"""MCP tool implementations for semantic model operations.

Tools: list_measures, read_measure, list_relationships.
"""

from .config import Config
from . import tmdl_parser


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
        # Provide available measure names for discoverability
        all_names = [m["name"] for m in tmdl_parser.get_all_measures(config)]
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


def list_relationships(config: Config) -> list[dict] | dict:
    """Return all model relationships with fromTable, fromColumn, toTable, toColumn, isActive."""
    try:
        return tmdl_parser.get_relationships(config)
    except Exception as e:
        return {"error": f"Failed to parse relationships: {e}"}
