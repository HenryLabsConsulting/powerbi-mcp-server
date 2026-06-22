"""MCP tool implementations for semantic model operations.

Tools: list_tables, read_table, list_measures, read_measure,
       create_measure, update_measure, delete_measure,
       list_relationships, create_relationship, read_data_sources.
"""

from .config import Config
from . import tmdl_parser


def list_tables(config: Config) -> list[dict] | dict:
    """Return all tables with name, type classification, column/measure counts."""
    try:
        tables = tmdl_parser.get_all_tables(config)
    except Exception as e:
        return {"error": f"Failed to parse tables: {e}"}

    results = []
    for t in tables:
        name = t.get("name", "")
        col_count = len(t.get("columns", []))
        calc_col_count = len(t.get("calculated_columns", []))
        measure_count = len(t.get("measures", []))
        partition_count = len(t.get("partitions", []))

        # Classify table type heuristically
        name_lower = name.lower()
        if name_lower.startswith("fact"):
            table_type = "fact"
        elif name_lower.startswith("dim"):
            table_type = "dimension"
        elif name_lower.startswith("bridge"):
            table_type = "bridge"
        elif measure_count > 0 and col_count == 0:
            table_type = "measure_table"
        else:
            table_type = "other"

        results.append({
            "name": name,
            "type": table_type,
            "columns": col_count,
            "calculated_columns": calc_col_count,
            "measures": measure_count,
            "partitions": partition_count,
            "lineageTag": t.get("lineageTag"),
        })

    return results


def read_table(config: Config, table_name: str) -> dict:
    """Return the full parsed TMDL definition for a specific table.

    Includes columns, calculated columns, measures, and partitions.
    """
    try:
        tables = tmdl_parser.get_all_tables(config)
    except Exception as e:
        return {"error": f"Failed to parse tables: {e}"}

    table_name_lower = table_name.lower().strip()
    for t in tables:
        if t.get("name", "").lower().strip() == table_name_lower:
            return t

    table_names = [t["name"] for t in tables]
    return {
        "error": f"Table '{table_name}' not found.",
        "available_tables": table_names,
    }


def list_measures(config: Config, table_name: str | None = None) -> list[dict] | dict:
    """Return all measures, optionally filtered by table name.

    Each measure includes name, table, expression (DAX), formatString, description.
    """
    try:
        measures = tmdl_parser.get_all_measures(config, table_name)
        if table_name and not measures:
            # Check if the table exists at all
            tables = tmdl_parser.get_all_tables(config)
            table_names = [t["name"] for t in tables]
            if not any(t.lower() == table_name.lower() for t in table_names):
                return {
                    "error": f"Table '{table_name}' not found.",
                    "available_tables": table_names,
                }
            # Table exists but has no measures
            return []
        return measures
    except Exception as e:
        return {"error": f"Failed to parse measures: {e}"}


def read_measure(
    config: Config, measure_name: str, table_name: str | None = None
) -> dict:
    """Return full DAX expression and metadata for a specific measure.

    If table_name is not provided, searches all tables. Returns the first match.
    If multiple tables have a measure with the same name and no table_name is
    specified, returns the first match with a note about ambiguity.
    """
    try:
        all_measures = tmdl_parser.get_all_measures(config, table_name)
    except Exception as e:
        return {"error": f"Failed to parse measures: {e}"}

    measure_name_lower = measure_name.lower().strip()
    matches = [m for m in all_measures if m["name"].lower().strip() == measure_name_lower]

    if not matches:
        # Provide available measure names for discoverability. Reuse the measures
        # already parsed above when the search was unfiltered, to avoid a second
        # full re-parse of every table file on a miss.
        if table_name is None:
            source_measures = all_measures
        else:
            source_measures = tmdl_parser.get_all_measures(config)
        all_names = [m["name"] for m in source_measures]
        return {
            "error": f"Measure '{measure_name}' not found.",
            "available_measures": all_names[:50],  # cap to avoid huge responses
        }

    result = matches[0]
    if len(matches) > 1:
        result["note"] = (
            f"Multiple measures named '{measure_name}' found in tables: "
            f"{[m['table'] for m in matches]}. Returning the first. "
            "Specify table_name to disambiguate."
        )

    return result


def create_measure(
    config: Config,
    table_name: str,
    measure_name: str,
    expression: str,
    format_string: str | None = None,
    description: str | None = None,
    display_folder: str | None = None,
) -> dict:
    """Create a new DAX measure in a table's TMDL file.

    Validates that the table exists and the measure name is unique within it.
    Creates a .bak backup before writing.
    """
    if config.read_only:
        return {
            "error": "Server is in read-only mode. Set POWERBI_MCP_READ_ONLY=false to enable writes."
        }

    if not measure_name or not measure_name.strip():
        return {"error": "measure_name is required."}
    if not expression or not expression.strip():
        return {"error": "expression (DAX) is required."}
    if not table_name or not table_name.strip():
        return {"error": "table_name is required."}

    # Path confinement check
    table_file = tmdl_parser.find_table_file(config, table_name)
    if table_file and not config.is_within_project(table_file):
        return {"error": "Invalid path: must be within the .pbip project directory."}

    try:
        result = tmdl_parser.add_measure_to_table(
            config,
            table_name=table_name,
            measure_name=measure_name,
            expression=expression,
            format_string=format_string,
            description=description,
            display_folder=display_folder,
        )
        return {"success": True, **result}
    except ValueError as e:
        return {"error": str(e)}
    except PermissionError:
        return {
            "error": "File is locked, likely by Power BI Desktop. Close Power BI Desktop and try again."
        }
    except OSError as e:
        return {"error": f"Write failed: {e}"}


def update_measure(
    config: Config,
    measure_name: str,
    table_name: str,
    expression: str | None = None,
    format_string: str | None = ...,
    description: str | None = ...,
    display_folder: str | None = ...,
) -> dict:
    """Update an existing measure's DAX expression or metadata.

    Only the fields provided are changed; others are preserved.
    Creates a .bak backup before writing.
    """
    if config.read_only:
        return {
            "error": "Server is in read-only mode. Set POWERBI_MCP_READ_ONLY=false to enable writes."
        }

    if not measure_name or not measure_name.strip():
        return {"error": "measure_name is required."}
    if not table_name or not table_name.strip():
        return {"error": "table_name is required."}

    # At least one field must be changing
    if (
        expression is None
        and format_string is ...
        and description is ...
        and display_folder is ...
    ):
        return {"error": "At least one field (expression, format_string, description, display_folder) must be provided."}

    table_file = tmdl_parser.find_table_file(config, table_name)
    if table_file and not config.is_within_project(table_file):
        return {"error": "Invalid path: must be within the .pbip project directory."}

    try:
        result = tmdl_parser.update_measure_in_table(
            config,
            table_name=table_name,
            measure_name=measure_name,
            expression=expression,
            format_string=format_string,
            description=description,
            display_folder=display_folder,
        )
        return {"success": True, **result}
    except ValueError as e:
        return {"error": str(e)}
    except PermissionError:
        return {
            "error": "File is locked, likely by Power BI Desktop. Close Power BI Desktop and try again."
        }
    except OSError as e:
        return {"error": f"Write failed: {e}"}


def delete_measure(
    config: Config,
    measure_name: str,
    table_name: str,
) -> dict:
    """Delete a measure from a table's TMDL file.

    Creates a .bak backup before writing for safety.
    """
    if config.read_only:
        return {
            "error": "Server is in read-only mode. Set POWERBI_MCP_READ_ONLY=false to enable writes."
        }

    if not measure_name or not measure_name.strip():
        return {"error": "measure_name is required."}
    if not table_name or not table_name.strip():
        return {"error": "table_name is required."}

    table_file = tmdl_parser.find_table_file(config, table_name)
    if table_file and not config.is_within_project(table_file):
        return {"error": "Invalid path: must be within the .pbip project directory."}

    try:
        result = tmdl_parser.delete_measure_from_table(
            config,
            table_name=table_name,
            measure_name=measure_name,
        )
        return {"success": True, **result}
    except ValueError as e:
        return {"error": str(e)}
    except PermissionError:
        return {
            "error": "File is locked, likely by Power BI Desktop. Close Power BI Desktop and try again."
        }
    except OSError as e:
        return {"error": f"Write failed: {e}"}


def list_relationships(config: Config) -> list[dict] | dict:
    """Return all model relationships with fromTable, fromColumn, toTable, toColumn, isActive."""
    try:
        return tmdl_parser.get_relationships(config)
    except Exception as e:
        return {"error": f"Failed to parse relationships: {e}"}


def create_relationship(
    config: Config,
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    is_active: bool = True,
    cross_filtering: str | None = None,
) -> dict:
    """Create a new relationship in relationships.tmdl.

    Validates that the exact relationship doesn't already exist.
    Creates a .bak backup before writing.
    """
    if config.read_only:
        return {
            "error": "Server is in read-only mode. Set POWERBI_MCP_READ_ONLY=false to enable writes."
        }

    if not from_table or not from_column or not to_table or not to_column:
        return {"error": "from_table, from_column, to_table, and to_column are all required."}

    # Validate cross_filtering value if provided
    valid_cross = {"oneDirection", "bothDirections", "automatic", None}
    if cross_filtering and cross_filtering not in valid_cross:
        return {
            "error": f"Invalid crossFilteringBehavior: '{cross_filtering}'. "
            f"Valid values: oneDirection, bothDirections, automatic."
        }

    # Verify both tables exist
    tables = tmdl_parser.get_all_tables(config)
    table_names_lower = {t["name"].lower() for t in tables}
    if from_table.lower() not in table_names_lower:
        return {"error": f"from_table '{from_table}' not found in semantic model."}
    if to_table.lower() not in table_names_lower:
        return {"error": f"to_table '{to_table}' not found in semantic model."}

    # Verify columns exist in the respective tables
    for t in tables:
        if t["name"].lower() == from_table.lower():
            all_cols = [c["name"].lower() for c in t.get("columns", [])]
            all_cols += [c["name"].lower() for c in t.get("calculated_columns", [])]
            if from_column.lower() not in all_cols:
                return {
                    "error": f"Column '{from_column}' not found in table '{from_table}'.",
                    "available_columns": [c["name"] for c in t.get("columns", [])]
                    + [c["name"] for c in t.get("calculated_columns", [])],
                }
        if t["name"].lower() == to_table.lower():
            all_cols = [c["name"].lower() for c in t.get("columns", [])]
            all_cols += [c["name"].lower() for c in t.get("calculated_columns", [])]
            if to_column.lower() not in all_cols:
                return {
                    "error": f"Column '{to_column}' not found in table '{to_table}'.",
                    "available_columns": [c["name"] for c in t.get("columns", [])]
                    + [c["name"] for c in t.get("calculated_columns", [])],
                }

    # Path confinement
    if not config.is_within_project(config.relationships_path):
        return {"error": "Invalid path: must be within the .pbip project directory."}

    try:
        result = tmdl_parser.add_relationship(
            config,
            from_table=from_table,
            from_column=from_column,
            to_table=to_table,
            to_column=to_column,
            is_active=is_active,
            cross_filtering=cross_filtering,
        )
        return {"success": True, **result}
    except ValueError as e:
        return {"error": str(e)}
    except PermissionError:
        return {
            "error": "File is locked, likely by Power BI Desktop. Close Power BI Desktop and try again."
        }
    except OSError as e:
        return {"error": f"Write failed: {e}"}


def read_data_sources(config: Config) -> dict:
    """Return data source information from the semantic model.

    Reads expressions.tmdl for shared expressions (M/Power Query data sources)
    and summarizes partition sources from tables. Sanitizes connection strings
    to remove credentials.
    """
    result = {
        "expressions": [],
        "table_partitions": [],
    }

    # Parse expressions.tmdl (shared functions / data sources)
    try:
        expressions = tmdl_parser.parse_expressions_file(config)
        for expr in expressions:
            result["expressions"].append({
                "name": expr["name"],
                "expression": _sanitize_expression(expr.get("expression", "")),
                "lineageTag": expr.get("lineageTag"),
                "queryGroup": expr.get("queryGroup"),
            })
    except Exception as e:
        result["expressions_error"] = f"Failed to parse expressions: {e}"

    # Summarize partition sources from each table
    try:
        tables = tmdl_parser.get_all_tables(config)
        for t in tables:
            for p in t.get("partitions", []):
                source_preview = _sanitize_expression(p.get("source", "") or "")
                # Truncate long M expressions to first 500 chars
                if len(source_preview) > 500:
                    source_preview = source_preview[:500] + "... [truncated]"
                result["table_partitions"].append({
                    "table": t["name"],
                    "partition": p["name"],
                    "type": p.get("type"),
                    "mode": p.get("mode"),
                    "source_preview": source_preview,
                })
    except Exception as e:
        result["partitions_error"] = f"Failed to parse table partitions: {e}"

    return result


def _sanitize_expression(expr: str) -> str:
    """Remove potential credentials from M/Power Query expressions.

    Replaces password-like patterns with [REDACTED].
    """
    import re

    # Redact common credential patterns
    patterns = [
        (r'(Password|password|pwd)\s*=\s*"[^"]*"', r'\1="[REDACTED]"'),
        (r'(Key|key|Secret|secret|Token|token)\s*=\s*"[^"]*"', r'\1="[REDACTED]"'),
        (r'(AccountKey|accountkey)\s*=\s*[^;,\s]+', r'\1=[REDACTED]'),
    ]

    result = expr
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result
