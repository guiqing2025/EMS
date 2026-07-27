"""AIS 坐标解析与完备性相关回归。"""
from pathlib import Path

from placement_audit import audit_parsed_placement
from placement_parser import parse_ais_txt


def test_ais_mirror_yes_not_skipped(tmp_path: Path):
    content = """$HEADER$
BOARD_TYPE PCB_DESIGN
UNITS MM
$END HEADER$

$PART_SECTION_BEGIN$
J1                               14109020                         90.00      163.40     75.00      TOP        NO
D1                               15010347                         270.00     155.70     89.50      BOTTOM     YES
R1                               07090061                         0.00       137.70     134.20     BOTTOM     YES
$PART_SECTION_END$
"""
    path = tmp_path / "sample_坐标文件.txt"
    path.write_text(content, encoding="utf-8")
    parsed = parse_ais_txt(path)
    assert len(parsed.lines) == 3
    assert all(not ln.skip for ln in parsed.lines)
    by_ref = {ln.refdes: ln for ln in parsed.lines}
    assert by_ref["J1"].layer == "T"
    assert by_ref["D1"].layer == "B"
    assert by_ref["R1"].layer == "B"
    audit = audit_parsed_placement(parsed)
    assert audit.status == "passed"
    assert audit.refdes_count == 3
    assert audit.layer_count == 2
