"""批量来料 Excel 解析与模板。"""
from __future__ import annotations

import io
from typing import Any, Optional

from openpyxl import Workbook, load_workbook

CODE_HEADERS = ("物料编码", "物料编号", "料号", "material_code", "Material Code")
QTY_HEADERS = ("数量", "来料数", "来料数量", "入库数量", "qty", "Qty")
REMARK_HEADERS = ("备注", "remark", "Remark")
NAME_HEADERS = ("物料名称", "品名", "material_name", "Material Name")
SPEC_HEADERS = ("规格", "规格型号", "spec", "Spec")

INBOUND_TEMPLATE_HEADERS = ["物料编码", "数量", "品名", "规格", "备注"]


def build_inbound_template_workbook() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "来料导入"
    ws.append(INBOUND_TEMPLATE_HEADERS)
    ws.append(["示例料号A", 100, "示例品名", "0402", "可选"])
    ws.append(["示例料号B", 50, "", "", ""])
    return wb


def _norm_header(value: Any) -> str:
    return str(value or "").strip()


def _find_col(headers: list[str], aliases: tuple[str, ...]) -> Optional[int]:
    """按别名找列。空表头不参与匹配（避免 '' in '料号' 误命中）。"""
    cleaned = [(i, (h or "").strip()) for i, h in enumerate(headers)]
    lower_map = {h.lower(): i for i, h in cleaned if h}
    for alias in aliases:
        if alias in headers:
            return headers.index(alias)
        key = alias.lower()
        if key in lower_map:
            return lower_map[key]
    # 仅允许「别名是表头子串」：如 料号 ⊂ 物料编码；禁止反过来（短串/空串误伤）
    for i, h in cleaned:
        if not h:
            continue
        hl = h.lower()
        for alias in aliases:
            al = alias.lower()
            if al and al in hl:
                return i
    return None


def _float_val(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        n = float(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def parse_inbound_excel(content: bytes) -> dict:
    """解析来料 Excel，返回 items 与解析提示。"""
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"无法读取 Excel 文件：{exc}") from exc

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel 为空")

    header_idx = 0
    headers: list[str] = []
    code_col = qty_col = remark_col = name_col = spec_col = None

    for idx, row in enumerate(rows[:15]):
        cells = [_norm_header(c) for c in row]
        if not any(cells):
            continue
        cc = _find_col(cells, CODE_HEADERS)
        qc = _find_col(cells, QTY_HEADERS)
        if cc is not None and qc is not None:
            header_idx = idx
            headers = cells
            code_col = cc
            qty_col = qc
            remark_col = _find_col(cells, REMARK_HEADERS)
            name_col = _find_col(cells, NAME_HEADERS)
            spec_col = _find_col(cells, SPEC_HEADERS)
            break

    if code_col is None or qty_col is None:
        # 无表头：按第一列料号、第二列数量
        code_col, qty_col = 0, 1
        remark_col = 2 if len(rows[0]) > 2 else None
        name_col = spec_col = None
        header_idx = -1

    items = []
    errors = []
    for row_no, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        if not row:
            continue
        cells = list(row)
        if code_col >= len(cells):
            continue
        code = _norm_header(cells[code_col])
        if not code or code in CODE_HEADERS:
            continue
        qty = _float_val(cells[qty_col] if qty_col < len(cells) else None)
        if qty is None:
            if code:
                errors.append({"row": row_no, "material_code": code, "error": "数量无效或为空"})
            continue
        remark = ""
        if remark_col is not None and remark_col < len(cells):
            remark = _norm_header(cells[remark_col])
        material_name = ""
        if name_col is not None and name_col < len(cells):
            material_name = _norm_header(cells[name_col])
        spec = ""
        if spec_col is not None and spec_col < len(cells):
            spec = _norm_header(cells[spec_col])
        items.append(
            {
                "material_code": code,
                "qty": qty,
                "remark": remark,
                "material_name": material_name,
                "spec": spec,
            }
        )

    if not items:
        raise ValueError("未解析到有效来料行，请确认表头含「物料编码」「数量」或前两列为料号、数量")

    return {
        "items": items,
        "errors": errors,
        "parsed_count": len(items),
        "header_row": header_idx + 1 if header_idx >= 0 else None,
    }
