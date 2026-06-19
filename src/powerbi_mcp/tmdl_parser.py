"""Line-by-line state machine parser for .tmdl files.

Extracts tables, columns, measures (with full multi-line DAX), calculated columns,
and relationships from the TMDL format.

TMDL uses tab-based indentation:
- Level 0: table, relationship (top-level blocks)
- Level 1: column, measure, partition, annotation (under table)
- Level 2: properties like formatString, lineageTag, expression (under column/measure)
"""

import shutil
import uuid
from pathlib import Path

from .config import Config


def _indent_level(line: str) -> int:
    """Count leading tabs."""
    count = 0
    for ch in line:
        if ch == "\t":
            count += 1
        else:
            break
    return count


def _strip_quotes(name: str) -> str:
    """Remove surrounding single quotes from TMDL identifiers like 'Measures (2)'."""
    name = name.strip()
    if name.startswith("'") and name.endswith("'"):
        return name[1:-1]
    return name


def _extract_backtick_expression(lines: list[str], start_idx: int) -> tuple[str, int]:
    """Extract a multi-line expression delimited by triple backticks.

    start_idx points to the line containing the opening ```.
    Returns (expression_text, index_of_closing_backtick_line).
    """
    expr_lines = []
    i = start_idx + 1
    while i < len(lines):
        if lines[i].strip() == "```":
            return ("\n".join(expr_lines).strip(), i)
        expr_lines.append(lines[i].strip())
        i += 1
    # No closing backticks found — return what we have
    return ("\n".join(expr_lines).strip(), i - 1)


def parse_table_file(file_path: Path) -> dict:
    """Parse a single .tmdl table file.

    Returns:
        {
            "name": str,
            "lineageTag": str | None,
            "columns": [...],
            "measures": [...],
            "calculated_columns": [...],
            "partitions": [...],
        }
    """
    text = file_path.read_text(encoding="utf-8")
    # Normalize line endings (some files have \r\n)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    table_name = ""
    table_lineage_tag = None
    columns = []
    measures = []
    calculated_columns = []
    partitions = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = _indent_level(line)

        # Table declaration (level 0)
        if indent == 0 and stripped.startswith("table "):
            table_name = _strip_quotes(stripped[6:].strip())
            i += 1
            continue

        # Table-level lineageTag
        if indent == 1 and stripped.startswith("lineageTag:") and not columns and not measures:
            table_lineage_tag = stripped.split(":", 1)[1].strip()
            i += 1
            continue

        # Measure block (level 1)
        if indent == 1 and stripped.startswith("measure "):
            measure, i = _parse_measure_block(lines, i)
            if measure:
                measures.append(measure)
            continue

        # Column block (level 1) — may be calculated column if it has expression
        if indent == 1 and stripped.startswith("column "):
            column, i = _parse_column_block(lines, i)
            if column:
                if column.get("expression"):
                    calculated_columns.append(column)
                else:
                    columns.append(column)
            continue

        # Partition block (level 1)
        if indent == 1 and stripped.startswith("partition "):
            partition, i = _parse_partition_block(lines, i)
            if partition:
                partitions.append(partition)
            continue

        i += 1

    return {
        "name": table_name,
        "lineageTag": table_lineage_tag,
        "columns": columns,
        "measures": measures,
        "calculated_columns": calculated_columns,
        "partitions": partitions,
    }


def _parse_measure_block(lines: list[str], start: int) -> tuple[dict | None, int]:
    """Parse a measure block starting at the 'measure ...' line.

    Measure format:
        measure 'Name' = ```
            DAX expression
            ```
            formatString: ...
            lineageTag: ...
    OR:
        measure 'Name' = SOME_INLINE_EXPRESSION
            formatString: ...
    """
    stripped = lines[start].strip()
    # Extract name and possible inline expression
    rest = stripped[8:]  # after "measure "

    measure = {
        "name": "",
        "expression": "",
        "formatString": None,
        "description": None,
        "lineageTag": None,
        "displayFolder": None,
    }

    # Split on " = " to get name and expression start
    # Handle both "measure Name = ```" and "measure Name =" (trailing =)
    if " = " in rest or rest.endswith(" =") or rest.endswith("="):
        if " = " in rest:
            name_part, expr_start = rest.split(" = ", 1)
        else:
            # "measure Name =" with nothing after =
            name_part = rest[:-1].rstrip()
            expr_start = ""
        measure["name"] = _strip_quotes(name_part)

        expr_start = expr_start.strip()
        if expr_start == "```":
            # Multi-line expression in backtick block
            expr, end_idx = _extract_backtick_expression(lines, start)
            measure["expression"] = expr
            i = end_idx + 1
        elif not expr_start:
            # Expression follows on subsequent indented lines (no backticks)
            # Collect lines at indent >= 3 until we hit a property line (indent 2)
            i = start + 1
            expr_lines = []
            while i < len(lines):
                line = lines[i]
                s = line.strip()
                ind = _indent_level(line)
                if not s:
                    i += 1
                    continue
                if ind >= 3:
                    expr_lines.append(s)
                    i += 1
                else:
                    break
            measure["expression"] = "\n".join(expr_lines).strip()
        else:
            # Inline expression on same line
            measure["expression"] = expr_start
            i = start + 1
    else:
        measure["name"] = _strip_quotes(rest)
        i = start + 1

    # Parse properties (level 2+) until we hit another level-1 block or end
    while i < len(lines):
        line = lines[i]
        indent = _indent_level(line)
        s = line.strip()

        if not s or (indent <= 1 and s and not s.startswith("annotation ")):
            # Empty line at level 1 might just be spacing — peek ahead
            if not s:
                i += 1
                continue
            break

        if indent >= 2:
            if s.startswith("formatString:"):
                measure["formatString"] = s.split(":", 1)[1].strip()
            elif s.startswith("lineageTag:"):
                measure["lineageTag"] = s.split(":", 1)[1].strip()
            elif s.startswith("description:"):
                measure["description"] = s.split(":", 1)[1].strip()
            elif s.startswith("displayFolder:"):
                measure["displayFolder"] = s.split(":", 1)[1].strip()
        elif indent == 1 and s.startswith("annotation "):
            # Skip annotations within the measure block
            pass
        else:
            break

        i += 1

    return (measure, i)


def _parse_column_block(lines: list[str], start: int) -> tuple[dict | None, int]:
    """Parse a column block starting at the 'column ...' line.

    Column can be:
        column Name             (regular column)
        column Name = ```...``` (calculated column with backtick expression)
    """
    stripped = lines[start].strip()
    rest = stripped[7:]  # after "column "

    column = {
        "name": "",
        "expression": None,
        "formatString": None,
        "lineageTag": None,
        "summarizeBy": None,
        "sourceColumn": None,
        "sortByColumn": None,
        "isNameInferred": False,
    }

    if " = " in rest:
        name_part, expr_start = rest.split(" = ", 1)
        column["name"] = _strip_quotes(name_part)

        if expr_start.strip() == "```":
            expr, end_idx = _extract_backtick_expression(lines, start)
            column["expression"] = expr
            i = end_idx + 1
        else:
            column["expression"] = expr_start.strip()
            i = start + 1
    else:
        column["name"] = _strip_quotes(rest)
        i = start + 1

    # Parse properties
    while i < len(lines):
        line = lines[i]
        indent = _indent_level(line)
        s = line.strip()

        if not s:
            i += 1
            continue

        if indent < 2:
            break

        if s.startswith("formatString:"):
            column["formatString"] = s.split(":", 1)[1].strip()
        elif s.startswith("lineageTag:"):
            column["lineageTag"] = s.split(":", 1)[1].strip()
        elif s.startswith("summarizeBy:"):
            column["summarizeBy"] = s.split(":", 1)[1].strip()
        elif s.startswith("sourceColumn:"):
            column["sourceColumn"] = s.split(":", 1)[1].strip()
        elif s.startswith("sortByColumn:"):
            column["sortByColumn"] = s.split(":", 1)[1].strip()
        elif s == "isNameInferred":
            column["isNameInferred"] = True
        elif s.startswith("annotation "):
            pass  # skip annotations

        i += 1

    return (column, i)


def _parse_partition_block(lines: list[str], start: int) -> tuple[dict | None, int]:
    """Parse a partition block. Extracts name, mode, and source expression."""
    stripped = lines[start].strip()
    rest = stripped[10:]  # after "partition "

    partition = {"name": "", "mode": None, "source": None, "type": None}

    # "partition DimDate = calculated"
    if " = " in rest:
        name_part, type_part = rest.split(" = ", 1)
        partition["name"] = _strip_quotes(name_part)
        partition["type"] = type_part.strip()
    else:
        partition["name"] = _strip_quotes(rest)

    i = start + 1
    while i < len(lines):
        line = lines[i]
        indent = _indent_level(line)
        s = line.strip()

        if not s:
            i += 1
            continue

        if indent < 2:
            break

        if s.startswith("mode:"):
            partition["mode"] = s.split(":", 1)[1].strip()
        elif s.startswith("source") and "= ```" in s:
            expr, end_idx = _extract_backtick_expression(lines, i)
            partition["source"] = expr
            i = end_idx + 1
            continue
        elif s.startswith("source ="):
            partition["source"] = s.split("=", 1)[1].strip()

        i += 1

    return (partition, i)


def parse_relationships_file(file_path: Path) -> list[dict]:
    """Parse relationships.tmdl into a list of relationship dicts.

    Each relationship block:
        relationship {name}
            fromColumn: {Table}.{Column}  (or {Table}.'{Column}')
            toColumn: {Table}.{Column}
            isActive: true/false
            crossFilteringBehavior: ...
    """
    if not file_path.exists():
        return []

    text = file_path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    relationships = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if stripped.startswith("relationship "):
            rel_name = stripped[13:].strip()
            rel = {
                "name": rel_name,
                "fromTable": None,
                "fromColumn": None,
                "toTable": None,
                "toColumn": None,
                "isActive": True,
                "crossFilteringBehavior": None,
            }

            i += 1
            while i < len(lines):
                line = lines[i]
                indent = _indent_level(line)
                s = line.strip()

                if not s:
                    i += 1
                    continue

                if indent == 0:
                    break

                if s.startswith("fromColumn:"):
                    table, col = _parse_table_column_ref(s.split(":", 1)[1].strip())
                    rel["fromTable"] = table
                    rel["fromColumn"] = col
                elif s.startswith("toColumn:"):
                    table, col = _parse_table_column_ref(s.split(":", 1)[1].strip())
                    rel["toTable"] = table
                    rel["toColumn"] = col
                elif s.startswith("isActive:"):
                    rel["isActive"] = s.split(":", 1)[1].strip().lower() != "false"
                elif s.startswith("crossFilteringBehavior:"):
                    rel["crossFilteringBehavior"] = s.split(":", 1)[1].strip()

                i += 1

            relationships.append(rel)
            continue

        i += 1

    return relationships


def _parse_table_column_ref(ref: str) -> tuple[str, str]:
    """Parse 'Table.Column' or 'Table.'Column Name'' into (table, column).

    Handles quoted column names like FactJob.'Job Date'.
    """
    ref = ref.strip()

    # Find the dot separator — but it could be inside quotes
    # Pattern: TableName.ColumnName or TableName.'Column Name'
    dot_idx = ref.find(".")
    if dot_idx == -1:
        return ("", ref)

    table = ref[:dot_idx]
    col = ref[dot_idx + 1:]
    return (table, _strip_quotes(col))


def get_all_tables(config: Config) -> list[dict]:
    """Parse all .tmdl table files and return parsed table dicts."""
    if not config.tables_dir.exists():
        return []

    tables = []
    for tmdl_file in sorted(config.tables_dir.glob("*.tmdl")):
        try:
            table = parse_table_file(tmdl_file)
            tables.append(table)
        except Exception as e:
            tables.append({
                "name": tmdl_file.stem,
                "parse_error": str(e),
                "columns": [],
                "measures": [],
                "calculated_columns": [],
                "partitions": [],
            })

    return tables


def get_all_measures(config: Config, table_name: str | None = None) -> list[dict]:
    """Extract all measures, optionally filtered by table name."""
    tables = get_all_tables(config)
    measures = []

    for table in tables:
        if table_name and table.get("name", "").lower() != table_name.lower():
            continue
        for m in table.get("measures", []):
            measures.append({
                "name": m["name"],
                "table": table["name"],
                "expression": m["expression"],
                "formatString": m.get("formatString"),
                "description": m.get("description"),
                "lineageTag": m.get("lineageTag"),
                "displayFolder": m.get("displayFolder"),
            })

    return measures


def get_relationships(config: Config) -> list[dict]:
    """Parse and return all relationships."""
    return parse_relationships_file(config.relationships_path)


# ---------------------------------------------------------------------------
# TMDL Write Operations
# ---------------------------------------------------------------------------


def _generate_lineage_tag() -> str:
    """Generate a new GUID lineage tag."""
    return str(uuid.uuid4())


def _backup_file(file_path: Path) -> Path:
    """Create a .bak backup of a file before writing. Returns backup path."""
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")
    shutil.copy2(file_path, backup_path)
    return backup_path


def _format_measure_tmdl(
    name: str,
    expression: str,
    format_string: str | None = None,
    description: str | None = None,
    display_folder: str | None = None,
    lineage_tag: str | None = None,
    extra_lines: list[str] | None = None,
) -> str:
    """Format a measure as a TMDL text block (with leading tab for level 1).

    Returns the text block ready to be inserted into a table file. `extra_lines`
    holds child lines this formatter does not regenerate (annotations,
    formatStringDefinition, etc.), re-emitted verbatim so an update preserves them.
    """
    tag = lineage_tag or _generate_lineage_tag()

    # Quote name if it contains spaces or special characters
    quoted_name = f"'{name}'" if " " in name or "(" in name or ")" in name else name

    lines = []
    # Multi-line expression uses backtick block
    expr_lines = expression.strip().split("\n")
    if len(expr_lines) > 1 or len(expression) > 80:
        lines.append(f"\tmeasure {quoted_name} = ```")
        for eline in expr_lines:
            lines.append(f"\t\t\t{eline}")
        lines.append("\t\t\t```")
    else:
        lines.append(f"\tmeasure {quoted_name} = {expression.strip()}")

    if format_string:
        lines.append(f"\t\tformatString: {format_string}")
    if description:
        lines.append(f"\t\tdescription: {description}")
    if display_folder:
        lines.append(f"\t\tdisplayFolder: {display_folder}")
    lines.append(f"\t\tlineageTag: {tag}")
    if extra_lines:
        lines.extend(extra_lines)
    lines.append("")

    return "\n".join(lines)


def find_table_file(config: Config, table_name: str) -> Path | None:
    """Find the .tmdl file for a given table name.

    Matches by parsing each file's table declaration, since filenames
    may differ from the table name (e.g., 'Measures (2).tmdl').
    """
    if not config.tables_dir.exists():
        return None

    for tmdl_file in config.tables_dir.glob("*.tmdl"):
        try:
            text = tmdl_file.read_text(encoding="utf-8")
            for raw_line in text.split("\n"):
                stripped = raw_line.strip()
                if stripped.startswith("table "):
                    parsed_name = _strip_quotes(stripped[6:].strip())
                    if parsed_name.lower() == table_name.lower():
                        return tmdl_file
                    break  # Only check first table declaration
        except OSError:
            continue

    return None


def add_measure_to_table(
    config: Config,
    table_name: str,
    measure_name: str,
    expression: str,
    format_string: str | None = None,
    description: str | None = None,
    display_folder: str | None = None,
) -> dict:
    """Add a new measure to a table's TMDL file.

    Returns dict with file path, backup path, and the generated lineage tag.
    Raises ValueError if measure already exists or table not found.
    """
    table_file = find_table_file(config, table_name)
    if table_file is None:
        raise ValueError(f"Table '{table_name}' not found in semantic model.")

    # Check the measure doesn't already exist in this table
    table_data = parse_table_file(table_file)
    for m in table_data.get("measures", []):
        if m["name"].lower() == measure_name.lower():
            raise ValueError(
                f"Measure '{measure_name}' already exists in table '{table_name}'."
            )

    lineage_tag = _generate_lineage_tag()
    measure_block = _format_measure_tmdl(
        name=measure_name,
        expression=expression,
        format_string=format_string,
        description=description,
        display_folder=display_folder,
        lineage_tag=lineage_tag,
    )

    # Read existing content and append the measure before any partition blocks
    # or at the end of the file
    text = table_file.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Find the best insertion point: before the first partition, or at end
    lines = text.split("\n")
    insert_idx = len(lines)
    for idx, line in enumerate(lines):
        if _indent_level(line) == 1 and line.strip().startswith("partition "):
            insert_idx = idx
            break

    # Ensure there's a blank line before the new measure
    measure_lines = measure_block.split("\n")
    if insert_idx > 0 and lines[insert_idx - 1].strip() != "":
        measure_lines = [""] + measure_lines

    new_lines = lines[:insert_idx] + measure_lines + lines[insert_idx:]
    new_text = "\n".join(new_lines)

    # Backup and write
    backup_path = _backup_file(table_file)
    table_file.write_text(new_text, encoding="utf-8")

    return {
        "file": str(table_file),
        "backup": str(backup_path),
        "lineageTag": lineage_tag,
    }


def update_measure_in_table(
    config: Config,
    table_name: str,
    measure_name: str,
    expression: str | None = None,
    format_string: str | None = ...,  # sentinel: ... means "don't change"
    description: str | None = ...,
    display_folder: str | None = ...,
) -> dict:
    """Update an existing measure's properties in a table's TMDL file.

    Only provided (non-sentinel) values are changed. Expression, formatString,
    description, and displayFolder can each be updated independently.

    Returns dict with file path and backup path.
    Raises ValueError if measure or table not found.
    """
    table_file = find_table_file(config, table_name)
    if table_file is None:
        raise ValueError(f"Table '{table_name}' not found in semantic model.")

    table_data = parse_table_file(table_file)
    existing = None
    for m in table_data.get("measures", []):
        if m["name"].lower() == measure_name.lower():
            existing = m
            break

    if existing is None:
        raise ValueError(
            f"Measure '{measure_name}' not found in table '{table_name}'."
        )

    # Build the updated measure using existing values as defaults
    new_expr = expression if expression is not None else existing["expression"]
    new_fmt = format_string if format_string is not ... else existing.get("formatString")
    new_desc = description if description is not ... else existing.get("description")
    new_folder = display_folder if display_folder is not ... else existing.get("displayFolder")
    lineage_tag = existing.get("lineageTag") or _generate_lineage_tag()

    # Find and replace the measure block in the file
    text = table_file.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    # Find the measure start line
    measure_start = None
    measure_name_lower = measure_name.lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if _indent_level(line) == 1 and stripped.startswith("measure "):
            rest = stripped[8:]
            if " = " in rest or rest.endswith(" =") or rest.endswith("="):
                name_part = rest.split(" = ", 1)[0] if " = " in rest else rest[:-1].rstrip()
                parsed = _strip_quotes(name_part).lower()
                if parsed == measure_name_lower:
                    measure_start = idx
                    break

    if measure_start is None:
        raise ValueError(
            f"Could not locate measure '{measure_name}' block in file."
        )

    # Find the end of the measure block
    measure_end = measure_start + 1
    # Skip backtick expression block if present
    if "```" in lines[measure_start]:
        # Find closing backticks
        while measure_end < len(lines):
            if lines[measure_end].strip() == "```":
                measure_end += 1
                break
            measure_end += 1

    # Continue past properties (indent >= 2) and annotations (indent 1 + annotation).
    # Capture any child line this formatter does not regenerate (annotations,
    # formatStringDefinition, isHidden, etc.) so the update preserves it verbatim.
    preserved_lines: list[str] = []
    regenerated = ("formatString:", "description:", "displayFolder:", "lineageTag:")
    while measure_end < len(lines):
        line = lines[measure_end]
        stripped = line.strip()
        indent = _indent_level(line)

        if not stripped:
            measure_end += 1
            continue

        if indent >= 2:
            if not stripped.startswith(regenerated):
                preserved_lines.append(line)
            measure_end += 1
            continue

        if indent == 1 and stripped.startswith("annotation "):
            preserved_lines.append(line)
            measure_end += 1
            continue

        break

    # Consume trailing blank lines that belong to this block
    while measure_end < len(lines) and lines[measure_end].strip() == "":
        measure_end += 1

    new_block = _format_measure_tmdl(
        name=existing["name"],  # preserve original casing
        expression=new_expr,
        format_string=new_fmt,
        description=new_desc,
        display_folder=new_folder,
        lineage_tag=lineage_tag,
        extra_lines=preserved_lines,
    )

    # Replace
    new_block_lines = new_block.split("\n")
    new_lines = lines[:measure_start] + new_block_lines + lines[measure_end:]
    new_text = "\n".join(new_lines)

    backup_path = _backup_file(table_file)
    table_file.write_text(new_text, encoding="utf-8")

    return {
        "file": str(table_file),
        "backup": str(backup_path),
        "lineageTag": lineage_tag,
    }


def delete_measure_from_table(
    config: Config,
    table_name: str,
    measure_name: str,
) -> dict:
    """Delete a measure from a table's TMDL file.

    Returns dict with file path and backup path.
    Raises ValueError if measure or table not found.
    """
    table_file = find_table_file(config, table_name)
    if table_file is None:
        raise ValueError(f"Table '{table_name}' not found in semantic model.")

    # Verify measure exists
    table_data = parse_table_file(table_file)
    found = False
    for m in table_data.get("measures", []):
        if m["name"].lower() == measure_name.lower():
            found = True
            break

    if not found:
        raise ValueError(
            f"Measure '{measure_name}' not found in table '{table_name}'."
        )

    text = table_file.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    # Find the measure start line
    measure_start = None
    measure_name_lower = measure_name.lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if _indent_level(line) == 1 and stripped.startswith("measure "):
            rest = stripped[8:]
            if " = " in rest or rest.endswith(" =") or rest.endswith("="):
                name_part = rest.split(" = ", 1)[0] if " = " in rest else rest[:-1].rstrip()
                parsed = _strip_quotes(name_part).lower()
                if parsed == measure_name_lower:
                    measure_start = idx
                    break

    if measure_start is None:
        raise ValueError(
            f"Could not locate measure '{measure_name}' block in file."
        )

    # Find end of measure block (same logic as update)
    measure_end = measure_start + 1
    if "```" in lines[measure_start]:
        while measure_end < len(lines):
            if lines[measure_end].strip() == "```":
                measure_end += 1
                break
            measure_end += 1

    while measure_end < len(lines):
        line = lines[measure_end]
        stripped = line.strip()
        indent = _indent_level(line)

        if not stripped:
            measure_end += 1
            continue

        if indent >= 2:
            measure_end += 1
            continue

        if indent == 1 and stripped.startswith("annotation "):
            measure_end += 1
            continue

        break

    # Consume trailing blank lines
    while measure_end < len(lines) and lines[measure_end].strip() == "":
        measure_end += 1

    # Remove the block
    new_lines = lines[:measure_start] + lines[measure_end:]
    new_text = "\n".join(new_lines)

    backup_path = _backup_file(table_file)
    table_file.write_text(new_text, encoding="utf-8")

    return {
        "file": str(table_file),
        "backup": str(backup_path),
    }


def add_relationship(
    config: Config,
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    is_active: bool = True,
    cross_filtering: str | None = None,
) -> dict:
    """Add a new relationship to relationships.tmdl.

    Returns dict with file path, backup path, and generated relationship name.
    Raises ValueError if the exact relationship already exists.
    """
    rel_path = config.relationships_path

    # Check for duplicate
    existing = parse_relationships_file(rel_path) if rel_path.exists() else []
    for r in existing:
        if (
            r.get("fromTable", "").lower() == from_table.lower()
            and r.get("fromColumn", "").lower() == from_column.lower()
            and r.get("toTable", "").lower() == to_table.lower()
            and r.get("toColumn", "").lower() == to_column.lower()
        ):
            raise ValueError(
                f"Relationship from {from_table}.{from_column} to "
                f"{to_table}.{to_column} already exists."
            )

    rel_name = str(uuid.uuid4())

    # Format the from/to column references (quote if needed)
    def _quote_col(col: str) -> str:
        if " " in col or "." in col:
            return f"'{col}'"
        return col

    lines = []
    lines.append(f"relationship {rel_name}")
    if not is_active:
        lines.append("\tisActive: false")
    if cross_filtering:
        lines.append(f"\tcrossFilteringBehavior: {cross_filtering}")
    lines.append(f"\tfromColumn: {from_table}.{_quote_col(from_column)}")
    lines.append(f"\ttoColumn: {to_table}.{_quote_col(to_column)}")
    lines.append("")

    block = "\n".join(lines) + "\n"

    # Backup and append
    backup_path = None
    if rel_path.exists():
        backup_path = _backup_file(rel_path)
        text = rel_path.read_text(encoding="utf-8")
        # Ensure trailing newline before appending
        if not text.endswith("\n"):
            text += "\n"
        text += block
    else:
        text = block

    rel_path.write_text(text, encoding="utf-8")

    return {
        "file": str(rel_path),
        "backup": str(backup_path) if backup_path else None,
        "relationship_name": rel_name,
    }


def parse_expressions_file(config: Config) -> list[dict]:
    """Parse expressions.tmdl for data source / shared expression definitions.

    Returns a list of dicts with name, expression, lineageTag, queryGroup.
    """
    expr_path = config.semantic_model_dir / "definition" / "expressions.tmdl"
    if not expr_path.exists():
        return []

    text = expr_path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    expressions = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if stripped.startswith("expression "):
            rest = stripped[11:]
            expr = {
                "name": "",
                "expression": "",
                "lineageTag": None,
                "queryGroup": None,
            }

            if " = " in rest or rest.endswith(" =") or rest.endswith("="):
                if " = " in rest:
                    name_part, expr_start = rest.split(" = ", 1)
                else:
                    name_part = rest[:-1].rstrip()
                    expr_start = ""
                expr["name"] = _strip_quotes(name_part)

                # Collect indented expression lines
                i += 1
                expr_lines = []
                while i < len(lines):
                    line = lines[i]
                    ind = _indent_level(line)
                    s = line.strip()

                    if not s:
                        i += 1
                        continue

                    if ind >= 2:
                        # Property lines vs continued M expression
                        if s.startswith("lineageTag:"):
                            expr["lineageTag"] = s.split(":", 1)[1].strip()
                        elif s.startswith("queryGroup:"):
                            expr["queryGroup"] = s.split(":", 1)[1].strip()
                        elif s.startswith("annotation "):
                            pass  # skip annotations
                        else:
                            expr_lines.append(s)
                        i += 1
                    elif ind == 1:
                        if s.startswith("lineageTag:"):
                            expr["lineageTag"] = s.split(":", 1)[1].strip()
                        elif s.startswith("queryGroup:"):
                            expr["queryGroup"] = s.split(":", 1)[1].strip()
                        elif s.startswith("annotation "):
                            pass
                        else:
                            break
                        i += 1
                    else:
                        break

                # Combine the initial expression fragment with collected lines
                if expr_start:
                    full_expr = expr_start.strip()
                    if expr_lines:
                        full_expr += "\n" + "\n".join(expr_lines)
                    expr["expression"] = full_expr.strip()
                else:
                    expr["expression"] = "\n".join(expr_lines).strip()
            else:
                expr["name"] = _strip_quotes(rest)
                i += 1

            expressions.append(expr)
            continue

        i += 1

    return expressions
