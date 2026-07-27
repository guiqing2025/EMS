"""亿兰科 PADS 风格坐标表：RefDes / Orient. / Layer / PartDecal。"""
from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Optional

from openpyxl import Workbook

from placement_parser import parse_placement_file


def test_yilanke_pads_refdes_xlsx(tmp_path: Optional[Path] = None):
    root = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp())
    path = root / "6801-0075A-坐标.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["PartType", "RefDes", "PartDecal", "Pins", "Layer", "Orient.", "X", "Y", "SMD", "Glued"])
    ws.append(["102K/0603", "C1", "C0603", 2, "Top", 270, 266.4, 12.4, "Yes", "No"])
    ws.append(["102K/0603", "C5", "C0603", 2, "Bottom", 90, 277.3, 12.4, "Yes", "No"])
    wb.save(path)

    parsed = parse_placement_file(path)
    assert len(parsed.lines) == 2
    c1 = parsed.lines[0]
    assert c1.refdes == "C1"
    assert c1.layer == "T"
    assert c1.rotation == 270
    assert c1.mid_x == 266.4
    assert c1.mid_y == 12.4
    assert c1.footprint == "C0603"
    assert c1.comment == "102K/0603"
    c5 = parsed.lines[1]
    assert c5.refdes == "C5"
    assert c5.layer == "B"
    assert c5.rotation == 90


if __name__ == "__main__":
    test_yilanke_pads_refdes_xlsx()
    print("OK")
