"""亿兰科单份（纯 DIP）BOM 导入。"""
from bom_excel import ParsedBom, ParsedBomLine
from yilanke_bom import finalize_yilanke_single


def _line(code: str, name: str = "插件料", process: str = "DIP") -> ParsedBomLine:
    return ParsedBomLine(
        seq="1",
        material_code=code,
        material_name=name,
        spec=None,
        unit="PCS",
        qty_per=1.0,
        position=None,
        process=process,
        remark=None,
        sort_order=1,
    )


def test_finalize_pure_dip_keeps_plugin_lines():
    parsed = ParsedBom(
        model_code="3001-0147A",
        model_name="整机 3001-0147A",
        model_spec="",
        lines=[
            _line("3003-9999", "SMT半成品"),  # 应剔除
            _line("R1001", "电阻"),
            _line("CN1", "接插件"),
        ],
        folder_name="",
        source_file="3001-0147A.xlsx",
        source_mtime=1.0,
    )
    out = finalize_yilanke_single(parsed)
    assert out.model_code == "3001-0147A"
    assert "纯 DIP" in (out.model_spec or "")
    codes = [ln.material_code for ln in out.lines]
    assert codes == ["R1001", "CN1"]
    assert all((ln.process or "").upper() == "DIP" for ln in out.lines)


if __name__ == "__main__":
    test_finalize_pure_dip_keeps_plugin_lines()
    print("OK")
