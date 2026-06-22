"""Round-trip tests for the TMDL measure writer.

Guards the data-loss class of bug where updating a measure dropped child content
the writer does not regenerate (annotations, formatStringDefinition).
"""

from pathlib import Path

from powerbi_mcp import tmdl_parser
from powerbi_mcp.config import Config

T = "\t"

TABLE = (
    "table MyTable\n"
    f"{T}lineageTag: 11111111-1111-1111-1111-111111111111\n"
    "\n"
    f"{T}measure 'Total Revenue' = SUM(fact[revenue])\n"
    f"{T}{T}formatString: \\$#,0\n"
    f"{T}{T}lineageTag: 22222222-2222-2222-2222-222222222222\n"
    f'{T}{T}annotation PBI_FormatHint = {{"isDecimal":true}}\n'
    "\n"
    f"{T}column revenue\n"
    f"{T}{T}dataType: double\n"
    f"{T}{T}lineageTag: 33333333-3333-3333-3333-333333333333\n"
)


def _make_project(tmp_path: Path) -> Config:
    (tmp_path / "Demo.pbip").write_text(
        '{"artifacts": [{"report": {"path": "Demo.Report"}}]}', encoding="utf-8"
    )
    (tmp_path / "Demo.Report" / "definition" / "pages").mkdir(parents=True)
    tables = tmp_path / "Demo.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "MyTable.tmdl").write_text(TABLE, encoding="utf-8")
    return Config(pbip_path=str(tmp_path / "Demo.pbip"))


def _table_text(tmp_path: Path) -> str:
    path = tmp_path / "Demo.SemanticModel" / "definition" / "tables" / "MyTable.tmdl"
    return path.read_text(encoding="utf-8")


def test_update_measure_preserves_annotation(tmp_path):
    config = _make_project(tmp_path)
    tmdl_parser.update_measure_in_table(
        config, "MyTable", "Total Revenue",
        expression="SUM(fact[revenue]) * 1.0",
    )
    text = _table_text(tmp_path)
    assert "SUM(fact[revenue]) * 1.0" in text       # new expression written
    assert "annotation PBI_FormatHint" in text       # the bug: annotation must survive
    assert "column revenue" in text                  # sibling column untouched


def test_update_measure_keeps_unchanged_format(tmp_path):
    config = _make_project(tmp_path)
    tmdl_parser.update_measure_in_table(
        config, "MyTable", "Total Revenue", description="Top line.",
    )
    text = _table_text(tmp_path)
    assert "formatString: \\$#,0" in text             # unchanged property kept
    assert "description: Top line." in text           # new property added
    assert "annotation PBI_FormatHint" in text        # annotation still preserved


def test_format_measure_emits_extra_lines():
    block = tmdl_parser._format_measure_tmdl(
        name="M", expression="1", lineage_tag="t",
        extra_lines=["\t\tannotation Foo = bar"],
    )
    assert "annotation Foo = bar" in block


# B13 — a no-backtick measure whose continuation line sits at indent 2 must keep
# its full expression on parse (previously the indent-2 line was dropped, leaving
# only the first line, and a write-back then lost the rest of the DAX).
NO_BACKTICK_TABLE = (
    "table CalcTable\n"
    f"{T}lineageTag: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\n"
    "\n"
    f"{T}measure Spread =\n"
    f"{T}{T}CALCULATE(\n"
    f"{T}{T}SUM(fact[high]) - SUM(fact[low])\n"
    f"{T}{T})\n"
    f"{T}{T}formatString: 0.00\n"
    f"{T}{T}lineageTag: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\n"
)


def _calc_project(tmp_path: Path) -> Config:
    (tmp_path / "Demo.pbip").write_text(
        '{"artifacts": [{"report": {"path": "Demo.Report"}}]}', encoding="utf-8"
    )
    (tmp_path / "Demo.Report" / "definition" / "pages").mkdir(parents=True)
    tables = tmp_path / "Demo.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "CalcTable.tmdl").write_text(NO_BACKTICK_TABLE, encoding="utf-8")
    return Config(pbip_path=str(tmp_path / "Demo.pbip"))


def test_indent2_continuation_preserved_on_parse(tmp_path):
    config = _calc_project(tmp_path)
    measures = tmdl_parser.get_all_measures(config, "CalcTable")
    assert len(measures) == 1
    expr = measures[0]["expression"]
    # Every continuation line of the DAX body survives.
    assert "CALCULATE(" in expr
    assert "SUM(fact[high]) - SUM(fact[low])" in expr
    assert expr.rstrip().endswith(")")
    # The property line must NOT be swallowed into the expression body.
    assert "formatString" not in expr
    assert measures[0]["formatString"] == "0.00"


def test_indent2_continuation_survives_write_back(tmp_path):
    config = _calc_project(tmp_path)
    # An unrelated update (description only) must not drop the expression body.
    tmdl_parser.update_measure_in_table(
        config, "CalcTable", "Spread", description="High minus low.",
    )
    measures = tmdl_parser.get_all_measures(config, "CalcTable")
    expr = measures[0]["expression"]
    assert "CALCULATE(" in expr
    assert "SUM(fact[high]) - SUM(fact[low])" in expr
    assert measures[0]["description"] == "High minus low."
