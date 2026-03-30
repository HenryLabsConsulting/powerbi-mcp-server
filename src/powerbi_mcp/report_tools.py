"""MCP tool implementations for report-layer operations.

Tools: list_pages, list_visuals, read_visual, update_visual,
       create_visual, delete_visual, clone_visual.
"""

import json

from .config import Config
from . import pbip_reader


def list_pages(config: Config) -> list[dict]:
    """Return all pages with displayName, visibility, dimensions, visual count."""
    return pbip_reader.get_all_pages(config)


def list_visuals(config: Config, page_name: str) -> list[dict] | dict:
    """Return all visuals on a page with type, position, bound measures/columns.

    page_name can be a displayName (case-insensitive) or a page hash.
    """
    result = pbip_reader.find_page_by_name(config, page_name)
    if result is None:
        pages = pbip_reader.get_all_pages(config)
        available = [p["displayName"] for p in pages]
        return {
            "error": f"Page '{page_name}' not found.",
            "available_pages": available,
        }

    _page_hash, page_dir = result
    visual_dirs = pbip_reader.list_visual_folders(page_dir)
    visuals = []

    for vdir in visual_dirs:
        vdata = pbip_reader.read_visual_json(vdir)
        if vdata:
            visuals.append(pbip_reader.extract_visual_summary(vdata))
        else:
            visuals.append({"id": vdir.name, "error": "parse_error"})

    return visuals


def read_visual(config: Config, page_name: str, visual_id: str) -> dict:
    """Return the full visual.json content for a specific visual.

    visual_id can be a hash or a label like "card:Estimate Win Rate".
    """
    page_result = pbip_reader.find_page_by_name(config, page_name)
    if page_result is None:
        pages = pbip_reader.get_all_pages(config)
        available = [p["displayName"] for p in pages]
        return {"error": f"Page '{page_name}' not found.", "available_pages": available}

    _page_hash, page_dir = page_result
    visual_dir = pbip_reader.find_visual(page_dir, visual_id)
    if visual_dir is None:
        visual_dirs = pbip_reader.list_visual_folders(page_dir)
        available = []
        for vdir in visual_dirs:
            vdata = pbip_reader.read_visual_json(vdir)
            if vdata:
                summary = pbip_reader.extract_visual_summary(vdata)
                available.append({"id": summary["id"], "label": summary["label"]})
            else:
                available.append({"id": vdir.name, "label": "parse_error"})
        return {
            "error": f"Visual '{visual_id}' not found on page '{page_name}'.",
            "available_visuals": available,
        }

    vdata = pbip_reader.read_visual_json(visual_dir)
    if vdata is None:
        return {"error": f"Failed to parse visual.json for '{visual_id}'."}

    return vdata


def update_visual(
    config: Config, page_name: str, visual_id: str, properties: dict
) -> dict:
    """Deep-merge properties into visual.json. Requires read-write mode.

    Creates .bak backup before writing. Validates JSON before commit.
    """
    if config.read_only:
        return {
            "error": "Server is in read-only mode. Set POWERBI_MCP_READ_ONLY=false to enable writes."
        }

    page_result = pbip_reader.find_page_by_name(config, page_name)
    if page_result is None:
        pages = pbip_reader.get_all_pages(config)
        available = [p["displayName"] for p in pages]
        return {"error": f"Page '{page_name}' not found.", "available_pages": available}

    _page_hash, page_dir = page_result
    visual_dir = pbip_reader.find_visual(page_dir, visual_id)
    if visual_dir is None:
        return {"error": f"Visual '{visual_id}' not found on page '{page_name}'."}

    # Path confinement check
    if not config.is_within_project(visual_dir / "visual.json"):
        return {"error": "Invalid path: must be within the .pbip project directory."}

    current = pbip_reader.read_visual_json(visual_dir)
    if current is None:
        return {"error": f"Failed to read current visual.json for '{visual_id}'."}

    # Deep merge
    merged = pbip_reader.deep_merge(current, properties)

    try:
        result = pbip_reader.write_visual_json(visual_dir, merged)
        return {"success": True, **result}
    except ValueError as e:
        return {"error": f"JSON validation failed: {e}"}
    except PermissionError:
        return {
            "error": "File is locked, likely by Power BI Desktop. Close Power BI Desktop and try again."
        }
    except OSError as e:
        return {"error": f"Write failed: {e}"}


def create_visual(
    config: Config, page_name: str, visual_definition: dict
) -> dict:
    """Create a new visual on a page. Requires read-write mode.

    visual_definition should contain at minimum:
      - position: {x, y, width, height, z, tabOrder}
      - visual: {visualType: "...", query: {...}, ...}
    """
    if config.read_only:
        return {
            "error": "Server is in read-only mode. Set POWERBI_MCP_READ_ONLY=false to enable writes."
        }

    page_result = pbip_reader.find_page_by_name(config, page_name)
    if page_result is None:
        pages = pbip_reader.get_all_pages(config)
        available = [p["displayName"] for p in pages]
        return {"error": f"Page '{page_name}' not found.", "available_pages": available}

    _page_hash, page_dir = page_result

    # Path confinement check
    visuals_dir = page_dir / "visuals"
    if not config.is_within_project(visuals_dir):
        return {"error": "Invalid path: must be within the .pbip project directory."}

    try:
        result = pbip_reader.create_visual_dir(page_dir, visual_definition)
        return {"success": True, **result}
    except ValueError as e:
        return {"error": f"Validation failed: {e}"}
    except OSError as e:
        return {"error": f"Create failed: {e}"}


def delete_visual(
    config: Config, page_name: str, visual_id: str
) -> dict:
    """Delete a visual from a page. Moves to .deleted backup. Requires read-write mode."""
    if config.read_only:
        return {
            "error": "Server is in read-only mode. Set POWERBI_MCP_READ_ONLY=false to enable writes."
        }

    page_result = pbip_reader.find_page_by_name(config, page_name)
    if page_result is None:
        pages = pbip_reader.get_all_pages(config)
        available = [p["displayName"] for p in pages]
        return {"error": f"Page '{page_name}' not found.", "available_pages": available}

    _page_hash, page_dir = page_result
    visual_dir = pbip_reader.find_visual(page_dir, visual_id)
    if visual_dir is None:
        return {"error": f"Visual '{visual_id}' not found on page '{page_name}'."}

    if not config.is_within_project(visual_dir / "visual.json"):
        return {"error": "Invalid path: must be within the .pbip project directory."}

    try:
        result = pbip_reader.delete_visual_dir(visual_dir)
        return {"success": True, **result}
    except PermissionError:
        return {
            "error": "File is locked, likely by Power BI Desktop. Close Power BI Desktop and try again."
        }
    except OSError as e:
        return {"error": f"Delete failed: {e}"}


def clone_visual(
    config: Config, page_name: str, visual_id: str, position_override: dict | None = None
) -> dict:
    """Clone an existing visual to a new copy with optional position override. Requires read-write mode."""
    if config.read_only:
        return {
            "error": "Server is in read-only mode. Set POWERBI_MCP_READ_ONLY=false to enable writes."
        }

    page_result = pbip_reader.find_page_by_name(config, page_name)
    if page_result is None:
        pages = pbip_reader.get_all_pages(config)
        available = [p["displayName"] for p in pages]
        return {"error": f"Page '{page_name}' not found.", "available_pages": available}

    _page_hash, page_dir = page_result
    visual_dir = pbip_reader.find_visual(page_dir, visual_id)
    if visual_dir is None:
        return {"error": f"Visual '{visual_id}' not found on page '{page_name}'."}

    try:
        result = pbip_reader.clone_visual_dir(page_dir, visual_dir, position_override)
        return {"success": True, **result}
    except ValueError as e:
        return {"error": f"Clone failed: {e}"}
    except OSError as e:
        return {"error": f"Clone failed: {e}"}
