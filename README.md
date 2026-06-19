# Power BI MCP Server

An MCP server that gives an AI assistant like Claude direct read and write access to a Power BI project on disk (a `.pbip` project with its TMDL model). Ask in plain language to inspect the model, read a DAX measure, or edit a visual, and the change lands in the project files, reviewable in source control like any other code.

It is read-only by default, and every write makes a backup first.

## Why

Power BI work usually happens by clicking through Desktop. This server puts the report and the semantic model behind a small set of typed tools, so an assistant can answer "what measures feed this card" or "move this visual and change its title" by reading and editing the underlying files directly. The model becomes something you can review, diff, and edit as text.

## Tools

**Report (pages and visuals)**

| Tool | Purpose |
|---|---|
| `list_pages` | List report pages with dimensions and visual counts |
| `list_visuals` | List visuals on a page with type, position, and bindings |
| `read_visual` | Read a visual's full definition |
| `update_visual` | Deep-merge changes into a visual |
| `create_visual` | Add a new visual to a page |
| `delete_visual` | Remove a visual (kept in a `.deleted` backup) |
| `clone_visual` | Copy a visual, with optional position override |

**Semantic model (tables, measures, relationships, sources)**

| Tool | Purpose |
|---|---|
| `list_tables` | List tables with type classification and counts |
| `read_table` | Read a table's full TMDL (columns, measures, partitions) |
| `list_measures` | List DAX measures, optionally filtered by table |
| `read_measure` | Read a measure's DAX and metadata |
| `create_measure` | Add a new DAX measure |
| `update_measure` | Update a measure's expression or metadata |
| `delete_measure` | Remove a measure |
| `list_relationships` | List model relationships |
| `create_relationship` | Add a relationship between two tables |
| `read_data_sources` | List M expressions and partition sources (credentials redacted) |

## Install

```bash
pip install -e .
```

## Configure your MCP client

Point the server at a `.pbip` file. Example for a Claude client:

```json
{
  "mcpServers": {
    "powerbi": {
      "command": "powerbi-mcp-server",
      "args": ["--pbip-path", "C:/path/to/Project.pbip"],
      "env": { "POWERBI_MCP_READ_ONLY": "false" }
    }
  }
}
```

Configuration comes from the CLI argument or environment:

- `POWERBI_MCP_PBIP_PATH`: path to the `.pbip` file (alternative to `--pbip-path`).
- `POWERBI_MCP_READ_ONLY`: defaults to `true`. Set to `false` to allow writes.

## Safety model

- **Read-only by default.** Write tools do nothing until you set `POWERBI_MCP_READ_ONLY=false`.
- **Backups on every write.** File edits leave a `.bak`; deleted visuals move to a `.deleted` directory rather than being removed.
- **Confined writes.** Edits are restricted to the project's `.Report` and `.SemanticModel` directories.

## Example

Ask the assistant: "Change the Total Revenue measure to round to whole dollars and add a description." Behind the scenes it calls `update_measure`, backs up the table file, rewrites just that measure, and preserves the measure's other content (annotations, formatting) untouched.

## Develop

```bash
pip install -e . ruff pytest
ruff check src tests
pytest
```

---

*Part of [HenryLabs Consulting](https://github.com/HenryLabsConsulting)'s public work. MIT licensed.*
