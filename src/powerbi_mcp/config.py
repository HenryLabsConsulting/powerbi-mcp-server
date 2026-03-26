"""Configuration management for the Power BI MCP Server.

Reads POWERBI_MCP_PBIP_PATH and POWERBI_MCP_READ_ONLY from environment.
Parses the .pbip JSON to resolve .Report and .SemanticModel folder paths.
"""

import argparse
import json
import os
from pathlib import Path


class Config:
    """Resolved configuration for a single .pbip project."""

    def __init__(self, pbip_path: str | None = None):
        resolved_path = self._resolve_pbip_path(pbip_path)
        self.pbip_path = Path(resolved_path).resolve()
        self.read_only = os.environ.get("POWERBI_MCP_READ_ONLY", "true").lower() != "false"

        if not self.pbip_path.exists():
            raise FileNotFoundError(
                f"PBIP file not found at {self.pbip_path}. "
                "Check POWERBI_MCP_PBIP_PATH or --pbip-path."
            )

        pbip_data = self._parse_pbip_file()
        self.pbip_dir = self.pbip_path.parent

        # Resolve .Report folder from artifacts array
        report_rel = None
        for artifact in pbip_data.get("artifacts", []):
            if "report" in artifact:
                report_rel = artifact["report"].get("path")
                break

        if not report_rel:
            raise ValueError("No report artifact found in .pbip file.")

        self.report_dir = (self.pbip_dir / report_rel).resolve()
        if not self.report_dir.exists():
            raise FileNotFoundError(f"Report folder not found at {self.report_dir}")

        self.definition_dir = self.report_dir / "definition"
        self.pages_dir = self.definition_dir / "pages"

        # SemanticModel folder: same stem as .Report but with .SemanticModel suffix
        sm_name = report_rel.replace(".Report", ".SemanticModel")
        self.semantic_model_dir = (self.pbip_dir / sm_name).resolve()
        self.tables_dir = self.semantic_model_dir / "definition" / "tables"
        self.relationships_path = self.semantic_model_dir / "definition" / "relationships.tmdl"

    def _resolve_pbip_path(self, cli_path: str | None) -> str:
        """CLI arg takes precedence over env var."""
        if cli_path:
            return cli_path
        env_path = os.environ.get("POWERBI_MCP_PBIP_PATH")
        if env_path:
            return env_path
        raise ValueError(
            "No .pbip path configured. Set POWERBI_MCP_PBIP_PATH environment variable "
            "or pass --pbip-path argument."
        )

    def _parse_pbip_file(self) -> dict:
        try:
            return json.loads(self.pbip_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse .pbip file: {e}") from e

    def is_within_project(self, path: Path) -> bool:
        """Verify a path is within the .pbip project directory (path confinement)."""
        try:
            resolved = path.resolve()
            return (
                str(resolved).startswith(str(self.report_dir))
                or str(resolved).startswith(str(self.semantic_model_dir))
            )
        except (OSError, ValueError):
            return False


def parse_cli_args() -> str | None:
    """Parse --pbip-path from command line, if provided."""
    parser = argparse.ArgumentParser(description="Power BI MCP Server")
    parser.add_argument("--pbip-path", type=str, default=None, help="Path to .pbip file")
    args, _ = parser.parse_known_args()
    return args.pbip_path
