"""替代料人工导入：标准 XLSX / 旧客户A表 / 图片 OCR。"""
from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from models import SubstitutionRule
from substitution_service import normalize_code, reload_substitution_cache_from_db

logger = logging.getLogger(__name__)

TEMPLATE_HEADERS = [
    "元件品号",
    "元件品名",
    "元件规格",
    "单位",
    "主件品号",
    "主件品名",
    "关系类型",
    "替代料号",
    "替代品名",
    "替代规格",
    "顺序",
    "生效日期",
    "失效日期",
    "数量",
    "备注",
]

# 客户C委外替代料表（子项=BOM 原料，投产=实际发料/替代）
YONGLIAN_TEMPLATE_HEADERS = [
    "序号",
    "子项物料编码",
    "投产物料编码",
    "物料名称",
    "规格型号",
    "单位",
    "D1",
    "U1",
    "U2",
    "U3",
    "结构",
    "M1",
    "合并需求",
]

_PO_RE = re.compile(
    r"(?:委外订单号|订单号|采购订单|PO)[：:\s]*([0-9A-Za-z\-]+)",
    re.I,
)

# 常见料号形态（客户A / 客户B / 客户C / 客户D）——避免过宽通配产生误识别
_CODE_PATTERNS = [
    re.compile(r"\b\d{3}-\d{5,7}-\d{2}[A-Za-z]?\b"),  # 120-200235-09
    re.compile(r"\b\d{2}\.\d{2,4}\.\d{4,}\b"),  # 91.0302.100238 / 03.03.001100
    re.compile(r"\b0\d{7,8}\b"),  # 03029384
    re.compile(r"\b99\d{6,8}\b"),
    re.compile(r"\b3001-\d+[A-Za-z]?\b"),
]


def _cell_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    text = str(value).strip()
    return text or None


def _cell_code(value: Any) -> str:
    text = _cell_str(value)
    return normalize_code(text) if text else ""


def _cell_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_row(item: dict) -> Optional[dict]:
    comp = normalize_code(item.get("comp_code"))
    sub = normalize_code(item.get("sub_code"))
    if not comp or not sub or comp == sub:
        return None
    parent = normalize_code(item.get("parent_code")) or ""
    relation = (item.get("relation_type") or "替代料件").strip() or "替代料件"
    return {
        "comp_code": comp,
        "comp_name": _cell_str(item.get("comp_name")),
        "comp_spec": _cell_str(item.get("comp_spec")),
        "comp_unit": _cell_str(item.get("comp_unit")),
        "comp_unit_small": _cell_str(item.get("comp_unit_small")),
        "comp_attr": _cell_str(item.get("comp_attr")),
        "parent_code": parent,
        "parent_name": _cell_str(item.get("parent_name")),
        "parent_spec": _cell_str(item.get("parent_spec")),
        "parent_unit": _cell_str(item.get("parent_unit")),
        "parent_unit_small": _cell_str(item.get("parent_unit_small")),
        "parent_attr": _cell_str(item.get("parent_attr")),
        "relation_type": relation,
        "sub_code": sub,
        "sub_name": _cell_str(item.get("sub_name")),
        "sub_spec": _cell_str(item.get("sub_spec")),
        "sub_unit": _cell_str(item.get("sub_unit")),
        "sub_unit_small": _cell_str(item.get("sub_unit_small")),
        "sub_attr": _cell_str(item.get("sub_attr")),
        "sub_order": _cell_str(item.get("sub_order")),
        "effective_date": _cell_str(item.get("effective_date")),
        "expiry_date": _cell_str(item.get("expiry_date")),
        "qty": _cell_float(item.get("qty")),
        "remark": _cell_str(item.get("remark")),
    }


def build_template_xlsx(*, profile: str = "standard") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "替代料"
    if (profile or "").strip().lower() in ("yonglian", "yl", "a067"):
        ws.insert_rows(1)
        ws["A1"] = "委外订单号：01-202607-CG-0320       加工厂：景立创           委外型号/数量：UXR100060CZ（ D1  U1 M1 U2 U3）板 20套"
        for col, h in enumerate(YONGLIAN_TEMPLATE_HEADERS, 1):
            ws.cell(row=2, column=col, value=h)
        sample = [
            44,
            "90.0709.003300",
            "90.0709.003303",
            "片状电阻器",
            "RR1206 2K +/-1%",
            "Pcs",
            None,
            3,
            6,
            1,
            None,
            None,
            200,
        ]
        for col, v in enumerate(sample, 1):
            ws.cell(row=3, column=col, value=v)
        fname_hint = "yonglian"
    else:
        ws.append(TEMPLATE_HEADERS)
        ws.append(
            [
                "120-200001-01",
                "示例元件",
                "规格A",
                "PCS",
                "120-100001-01",
                "示例机型",
                "替代料件",
                "120-200001-02",
                "示例替代料",
                "规格B",
                "1",
                "",
                "",
                "1",
                "",
            ]
        )
        fname_hint = "standard"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    # fname_hint 仅便于调试；实际下载名由路由决定
    _ = fname_hint
    return buf.getvalue()


def _extract_purchase_no(text: str) -> str:
    if not text:
        return ""
    m = _PO_RE.search(str(text))
    return (m.group(1) or "").strip() if m else ""


def _row_header_cells(row) -> list[str]:
    return [str(c).strip() if c is not None else "" for c in row]


def _find_header_row(ws, max_scan: int = 20) -> tuple[int, list[str]]:
    """返回 1-based 表头行号与表头文本。"""
    for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), start=1):
        headers = _row_header_cells(row)
        joined = " ".join(headers)
        if "子项物料编码" in joined and "投产物料编码" in joined:
            return idx, headers
        mapped = _header_map(headers)
        if "comp_code" in mapped and "sub_code" in mapped:
            return idx, headers
    return 0, []


def _parse_yonglian_sheet(ws) -> tuple[list[dict], str]:
    """
    客户C模式：
      子项物料编码 = BOM 原料（元件品号）
      投产物料编码 = 实际投产/替代料号
      D1/U1/U2/U3/结构/M1 有用量则按板别拆行（qty=每板用量；parent 稍后绑机型）
    """
    from yonglian_board_tag import BOARD_TAGS

    header_row, headers = _find_header_row(ws)
    if not header_row:
        return [], ""
    joined = " ".join(headers)
    if "子项物料编码" not in joined or "投产物料编码" not in joined:
        return [], ""

    def col(*names: str) -> Optional[int]:
        for i, h in enumerate(headers):
            if h in names:
                return i
        return None

    i_comp = col("子项物料编码", "子项料号", "原物料编码")
    i_sub = col("投产物料编码", "投产料号", "替代物料编码")
    i_name = col("物料名称", "品名", "名称")
    i_spec = col("规格型号", "规格", "型号")
    i_unit = col("单位")
    i_merge = col("合并需求", "需求", "数量")
    i_seq = col("序号")
    board_cols = {tag: col(tag) for tag in BOARD_TAGS}
    if i_comp is None or i_sub is None:
        return [], ""

    # 表头上方标题行里常含订单号
    purchase_no = ""
    for row in ws.iter_rows(min_row=1, max_row=max(1, header_row - 1), values_only=True):
        for cell in row:
            if cell is None:
                continue
            text = str(cell)
            po = _extract_purchase_no(text)
            if not po:
                m = re.match(r"^\s*([0-9]{2}-[0-9]{6}-[A-Za-z]+-\d+)", text)
                po = (m.group(1) or "").strip() if m else ""
            if po:
                purchase_no = po
                break
        if purchase_no:
            break

    rows: list[dict] = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if not row:
            continue

        def pick(i: Optional[int]):
            return row[i] if i is not None and i < len(row) else None

        name = _cell_str(pick(i_name))
        spec = _cell_str(pick(i_spec))
        unit = _cell_str(pick(i_unit))
        seq = _cell_str(pick(i_seq))
        merge_qty = _cell_float(pick(i_merge))

        board_fills: list[tuple[str, float]] = []
        for tag, idx in board_cols.items():
            if idx is None:
                continue
            q = _cell_float(pick(idx))
            if q is not None and q > 0:
                board_fills.append((tag, q))

        # 无分板用量则跳过（不以合并需求冒充每板用量）
        if not board_fills:
            continue

        for tag, board_qty in board_fills:
            remark_parts = []
            if purchase_no:
                remark_parts.append(f"订单 {purchase_no}")
            if seq:
                remark_parts.append(f"序号 {seq}")
            remark_parts.append(f"板别{tag}")
            if merge_qty is not None:
                remark_parts.append(f"合并需求 {merge_qty:g}")
            item = _norm_row(
                {
                    "comp_code": pick(i_comp),
                    "comp_name": name,
                    "comp_spec": spec,
                    "comp_unit": unit,
                    "parent_code": "",
                    "parent_name": "",
                    "relation_type": "替代料件",
                    "sub_code": pick(i_sub),
                    "sub_name": name,
                    "sub_spec": spec,
                    "sub_unit": unit,
                    "sub_order": seq,
                    "qty": board_qty,
                    "remark": " · ".join(remark_parts),
                    "board_tag": tag,
                }
            )
            if item:
                item["board_tag"] = tag
                rows.append(item)
    return rows, purchase_no


def enrich_yonglian_rows_with_parents(
    db: Session,
    rows: list[dict],
    *,
    purchase_no: str = "",
    customer_id: str = "yonglian",
) -> tuple[list[dict], list[str]]:
    """按 board_tag / 备注中的板别绑定 bom_models → parent_code/name。"""
    from yonglian_board_tag import BOARD_TAGS, match_bom_for_board_tag

    warnings: list[str] = []
    po = (purchase_no or "").strip()
    if not po:
        for r in rows:
            rem = r.get("remark") or ""
            m = re.search(r"订单\s+([0-9A-Za-z\-]+)", rem)
            if m:
                po = m.group(1).strip()
                break

    out: list[dict] = []
    unbound = 0
    for raw in rows:
        item = dict(raw)
        tag = (item.pop("board_tag", None) or "").strip()
        if not tag:
            rem = item.get("remark") or ""
            for t in BOARD_TAGS:
                if f"板别{t}" in rem:
                    tag = t
                    break
        bom = match_bom_for_board_tag(
            db, customer_id=customer_id, purchase_no=po, board_tag=tag
        ) if tag else None
        if bom:
            item["parent_code"] = bom.model_code or ""
            item["parent_name"] = bom.model_name or ""
            item["parent_spec"] = bom.model_spec or ""
        else:
            unbound += 1
            if tag and len(warnings) < 12:
                warnings.append(f"板别 {tag} 未匹配到机型（订单 {po or '—'}）")
        normed = _norm_row(item)
        if normed:
            out.append(normed)
    if unbound:
        warnings.insert(0, f"有 {unbound} 条未绑定机型（仍导入，parent 为空）")
    return out, warnings


def _header_map(headers: list[str]) -> dict[str, int]:
    aliases = {
        "comp_code": [
            "元件品号",
            "元件料号",
            "主料号",
            "料号",
            "comp_code",
            "元件编号",
            "子项物料编码",
            "子项料号",
            "原物料编码",
        ],
        "comp_name": ["元件品名", "元件名称", "品名", "comp_name", "物料名称"],
        "comp_spec": ["元件规格", "规格", "comp_spec", "规格型号"],
        "comp_unit": ["单位", "元件单位", "comp_unit"],
        "parent_code": ["主件品号", "机型料号", "机型", "parent_code", "成品料号"],
        "parent_name": ["主件品名", "机型名称", "parent_name"],
        "relation_type": ["关系类型", "取替代料", "关系", "relation_type"],
        "sub_code": [
            "替代料号",
            "替代品号",
            "替代料",
            "sub_code",
            "投产物料编码",
            "投产料号",
            "替代物料编码",
        ],
        "sub_name": ["替代品名", "替代料名称", "sub_name"],
        "sub_spec": ["替代规格", "sub_spec"],
        "sub_order": ["顺序", "序号", "sub_order"],
        "effective_date": ["生效日期", "生效", "effective_date"],
        "expiry_date": ["失效日期", "失效", "expiry_date"],
        "qty": ["数量", "qty", "合并需求", "需求"],
        "remark": ["备注", "remark"],
    }
    idx: dict[str, int] = {}
    lowered = [(i, (h or "").strip()) for i, h in enumerate(headers)]
    for field, names in aliases.items():
        for i, h in lowered:
            if h in names or h.lower() in {n.lower() for n in names}:
                idx[field] = i
                break
    return idx


def _parse_legacy_feilisi_sheet(ws) -> list[dict]:
    """兼容旧 替代料06-03 列序（xls/xlsx 均可经 openpyxl 读）。"""
    rows: list[dict] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or len(row) < 14:
            continue
        relation = _cell_str(row[12] if len(row) > 12 else None) or ""
        if relation and relation != "替代料件":
            continue
        item = _norm_row(
            {
                "comp_code": row[0],
                "comp_name": row[1] if len(row) > 1 else None,
                "comp_spec": row[2] if len(row) > 2 else None,
                "comp_unit": row[3] if len(row) > 3 else None,
                "comp_unit_small": row[4] if len(row) > 4 else None,
                "comp_attr": row[5] if len(row) > 5 else None,
                "parent_code": row[6] if len(row) > 6 else None,
                "parent_name": row[7] if len(row) > 7 else None,
                "parent_spec": row[8] if len(row) > 8 else None,
                "parent_unit": row[9] if len(row) > 9 else None,
                "parent_unit_small": row[10] if len(row) > 10 else None,
                "parent_attr": row[11] if len(row) > 11 else None,
                "relation_type": relation or "替代料件",
                "sub_code": row[13] if len(row) > 13 else None,
                "sub_name": row[14] if len(row) > 14 else None,
                "sub_spec": row[15] if len(row) > 15 else None,
                "sub_unit": row[16] if len(row) > 16 else None,
                "sub_unit_small": row[17] if len(row) > 17 else None,
                "sub_attr": row[18] if len(row) > 18 else None,
                "sub_order": row[19] if len(row) > 19 else None,
                "effective_date": row[20] if len(row) > 20 else None,
                "expiry_date": row[21] if len(row) > 21 else None,
                "qty": row[22] if len(row) > 22 else None,
                "remark": row[23] if len(row) > 23 else None,
            }
        )
        if item:
            rows.append(item)
    return rows


def _parse_headered_sheet(ws) -> list[dict]:
    header_row, headers = _find_header_row(ws)
    if not header_row:
        # 兼容：默认第 1 行
        first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        headers = _row_header_cells(first or [])
        header_row = 1
    idx = _header_map(headers)
    if "comp_code" not in idx or "sub_code" not in idx:
        return []
    rows: list[dict] = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if not row:
            continue

        def pick(field: str):
            i = idx.get(field)
            return row[i] if i is not None and i < len(row) else None

        item = _norm_row(
            {
                "comp_code": pick("comp_code"),
                "comp_name": pick("comp_name"),
                "comp_spec": pick("comp_spec"),
                "comp_unit": pick("comp_unit"),
                "parent_code": pick("parent_code"),
                "parent_name": pick("parent_name"),
                "relation_type": pick("relation_type") or "替代料件",
                "sub_code": pick("sub_code"),
                "sub_name": pick("sub_name"),
                "sub_spec": pick("sub_spec"),
                "sub_order": pick("sub_order"),
                "effective_date": pick("effective_date"),
                "expiry_date": pick("expiry_date"),
                "qty": pick("qty"),
                "remark": pick("remark"),
            }
        )
        if item:
            rows.append(item)
    return rows


def parse_xlsx_bytes(content: bytes) -> dict:
    """解析 xlsx；兼容客户C委外表、标准模板与旧客户A宽表。"""
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        # 兼容旧 .xls：用 xlrd
        try:
            import xlrd

            book = xlrd.open_workbook(file_contents=content)
            sheet = book.sheet_by_index(0)

            class _FakeWs:
                def iter_rows(self, min_row=1, max_row=None, values_only=False):
                    start = min_row - 1
                    end = sheet.nrows if max_row is None else max_row
                    for r in range(start, end):
                        yield tuple(sheet.cell_value(r, c) for c in range(sheet.ncols))

            fake = _FakeWs()
            yl_rows, po = _parse_yonglian_sheet(fake)
            if yl_rows:
                msg = f"客户C格式解析到 {len(yl_rows)} 行"
                if po:
                    msg += f"（订单 {po}）"
                return {"rows": yl_rows, "format": "yonglian", "message": msg, "purchase_no": po}
            rows = _parse_legacy_feilisi_sheet(fake)
            if not rows:
                rows = _parse_headered_sheet(fake)
            return {"rows": rows, "format": "xls", "message": f"解析到 {len(rows)} 行"}
        except Exception as exc2:  # noqa: BLE001
            raise ValueError(f"无法解析表格: {exc}") from exc2

    ws = wb.active
    yl_rows, po = _parse_yonglian_sheet(ws)
    if yl_rows:
        msg = f"客户C格式解析到 {len(yl_rows)} 行（已按板别拆分）"
        if po:
            msg += f"（订单 {po}）"
        return {"rows": yl_rows, "format": "yonglian", "message": msg, "purchase_no": po}

    rows = _parse_headered_sheet(ws)
    fmt = "standard"
    if not rows:
        rows = _parse_legacy_feilisi_sheet(ws)
        fmt = "legacy_feilisi"
    return {"rows": rows, "format": fmt, "message": f"解析到 {len(rows)} 行"}


def parse_xlsx_bytes_with_db(
    db: Session,
    content: bytes,
    *,
    customer_id: str = "",
) -> dict:
    """解析并（客户C）绑定机型 parent。"""
    parsed = parse_xlsx_bytes(content)
    if (parsed.get("format") or "") == "yonglian" or (customer_id or "").strip().lower() in (
        "yonglian",
        "a067",
    ):
        rows, warnings = enrich_yonglian_rows_with_parents(
            db,
            parsed.get("rows") or [],
            purchase_no=parsed.get("purchase_no") or "",
            customer_id=(customer_id or "yonglian").strip() or "yonglian",
        )
        parsed["rows"] = rows
        if warnings:
            parsed["message"] = (parsed.get("message") or "") + "；" + "；".join(warnings[:5])
            parsed["warnings"] = warnings
    return parsed


def _extract_codes(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pat in _CODE_PATTERNS:
        for m in pat.finditer(text or ""):
            code = normalize_code(m.group(0))
            if len(code) < 6 or code in seen:
                continue
            seen.add(code)
            found.append(code)
    return found


def _ocr_image_bytes(content: bytes) -> str:
    from material_control_parse import _get_ocr, _ocr_image
    from PIL import Image

    ocr = _get_ocr()
    if not ocr:
        raise ValueError("OCR 引擎不可用，请安装 rapidocr_onnxruntime")
    img = Image.open(io.BytesIO(content))
    return _ocr_image(img)


def parse_image_bytes(contents: list[bytes]) -> dict:
    """多图 OCR → 规则预览行。"""
    texts: list[str] = []
    for blob in contents:
        try:
            texts.append(_ocr_image_bytes(blob))
        except Exception as exc:  # noqa: BLE001
            logger.warning("替代料图片 OCR 失败: %s", exc)
    full = "\n".join(texts)
    if not full.strip():
        return {"rows": [], "raw_text": "", "message": "未识别到文字"}

    rows: list[dict] = []
    # 按行：一行内出现 >=2 个料号，取前两个为 元件/替代
    for line in full.splitlines():
        line = line.strip()
        if not line:
            continue
        codes = _extract_codes(line)
        if len(codes) >= 2:
            item = _norm_row(
                {
                    "comp_code": codes[0],
                    "sub_code": codes[1],
                    "parent_code": codes[2] if len(codes) >= 3 else "",
                    "relation_type": "替代料件",
                    "remark": line[:120],
                }
            )
            if item:
                rows.append(item)

    # 若按行不够，全文两两配对（保守：仅当出现「替代」关键字段落）
    if not rows and ("替代" in full or "替料" in full):
        codes = _extract_codes(full)
        for i in range(0, len(codes) - 1, 2):
            item = _norm_row(
                {
                    "comp_code": codes[i],
                    "sub_code": codes[i + 1],
                    "relation_type": "替代料件",
                }
            )
            if item:
                rows.append(item)

    # 去重
    uniq: dict[tuple, dict] = {}
    for r in rows:
        key = (r["comp_code"], r["sub_code"], r.get("parent_code") or "")
        uniq[key] = r
    out = list(uniq.values())
    return {
        "rows": out,
        "raw_text": full[:4000],
        "message": f"OCR 识别到 {len(out)} 条候选规则，请核对后确认导入",
    }


def _rule_key(item: dict) -> tuple:
    return (
        normalize_code(item.get("comp_code")),
        normalize_code(item.get("parent_code")),
        normalize_code(item.get("sub_code")),
    )


def confirm_import(
    db: Session,
    *,
    customer_id: str,
    rows: list[dict],
    mode: str = "append",
    source_type: str = "xlsx",
    source_file: str = "",
) -> dict:
    cid = (customer_id or "").strip()
    if not cid:
        raise ValueError("customer_id 不能为空")
    mode = (mode or "append").strip().lower()
    if mode not in ("append", "replace", "insert_only"):
        raise ValueError("mode 须为 append / replace / insert_only")

    normalized: list[dict] = []
    for raw in rows:
        item = _norm_row(raw)
        if item:
            # 保留板别供客户C绑定
            tag = (raw.get("board_tag") or "").strip()
            if tag:
                item["board_tag"] = tag
            elif raw.get("remark"):
                item["remark"] = raw.get("remark")
            normalized.append(item)
    if not normalized:
        raise ValueError("没有可导入的有效规则行")

    if cid.lower() in ("yonglian", "a067"):
        normalized, _warn = enrich_yonglian_rows_with_parents(
            db,
            normalized,
            purchase_no="",
            customer_id=cid,
        )
        if not normalized:
            raise ValueError("客户C规则绑定后无有效行")

    now = datetime.utcnow()
    batch_id = uuid.uuid4().hex[:16]
    deleted = 0
    if mode == "replace":
        deleted = (
            db.query(SubstitutionRule)
            .filter(SubstitutionRule.customer_id == cid)
            .delete(synchronize_session=False)
        )

    existing: dict[tuple, SubstitutionRule] = {}
    if mode != "replace":
        for row in db.query(SubstitutionRule).filter(SubstitutionRule.customer_id == cid).all():
            existing[_rule_key({"comp_code": row.comp_code, "parent_code": row.parent_code, "sub_code": row.sub_code})] = row

    inserted = 0
    updated = 0
    skipped = 0
    for item in normalized:
        key = _rule_key(item)
        hit = existing.get(key)
        if hit is None:
            db.add(
                SubstitutionRule(
                    customer_id=cid,
                    **item,
                    source_type=source_type,
                    source_file=source_file or None,
                    import_batch_id=batch_id,
                    synced_at=now,
                )
            )
            inserted += 1
            continue
        if mode == "insert_only":
            skipped += 1
            continue
        for k, v in item.items():
            setattr(hit, k, v)
        hit.source_type = source_type
        hit.source_file = source_file or hit.source_file
        hit.import_batch_id = batch_id
        hit.synced_at = now
        updated += 1

    db.flush()
    reload_substitution_cache_from_db(db, cid)
    total = db.query(SubstitutionRule).filter(SubstitutionRule.customer_id == cid).count()
    return {
        "status": "success",
        "message": f"已导入客户 {cid}：新增 {inserted}，更新 {updated}，跳过 {skipped}"
        + (f"，覆盖前删除 {deleted}" if deleted else ""),
        "customer_id": cid,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "deleted": deleted,
        "import_batch_id": batch_id,
        "row_count": total,
        "synced_at": now,
    }


def create_rule(db: Session, customer_id: str, payload: dict) -> SubstitutionRule:
    cid = (customer_id or "").strip()
    item = _norm_row(payload)
    if not cid or not item:
        raise ValueError("客户与元件/替代料号不能为空")
    now = datetime.utcnow()
    row = SubstitutionRule(
        customer_id=cid,
        **item,
        source_type="manual",
        source_file=None,
        import_batch_id=None,
        synced_at=now,
    )
    db.add(row)
    db.flush()
    reload_substitution_cache_from_db(db, cid)
    return row


def update_rule(db: Session, rule_id: int, payload: dict) -> SubstitutionRule:
    row = db.query(SubstitutionRule).filter(SubstitutionRule.id == rule_id).first()
    if not row:
        raise ValueError("规则不存在")
    merged = {
        "comp_code": payload.get("comp_code", row.comp_code),
        "comp_name": payload.get("comp_name", row.comp_name),
        "comp_spec": payload.get("comp_spec", row.comp_spec),
        "comp_unit": payload.get("comp_unit", row.comp_unit),
        "parent_code": payload.get("parent_code", row.parent_code),
        "parent_name": payload.get("parent_name", row.parent_name),
        "relation_type": payload.get("relation_type", row.relation_type),
        "sub_code": payload.get("sub_code", row.sub_code),
        "sub_name": payload.get("sub_name", row.sub_name),
        "sub_spec": payload.get("sub_spec", row.sub_spec),
        "sub_order": payload.get("sub_order", row.sub_order),
        "effective_date": payload.get("effective_date", row.effective_date),
        "expiry_date": payload.get("expiry_date", row.expiry_date),
        "qty": payload.get("qty", row.qty),
        "remark": payload.get("remark", row.remark),
    }
    item = _norm_row(merged)
    if not item:
        raise ValueError("元件/替代料号无效")
    for k, v in item.items():
        setattr(row, k, v)
    if not row.source_type:
        row.source_type = "manual"
    row.synced_at = datetime.utcnow()
    db.flush()
    reload_substitution_cache_from_db(db, row.customer_id)
    return row


def delete_rule(db: Session, rule_id: int) -> str:
    row = db.query(SubstitutionRule).filter(SubstitutionRule.id == rule_id).first()
    if not row:
        raise ValueError("规则不存在")
    cid = row.customer_id
    db.delete(row)
    db.flush()
    reload_substitution_cache_from_db(db, cid)
    return cid


def confirm_manual_sub(
    db: Session,
    rule_id: int,
    *,
    sub_code: str = "",
    sub_name: str = "",
    sub_spec: str = "",
) -> SubstitutionRule:
    row = db.query(SubstitutionRule).filter(SubstitutionRule.id == rule_id).first()
    if not row:
        raise ValueError("规则不存在")
    code = _cell_code(sub_code)
    if not code:
        raise ValueError("替代料号无效")
    row.sub_code = code
    if sub_name is not None:
        row.sub_name = (sub_name or "").strip() or row.sub_name
    if sub_spec is not None:
        row.sub_spec = (sub_spec or "").strip() or row.sub_spec
    row.source_type = row.source_type or "manual"
    row.synced_at = datetime.utcnow()
    db.flush()
    reload_substitution_cache_from_db(db, row.customer_id)
    return row
