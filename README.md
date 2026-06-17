# Power BI MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that gives AI assistants like Claude direct read and write access to Power BI `.pbip` project files. Edit visuals, inspect measures, and manage report layouts, all through natural language.

## What it does

Power BI Desktop now supports the `.pbip` format: a folder of JSON and TMDL text files instead of a single binary `.pbix`. This server exposes that folder structure through 7 MCP tools, allowing any MCP-compatible client to:

- **List pages** in a report with dimensions, visibility, and visual counts
- **List visuals** on any page with type, position, and bound measures/columns
- **Read a visual's** full configuration (query bindings, formatting, filters)
- **Update a visual** via deep-merge: change position, rebind measures, update titles, all with partial JSON
- **List all DAX measures** with expressions, format strings, and table membership
- **Read a specific measure's** full DAX expression and metadata
- **List all relationships** in the semantic model with cardinality and cross-filter direction

## Architecture

```
┌─────────────────────────────┐
│  Claude Code / MCP Client   │
│  (natural language)         │
└──────────┬──────────────────┘
           │ stdio (JSON-RPC)
┌──────────▼──────────────────┐
│  powerbi-mcp-server         │
│  ┌───────────────────────┐  │
│  │ server.py (FastMCP)   │  │
│  │  7 registered tools   │  │
│  ├───────────────────────┤  │
│  │ report_tools.py       │  │  ← pages, visuals, read/write
│  │ pbip_reader.py        │  │  ← filesystem ops, deep merge
│  │ model_tools.py        │  │  ← measures, relationships
│  │ tmdl_parser.py        │  │  ← TMDL state machine parser
│  │ config.py             │  │  ← path resolution, safety
│  └───────────────────────┘  │
└──────────┬──────────────────┘
           │ filesystem
┌──────────▼──────────────────┐
│  .pbip Project              │
│  ├── Project.Report/        │  ← pages & visuals (JSON)
│  └── Project.SemanticModel/ │  ← measures & relationships (TMDL)
└─────────────────────────────┘
```

## Quick start

### Prerequisites

- Python 3.12+
- A Power BI `.pbip` project file (or use the included sample)
- An MCP client ([Claude Code](https://claude.ai/claude-code), [Claude Desktop](https://claude.ai/download), etc.)

### Install

```bash
git clone https://github.com/HenryLabsConsulting/powerbi-mcp-server.git
cd powerbi-mcp-server
pip install -e .
```

### Configure your MCP client

Add to your `.mcp.json` (Claude Code) or `claude_desktop_config.json` (Claude Desktop):

```json
{
  "mcpServers": {
    "powerbi": {
      "command": "python",
      "args": ["-m", "powerbi_mcp"],
      "env": {
        "POWERBI_MCP_PBIP_PATH": "C:\\path\\to\\your\\project.pbip",
        "POWERBI_MCP_READ_ONLY": "false"
      }
    }
  }
}
```

To use the included sample project:

```json
{
  "mcpServers": {
    "powerbi": {
      "command": "python",
      "args": ["-m", "powerbi_mcp"],
      "env": {
        "POWERBI_MCP_PBIP_PATH": "C:\\path\\to\\powerbi-mcp-server\\sample\\Contoso Coffee Shop.pbip",
        "POWERBI_MCP_READ_ONLY": "false"
      }
    }
  }
}
```

### Try it

Once configured, restart your MCP client and ask:

> "List all pages in my Power BI report"

> "Show me the visuals on the Overview page"

> "Change the combo chart title to 'Monthly Revenue Trend'"

> "Move the Total Revenue card to position y=100"

> "What DAX measures are in the model?"

## Tools reference

| Tool | Description | Write? |
|------|------------|--------|
| `list_pages` | All pages with dimensions, visibility, visual count | No |
| `list_visuals` | All visuals on a page with type, position, bindings | No |
| `read_visual` | Full visual.json for a specific visual | No |
| `update_visual` | Deep-merge partial JSON into a visual | Yes |
| `list_measures` | All DAX measures, optionally filtered by table | No |
| `read_measure` | Full DAX expression and metadata for one measure | No |
| `list_relationships` | All model relationships with cardinality | No |

### Write mode

By default, the server starts in **read-only mode**. Set `POWERBI_MCP_READ_ONLY=false` to enable `update_visual`.

When writing, the server:
1. Creates a `.bak` backup of the visual before any change
2. Deep-merges your partial JSON into the existing visual (unchanged properties are preserved)
3. Validates the merged JSON before writing
4. Enforces path confinement: writes are restricted to the `.pbip` project directory

### Visual addressing

Visuals can be referenced by:
- **Hash ID**: `6a14287f85e76c72e612` (the folder name)
- **Label**: `card:Total Revenue` (type + primary bound field)

Pages can be referenced by:
- **Display name**: `Overview` (case-insensitive)
- **Hash ID**: `81c196a5709f266255cc`

## Sample project

The `sample/` directory contains a complete "Contoso Coffee Shop" `.pbip` project with:
- 2 pages (Overview, Products)
- 6 visuals (cards, combo chart, bar chart, table)
- 3 DAX measures (Total Revenue, Total Orders, Avg Order Value)
- 4 tables (DimDate, DimStore, DimProduct, FactSales) with a star schema
- 3 relationships

This is a structural sample. It contains report definitions and measure formulas, not row-level data. You can use it to test every tool without connecting to a data source.

## How .pbip works

The `.pbip` format (introduced in Power BI Desktop) saves reports as a folder of text files instead of a binary `.pbix`:

```
Project.pbip                    ← entry point (JSON, points to .Report)
Project.Report/
  definition/
    pages/
      pages.json                ← page order
      {page-hash}/
        page.json               ← page metadata (name, size)
        visuals/
          {visual-hash}/
            visual.json         ← visual config (type, position, query, formatting)
Project.SemanticModel/
  definition/
    tables/
      TableName.tmdl            ← columns, measures, partitions (TMDL format)
    relationships.tmdl           ← foreign keys between tables
```

Because everything is text, it's version-controllable and programmatically editable, which is exactly what this server enables.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `POWERBI_MCP_PBIP_PATH` | *(required)* | Absolute path to your `.pbip` file |
| `POWERBI_MCP_READ_ONLY` | `true` | Set to `false` to enable write operations |

You can also pass `--pbip-path` as a CLI argument (takes precedence over the env var).

## Requirements

- Python 3.12+
- [`mcp`](https://pypi.org/project/mcp/) >= 1.0.0 (the only dependency)

## License

MIT
