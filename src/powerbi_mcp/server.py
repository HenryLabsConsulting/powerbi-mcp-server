"""MCP server entry point for Power BI .pbip file access.

Registers all 7 tools via FastMCP and runs on stdio transport.
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


def main():
    logger.info("Starting Power BI MCP Server (stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
