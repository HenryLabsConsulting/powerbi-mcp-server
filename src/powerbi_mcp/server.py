"""MCP server entry point for Power BI .pbip file access.

Registers all tools via FastMCP and runs on stdio transport.
Configuration is loaded at startup from environment variables and CLI args.
"""

import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

from .config import Config, parse_cli_args
from . import report_tools, model_tools

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("powerbi-mcp-server")

mcp = FastMCP("powerbi-mcp-server")

# Config is initialized lazily on first tool call to allow server to start
# and report its tool manifest even if the path is not yet configured.
_config: Config | None = None


def _get_config() -> Config:
    global _config
    if _config is None:
        cli_path = parse_cli_args()
        _config = Config(pbip_path=cli_path)
        mode_label = "read-only" if _config.read_only else "read-write"
        logger.info(f"Loaded .pbip: {_config.pbip_path} (mode: {mode_label})")
    return _config


@mcp.tool(
    name="list_pages",
    description=(
        "List all pages in the Power BI report with displayName, visibility, "
        "dimensions (width/height), page order, and visual count."
    ),
)
def tool_list_pages() -> str:
    """List all pages in the Power BI report."""
    try:
        config = _get_config()
        result = report_tools.list_pages(config)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="list_visuals",
    description=(
        "List all visuals on a specific page. Returns visual type, position "
        "(x, y, width, height), and bound measures/columns for each visual. "
        "Accepts page displayName (e.g. 'Overview') or page hash ID."
    ),
)
def tool_list_visuals(page_name: str) -> str:
    """List all visuals on a page.

    Args:
        page_name: Page displayName (case-insensitive) or page hash ID.
    """
    try:
        config = _get_config()
        result = report_tools.list_visuals(config, page_name)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="read_visual",
    description=(
        "Read the full visual.json content for a specific visual, including "
        "position, visualType, query bindings, formatting objects, and filters. "
        "Accepts page displayName + visual hash ID or label (e.g. 'card:Estimate Win Rate')."
    ),
)
def tool_read_visual(page_name: str, visual_id: str) -> str:
    """Read full visual configuration.

    Args:
        page_name: Page displayName (case-insensitive) or page hash ID.
        visual_id: Visual hash ID or label like 'card:Estimate Win Rate'.
    """
    try:
        config = _get_config()
        result = report_tools.read_visual(config, page_name, visual_id)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="update_visual",
    description=(
        "Update a visual's properties by deep-merging changes into visual.json. "
        "Creates a .bak backup before writing. Only works when POWERBI_MCP_READ_ONLY=false. "
        "Pass partial JSON — only the specified keys are changed, everything else is preserved."
    ),
)
def tool_update_visual(page_name: str, visual_id: str, properties: str) -> str:
    """Update visual properties via deep merge.

    Args:
        page_name: Page displayName (case-insensitive) or page hash ID.
        visual_id: Visual hash ID or label like 'card:Estimate Win Rate'.
        properties: JSON string of properties to merge into the visual.
    """
    try:
        config = _get_config()
    except Exception as e:
        return json.dumps({"error": str(e)})

    # Parse the properties JSON string
    try:
        props = json.loads(properties) if isinstance(properties, str) else properties
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON in properties: {e}"})

    if not isinstance(props, dict):
        return json.dumps({"error": "properties must be a JSON object (dict)."})

    result = report_tools.update_visual(config, page_name, visual_id, props)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="create_visual",
    description=(
        "Create a new visual on a page. Provide full visual definition as JSON including "
        "position (x, y, width, height, z, tabOrder) and visual config (visualType, query, objects). "
        "Returns the generated visual_id. Only works when POWERBI_MCP_READ_ONLY=false."
    ),
)
def tool_create_visual(page_name: str, visual_definition: str) -> str:
    """Create a new visual on a page.

    Args:
        page_name: Page displayName (case-insensitive) or page hash ID.
        visual_definition: JSON string with the full visual definition (position, visual).
    """
    try:
        config = _get_config()
    except Exception as e:
        return json.dumps({"error": str(e)})

    try:
        definition = json.loads(visual_definition) if isinstance(visual_definition, str) else visual_definition
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON in visual_definition: {e}"})

    if not isinstance(definition, dict):
        return json.dumps({"error": "visual_definition must be a JSON object (dict)."})

    result = report_tools.create_visual(config, page_name, definition)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="delete_visual",
    description=(
        "Delete a visual from a page. Moves the visual to a .deleted backup directory "
        "for safety (not permanent deletion). Only works when POWERBI_MCP_READ_ONLY=false."
    ),
)
def tool_delete_visual(page_name: str, visual_id: str) -> str:
    """Delete a visual from a page.

    Args:
        page_name: Page displayName (case-insensitive) or page hash ID.
        visual_id: Visual hash ID or label like 'card:Estimate Win Rate'.
    """
    try:
        config = _get_config()
        result = report_tools.delete_visual(config, page_name, visual_id)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="clone_visual",
    description=(
        "Clone an existing visual to create a copy on the same page. "
        "Optionally override position (x, y, width, height, z, tabOrder) for the clone. "
        "Useful for creating variants of existing visuals. Only works when POWERBI_MCP_READ_ONLY=false."
    ),
)
def tool_clone_visual(page_name: str, visual_id: str, position: str = "{}") -> str:
    """Clone an existing visual with optional position override.

    Args:
        page_name: Page displayName (case-insensitive) or page hash ID.
        visual_id: Visual hash ID or label of the source visual.
        position: Optional JSON string with position overrides (x, y, width, height, z, tabOrder).
    """
    try:
        config = _get_config()
    except Exception as e:
        return json.dumps({"error": str(e)})

    try:
        pos_override = json.loads(position) if isinstance(position, str) else position
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON in position: {e}"})

    pos_dict = pos_override if pos_override else None
    result = report_tools.clone_visual(config, page_name, visual_id, pos_dict)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="list_tables",
    description=(
        "List all tables in the semantic model with type classification "
        "(fact/dimension/bridge/measure_table/other), column count, "
        "calculated column count, measure count, and partition count."
    ),
)
def tool_list_tables() -> str:
    """List all tables in the semantic model."""
    try:
        config = _get_config()
        result = model_tools.list_tables(config)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="read_table",
    description=(
        "Read a table's full TMDL definition including all columns (with data types, "
        "source expressions), calculated columns, measures, and partitions. "
        "Accepts table name (case-insensitive)."
    ),
)
def tool_read_table(table_name: str) -> str:
    """Read a specific table's full definition.

    Args:
        table_name: The table name (case-insensitive).
    """
    try:
        config = _get_config()
        result = model_tools.read_table(config, table_name)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="list_measures",
    description=(
        "List all DAX measures in the semantic model. Optionally filter by table name. "
        "Returns measure name, table, DAX expression, formatString, and description."
    ),
)
def tool_list_measures(table_name: str = "") -> str:
    """List all measures, optionally filtered by table.

    Args:
        table_name: Optional table name to filter measures. Empty string for all tables.
    """
    try:
        config = _get_config()
        filter_table = table_name if table_name else None
        result = model_tools.list_measures(config, filter_table)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="read_measure",
    description=(
        "Read the full DAX expression and metadata for a specific measure. "
        "Returns expression, formatString, description, lineageTag, and displayFolder. "
        "If the measure name exists in multiple tables, specify table_name to disambiguate."
    ),
)
def tool_read_measure(measure_name: str, table_name: str = "") -> str:
    """Read a specific measure's full definition.

    Args:
        measure_name: The measure name (case-insensitive).
        table_name: Optional table name if the measure name is ambiguous.
    """
    try:
        config = _get_config()
        filter_table = table_name if table_name else None
        result = model_tools.read_measure(config, measure_name, filter_table)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="create_measure",
    description=(
        "Create a new DAX measure in a table's TMDL file. Requires table_name, "
        "measure_name, and expression (DAX). Optional: format_string, description, "
        "display_folder. Creates .bak backup before writing. "
        "Only works when POWERBI_MCP_READ_ONLY=false."
    ),
)
def tool_create_measure(
    table_name: str,
    measure_name: str,
    expression: str,
    format_string: str = "",
    description: str = "",
    display_folder: str = "",
) -> str:
    """Create a new DAX measure.

    Args:
        table_name: The table to add the measure to.
        measure_name: Name for the new measure.
        expression: DAX expression for the measure.
        format_string: Optional DAX format string (e.g. '0.00', '$#,0').
        description: Optional description of the measure.
        display_folder: Optional display folder for organizing measures.
    """
    try:
        config = _get_config()
        result = model_tools.create_measure(
            config,
            table_name=table_name,
            measure_name=measure_name,
            expression=expression,
            format_string=format_string or None,
            description=description or None,
            display_folder=display_folder or None,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="update_measure",
    description=(
        "Update an existing measure's DAX expression or metadata. Only the fields "
        "you provide are changed; others are preserved. Requires measure_name and "
        "table_name. Creates .bak backup before writing. "
        "Only works when POWERBI_MCP_READ_ONLY=false."
    ),
)
def tool_update_measure(
    measure_name: str,
    table_name: str,
    expression: str = "",
    format_string: str = "",
    description: str = "",
    display_folder: str = "",
) -> str:
    """Update an existing measure.

    Args:
        measure_name: The measure to update (case-insensitive).
        table_name: The table containing the measure.
        expression: New DAX expression. Empty string = no change.
        format_string: New format string. Empty string = no change.
        description: New description. Empty string = no change.
        display_folder: New display folder. Empty string = no change.
    """
    try:
        config = _get_config()
        # Convert empty strings to sentinel (no change) or actual value
        result = model_tools.update_measure(
            config,
            measure_name=measure_name,
            table_name=table_name,
            expression=expression or None,
            format_string=format_string if format_string else ...,
            description=description if description else ...,
            display_folder=display_folder if display_folder else ...,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="delete_measure",
    description=(
        "Delete a measure from a table's TMDL file. Creates .bak backup before "
        "writing for safety. Only works when POWERBI_MCP_READ_ONLY=false."
    ),
)
def tool_delete_measure(measure_name: str, table_name: str) -> str:
    """Delete a measure from a table.

    Args:
        measure_name: The measure to delete (case-insensitive).
        table_name: The table containing the measure.
    """
    try:
        config = _get_config()
        result = model_tools.delete_measure(config, measure_name, table_name)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="list_relationships",
    description=(
        "List all relationships in the semantic model. Returns relationship name, "
        "fromTable, fromColumn, toTable, toColumn, isActive, and crossFilteringBehavior."
    ),
)
def tool_list_relationships() -> str:
    """List all model relationships."""
    try:
        config = _get_config()
        result = model_tools.list_relationships(config)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="create_relationship",
    description=(
        "Create a new relationship between two tables in relationships.tmdl. "
        "Validates both tables and columns exist. Optional: is_active (default true), "
        "cross_filtering ('oneDirection', 'bothDirections', 'automatic'). "
        "Creates .bak backup before writing. Only works when POWERBI_MCP_READ_ONLY=false."
    ),
)
def tool_create_relationship(
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    is_active: bool = True,
    cross_filtering: str = "",
) -> str:
    """Create a new model relationship.

    Args:
        from_table: The many-side (fact) table name.
        from_column: The foreign key column in from_table.
        to_table: The one-side (dimension) table name.
        to_column: The primary key column in to_table.
        is_active: Whether the relationship is active (default true).
        cross_filtering: Cross-filtering behavior: oneDirection, bothDirections, or automatic.
    """
    try:
        config = _get_config()
        result = model_tools.create_relationship(
            config,
            from_table=from_table,
            from_column=from_column,
            to_table=to_table,
            to_column=to_column,
            is_active=is_active,
            cross_filtering=cross_filtering or None,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="read_data_sources",
    description=(
        "List all data sources in the semantic model. Returns shared expressions "
        "(M/Power Query functions) from expressions.tmdl and partition source "
        "summaries from each table. Credentials are automatically redacted."
    ),
)
def tool_read_data_sources() -> str:
    """Read data source configuration from the semantic model."""
    try:
        config = _get_config()
        result = model_tools.read_data_sources(config)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def main():
    logger.info("Starting Power BI MCP Server (stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
