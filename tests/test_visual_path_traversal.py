"""B42: read_visual and clone_visual must not escape the .pbip project.

find_visual() resolves visual_id directly into a filesystem path
(visuals_dir / visual_id). Without a path-confinement check, a traversal
string like "..\\..\\..\\external_dir" resolves outside the .pbip project,
letting read_visual exfiltrate an arbitrary file's contents and letting
clone_visual copy an arbitrary external directory's contents into the
project. The fix enforces config.is_within_project(...) inside
find_visual() itself, so every caller (read, write, clone, delete)
inherits the guard.
"""

import json
import os

from powerbi_mcp import report_tools
from powerbi_mcp.config import Config

SECRET_MARKER = "TOP_SECRET_DATA_SHOULD_NEVER_LEAVE_HERE"


def _make_project(tmp_path):
    (tmp_path / "Demo.pbip").write_text(
        '{"artifacts": [{"report": {"path": "Demo.Report"}}]}', encoding="utf-8"
    )

    pages_dir = tmp_path / "Demo.Report" / "definition" / "pages"
    page_dir = pages_dir / "page1hash"
    visuals_dir = page_dir / "visuals"
    visuals_dir.mkdir(parents=True)

    (page_dir / "page.json").write_text(
        json.dumps({"displayName": "Page1"}), encoding="utf-8"
    )

    legit_visual_dir = visuals_dir / "legit0000000000hash"
    legit_visual_dir.mkdir()
    (legit_visual_dir / "visual.json").write_text(
        json.dumps(
            {
                "name": "legit0000000000hash",
                "position": {"x": 0, "y": 0, "width": 100, "height": 50, "z": 0, "tabOrder": 0},
                "visual": {"visualType": "card", "query": {"queryState": {}}},
            }
        ),
        encoding="utf-8",
    )

    (tmp_path / "Demo.SemanticModel" / "definition" / "tables").mkdir(parents=True)

    # A directory OUTSIDE the .pbip project (sibling of Demo.Report) that a
    # traversal visual_id will attempt to reach.
    external_dir = tmp_path / "external_secret_dir"
    external_dir.mkdir()
    (external_dir / "visual.json").write_text(
        json.dumps({"secret": SECRET_MARKER}), encoding="utf-8"
    )

    config = Config(pbip_path=str(tmp_path / "Demo.pbip"))
    traversal_id = os.path.relpath(external_dir, visuals_dir).replace(os.sep, "/")
    return config, traversal_id, "legit0000000000hash"


def test_read_visual_rejects_traversal_id(tmp_path):
    config, traversal_id, _legit_id = _make_project(tmp_path)

    result = report_tools.read_visual(config, "Page1", traversal_id)

    assert "error" in result
    assert SECRET_MARKER not in json.dumps(result)


def test_read_visual_succeeds_for_legit_id(tmp_path):
    config, _traversal_id, legit_id = _make_project(tmp_path)

    result = report_tools.read_visual(config, "Page1", legit_id)

    assert result["name"] == legit_id
    assert result["visual"]["visualType"] == "card"


def test_clone_visual_rejects_traversal_id(tmp_path, monkeypatch):
    monkeypatch.setenv("POWERBI_MCP_READ_ONLY", "false")
    config, traversal_id, _legit_id = _make_project(tmp_path)

    result = report_tools.clone_visual(config, "Page1", traversal_id)

    assert "error" in result
    assert "success" not in result

    # No file anywhere under the project tree may contain the external secret.
    for path in (tmp_path / "Demo.Report").rglob("*.json"):
        assert SECRET_MARKER not in path.read_text(encoding="utf-8")


def test_clone_visual_succeeds_for_legit_id(tmp_path, monkeypatch):
    monkeypatch.setenv("POWERBI_MCP_READ_ONLY", "false")
    config, _traversal_id, legit_id = _make_project(tmp_path)

    result = report_tools.clone_visual(config, "Page1", legit_id)

    assert result["success"] is True
    cloned_dir = config.pages_dir / "page1hash" / "visuals" / result["visual_id"]
    assert result["visual_id"] != legit_id
    cloned_data = json.loads((cloned_dir / "visual.json").read_text(encoding="utf-8"))
    assert cloned_data["visual"]["visualType"] == "card"
