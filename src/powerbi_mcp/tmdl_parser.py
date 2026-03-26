"""Line-by-line state machine parser for .tmdl files.

Extracts tables, columns, measures (with full multi-line DAX), calculated columns,
and relationships from the TMDL format.

TMDL uses tab-based indentation:
- Level 0: table, relationship (top-level blocks)
- Level 1: column, measure, partition, annotation (under table)
- Level 2: properties like formatString, lineageTag, expression (under column/measure)
"""

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
