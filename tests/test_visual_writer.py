"""Tests for the .pbip visual-writer guards.

Covers:
- B15: create_visual_dir must not mutate the caller's dict.
- B16: create_visual_dir must reject a definition missing required keys
  (position / visual.visualType) rather than writing a .pbip that Power BI
  cannot open.
"""

import copy

import pytest

from powerbi_mcp import pbip_reader


def _valid_visual() -> dict:
    return {
        "position": {"x": 0, "y": 0, "width": 200, "height": 100, "z": 0, "tabOrder": 0},
        "visual": {"visualType": "card", "query": {}},
    }


def test_create_visual_does_not_mutate_caller_dict(tmp_path):
    page_dir = tmp_path / "page"
    page_dir.mkdir()

    definition = _valid_visual()
    before = copy.deepcopy(definition)

    result = pbip_reader.create_visual_dir(page_dir, definition)

    # The write succeeded with a generated id...
    assert result["visual_id"]
    # ...but the caller's dict is byte-for-byte unchanged (no injected name/$schema).
    assert definition == before
    assert "name" not in definition
    assert "$schema" not in definition


def test_create_visual_rejects_missing_position(tmp_path):
    page_dir = tmp_path / "page"
    page_dir.mkdir()

    definition = {"visual": {"visualType": "card"}}
    with pytest.raises(ValueError) as exc:
        pbip_reader.create_visual_dir(page_dir, definition)
    assert "position" in str(exc.value)


def test_create_visual_rejects_missing_visual_type(tmp_path):
    page_dir = tmp_path / "page"
    page_dir.mkdir()

    definition = {"position": {"x": 0, "y": 0}, "visual": {"query": {}}}
    with pytest.raises(ValueError) as exc:
        pbip_reader.create_visual_dir(page_dir, definition)
    assert "visualType" in str(exc.value)


def test_create_visual_rejects_lists_all_missing_keys(tmp_path):
    page_dir = tmp_path / "page"
    page_dir.mkdir()

    with pytest.raises(ValueError) as exc:
        pbip_reader.create_visual_dir(page_dir, {})
    msg = str(exc.value)
    assert "position" in msg
    assert "visualType" in msg


def test_create_visual_writes_when_valid(tmp_path):
    page_dir = tmp_path / "page"
    page_dir.mkdir()

    result = pbip_reader.create_visual_dir(page_dir, _valid_visual())
    written = pbip_reader.read_visual_json(page_dir / "visuals" / result["visual_id"])
    assert written is not None
    assert written["name"] == result["visual_id"]
    assert written["visual"]["visualType"] == "card"
