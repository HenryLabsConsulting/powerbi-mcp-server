"""Filesystem operations for the .Report tree.

Discovers pages, reads page.json metadata, discovers visuals,
reads/writes visual.json files with backup support.
"""

import copy
import json
import secrets
import shutil
from pathlib import Path

from .config import Config


def get_pages_metadata(config: Config) -> dict:
    """Read pages.json for page order and active page."""
    pages_json_path = config.pages_dir / "pages.json"
    if not pages_json_path.exists():
        return {"pageOrder": [], "activePageName": None}
    return json.loads(pages_json_path.read_text(encoding="utf-8"))


def list_page_folders(config: Config) -> list[Path]:
    """Return all page hash directories under pages/."""
    if not config.pages_dir.exists():
        return []
    return sorted(
        [p for p in config.pages_dir.iterdir() if p.is_dir()],
        key=lambda p: p.name,
    )


def read_page_json(page_dir: Path) -> dict | None:
    """Read page.json from a page hash directory."""
    page_json = page_dir / "page.json"
    if not page_json.exists():
        return None
    try:
        return json.loads(page_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def find_page_by_name(config: Config, page_name: str) -> tuple[str, Path] | None:
    """Resolve a displayName (case-insensitive) or hash to (hash, page_dir).

    Returns None if no match found.
    """
    page_name_lower = page_name.lower().strip()

    for page_dir in list_page_folders(config):
        # Direct hash match
        if page_dir.name.lower() == page_name_lower:
            return (page_dir.name, page_dir)

    # Name-based lookup
    for page_dir in list_page_folders(config):
        page_data = read_page_json(page_dir)
        if page_data and page_data.get("displayName", "").lower().strip() == page_name_lower:
            return (page_dir.name, page_dir)

    return None


def get_all_pages(config: Config) -> list[dict]:
    """Return all pages with metadata, ordered by pages.json pageOrder."""
    pages_meta = get_pages_metadata(config)
    page_order = pages_meta.get("pageOrder", [])

    # Build lookup: hash -> page_dir
    page_dirs = {p.name: p for p in list_page_folders(config)}

    results = []
    seen = set()

    # Ordered pages first
    for idx, page_hash in enumerate(page_order):
        if page_hash in page_dirs:
            page_data = read_page_json(page_dirs[page_hash])
            if page_data:
                visuals_dir = page_dirs[page_hash] / "visuals"
                visual_count = len(list(visuals_dir.iterdir())) if visuals_dir.exists() else 0
                results.append({
                    "id": page_hash,
                    "displayName": page_data.get("displayName", ""),
                    "displayOption": page_data.get("displayOption", ""),
                    "width": page_data.get("width"),
                    "height": page_data.get("height"),
                    "visibility": page_data.get("visibility", "Visible"),
                    "order": idx,
                    "visual_count": visual_count,
                })
                seen.add(page_hash)

    # Any folders not in pageOrder (shouldn't happen but defensive)
    for page_hash, page_dir in page_dirs.items():
        if page_hash not in seen:
            page_data = read_page_json(page_dir)
            if page_data:
                visuals_dir = page_dir / "visuals"
                visual_count = len(list(visuals_dir.iterdir())) if visuals_dir.exists() else 0
                results.append({
                    "id": page_hash,
                    "displayName": page_data.get("displayName", ""),
                    "displayOption": page_data.get("displayOption", ""),
                    "width": page_data.get("width"),
                    "height": page_data.get("height"),
                    "visibility": page_data.get("visibility", "Visible"),
                    "order": len(results),
                    "visual_count": visual_count,
                })

    return results


def list_visual_folders(page_dir: Path) -> list[Path]:
    """Return all visual hash directories under a page's visuals/ folder."""
    visuals_dir = page_dir / "visuals"
    if not visuals_dir.exists():
        return []
    return sorted(
        [v for v in visuals_dir.iterdir() if v.is_dir()],
        key=lambda v: v.name,
    )


def read_visual_json(visual_dir: Path) -> dict | None:
    """Read visual.json from a visual hash directory."""
    visual_json = visual_dir / "visual.json"
    if not visual_json.exists():
        return None
    try:
        return json.loads(visual_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def extract_visual_summary(visual_data: dict) -> dict:
    """Extract a human-readable summary from a visual.json dict."""
    position = visual_data.get("position", {})
    visual_inner = visual_data.get("visual", {})
    visual_type = visual_inner.get("visualType", "unknown")

    # Extract bound fields (measures and columns) from query state
    bound_fields = []
    query = visual_inner.get("query", {})
    query_state = query.get("queryState", {})
    for _role, role_data in query_state.items():
        projections = role_data.get("projections", [])
        for proj in projections:
            field = proj.get("field", {})
            ref = proj.get("queryRef", "")
            if "Measure" in field:
                measure_info = field["Measure"]
                entity = measure_info.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                prop = measure_info.get("Property", "")
                bound_fields.append({"type": "measure", "entity": entity, "property": prop, "queryRef": ref})
            elif "Column" in field:
                col_info = field["Column"]
                entity = col_info.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                prop = col_info.get("Property", "")
                bound_fields.append({"type": "column", "entity": entity, "property": prop, "queryRef": ref})

    # Build human-readable label: "type:primary_field"
    label = visual_type
    if bound_fields:
        primary = bound_fields[0].get("property", "")
        if primary:
            label = f"{visual_type}:{primary}"

    return {
        "id": visual_data.get("name", ""),
        "label": label,
        "visualType": visual_type,
        "x": position.get("x"),
        "y": position.get("y"),
        "z": position.get("z"),
        "width": position.get("width"),
        "height": position.get("height"),
        "tabOrder": position.get("tabOrder"),
        "bound_fields": bound_fields,
    }


def find_visual(config: Config, page_dir: Path, visual_id: str) -> Path | None:
    """Find a visual directory by hash ID or label match.

    visual_id can be:
    - A hash (direct folder name match)
    - A label like "card:Estimate Win Rate" (type:field match)

    Path confinement is enforced here so every caller (read, write, clone,
    delete) inherits it: a visual_id containing traversal segments (e.g.
    "..\\..\\secrets") that resolves outside the .pbip project is rejected
    rather than returned.
    """
    visuals_dir = page_dir / "visuals"
    if not visuals_dir.exists():
        return None

    # Direct hash match
    direct = visuals_dir / visual_id
    if direct.exists() and direct.is_dir() and config.is_within_project(direct):
        return direct

    # Label-based lookup: scan all visuals and match label
    visual_id_lower = visual_id.lower().strip()
    for vdir in list_visual_folders(page_dir):
        vdata = read_visual_json(vdir)
        if vdata:
            summary = extract_visual_summary(vdata)
            if summary["label"].lower() == visual_id_lower:
                return vdir

    return None


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. override values win for non-dict types."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# Keys that Power BI requires inside the "visual" object, never at root level.
_VISUAL_INNER_KEYS = {"visualContainerObjects", "drillFilterOtherVisuals"}


def normalize_visual_structure(data: dict) -> dict:
    """Ensure visual-inner keys live inside data["visual"], not at root.

    Power BI .pbip schema requires keys like visualContainerObjects and
    drillFilterOtherVisuals to be nested inside the "visual" object.
    If they appear at the root level (sibling of $schema, name, position),
    this function relocates them via deep merge into data["visual"].
    """
    visual = data.get("visual")
    if not isinstance(visual, dict):
        return data

    for key in _VISUAL_INNER_KEYS:
        if key in data:
            # Key is at root but belongs inside visual — relocate it
            root_value = data.pop(key)
            if key in visual and isinstance(visual[key], dict) and isinstance(root_value, dict):
                visual[key] = deep_merge(visual[key], root_value)
            else:
                visual[key] = root_value

    return data


def write_visual_json(visual_dir: Path, merged_data: dict) -> dict:
    """Write merged visual data to visual.json with backup.

    Returns dict with 'path' and 'backup' keys on success.
    Raises on failure.
    """
    visual_json = visual_dir / "visual.json"
    backup_path = visual_dir / "visual.json.bak"

    # Ensure visualContainerObjects etc. are inside "visual", not at root
    merged_data = normalize_visual_structure(merged_data)

    # Validate the merged data is serializable and round-trips clean
    try:
        json_str = json.dumps(merged_data, indent=2, ensure_ascii=False)
        json.loads(json_str)  # round-trip validation
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"Merged JSON is invalid: {e}") from e

    # Create backup
    if visual_json.exists():
        shutil.copy2(visual_json, backup_path)

    # Write
    try:
        visual_json.write_text(json_str, encoding="utf-8")
    except OSError as e:
        raise OSError(f"Failed to write visual.json: {e}") from e

    return {
        "path": str(visual_json),
        "backup": str(backup_path),
    }


def generate_visual_hash() -> str:
    """Generate a 20-character hex hash for a new visual directory name."""
    return secrets.token_hex(10)


def _validate_visual_definition(visual_data: dict) -> None:
    """Raise ValueError if a visual definition is missing keys Power BI requires.

    A visual.json without a position or a visual.visualType produces a .pbip that
    Power BI refuses to open, so reject it up front rather than writing a corrupt
    file. The error lists every missing key so the caller can fix them in one pass.
    """
    missing: list[str] = []

    position = visual_data.get("position")
    if not isinstance(position, dict):
        missing.append("position")

    visual = visual_data.get("visual")
    if not isinstance(visual, dict):
        missing.append("visual.visualType")
    elif not visual.get("visualType"):
        missing.append("visual.visualType")

    if missing:
        raise ValueError(
            "Visual definition is missing required keys: " + ", ".join(missing)
        )


def create_visual_dir(page_dir: Path, visual_data: dict) -> dict:
    """Create a new visual directory with visual.json under a page.

    Generates a unique hash for the directory name and writes visual.json.
    The visual_data must include at minimum: position and visual.visualType.

    The caller's dict is never mutated; a deep copy is made before any edits.

    Returns dict with 'visual_id', 'path' keys on success.
    Raises ValueError on invalid data, OSError on write failure.
    """
    # Validate required keys before touching the filesystem.
    _validate_visual_definition(visual_data)

    # Work on a deep copy so the caller's dict is left untouched.
    visual_data = copy.deepcopy(visual_data)

    visuals_dir = page_dir / "visuals"
    visuals_dir.mkdir(exist_ok=True)

    # Generate unique hash, retry if collision (extremely unlikely)
    for _ in range(10):
        visual_hash = generate_visual_hash()
        visual_dir = visuals_dir / visual_hash
        if not visual_dir.exists():
            break
    else:
        raise OSError("Failed to generate unique visual hash after 10 attempts.")

    # Inject the hash as the visual name
    visual_data["name"] = visual_hash

    # Ensure $schema is present
    if "$schema" not in visual_data:
        visual_data["$schema"] = (
            "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definition/visualContainer/2.7.0/schema.json"
        )

    # Ensure visualContainerObjects etc. are inside "visual", not at root
    visual_data = normalize_visual_structure(visual_data)

    # Validate serialization
    try:
        json_str = json.dumps(visual_data, indent=2, ensure_ascii=False)
        json.loads(json_str)  # round-trip check
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"Visual JSON is invalid: {e}") from e

    # Write
    visual_dir.mkdir()
    visual_json_path = visual_dir / "visual.json"
    visual_json_path.write_text(json_str, encoding="utf-8")

    return {
        "visual_id": visual_hash,
        "path": str(visual_json_path),
    }


def delete_visual_dir(visual_dir: Path) -> dict:
    """Delete a visual directory after creating a backup.

    Moves the entire visual directory to visual_dir.deleted as a safety net.
    Returns dict with 'deleted_id', 'backup_path' keys.
    """
    visual_id = visual_dir.name
    backup_dir = visual_dir.parent / f"{visual_id}.deleted"

    # If a previous .deleted backup exists, remove it
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    # Move instead of delete for safety
    shutil.move(str(visual_dir), str(backup_dir))

    return {
        "deleted_id": visual_id,
        "backup_path": str(backup_dir),
    }


def clone_visual_dir(page_dir: Path, source_dir: Path, position_override: dict | None = None) -> dict:
    """Clone an existing visual to a new directory with a new hash.

    Optionally override position (x, y, width, height, z, tabOrder).
    Returns dict with 'visual_id', 'path' keys.
    """
    source_data = read_visual_json(source_dir)
    if source_data is None:
        raise ValueError(f"Failed to read source visual at {source_dir}.")

    # Override position if provided
    if position_override:
        current_pos = source_data.get("position", {})
        current_pos.update(position_override)
        source_data["position"] = current_pos

    return create_visual_dir(page_dir, source_data)
