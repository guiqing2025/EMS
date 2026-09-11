"""共享盘 BOM Excel 解析（A123/A116 首 Sheet）"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from config import get_engineering_customers, get_engineering_customer_by_code, get_engineering_share_base
from model_linkage import folder_alias_note, merge_remark
from models import BomLine, BomModel, ExcelImportLog

logger = logging.getLogger(__name__)

SKIP_FOLDER_PREFIXES = ("000", "00000")
SKIP_SUBFOLDER_NAMES = {"旧资料", "生产资料压缩包", "管制明细"}
SKIP_TOP_FOLDERS = {"生产资料压缩包", "管制明细"}


@dataclass
class ParsedBomLine:
    seq: Optional[str]
    material_code: str
    material_name: Optional[str]
    spec: Optional[str]
    unit: str
    qty_per: float
    position: Optional[str]
    process: Optional[str]
    remark: Optional[str]
    sort_order: int


@dataclass
class ParsedBom:
    model_code: str
    model_name: Optional[str]
    model_spec: Optional[str]
    lines: list[ParsedBomLine]
    folder_name: str
    source_file: str
    source_mtime: float


def resolve_engineering_share_dir() -> Path:
    configured = get_engineering_share_base()
    candidates = [
        Path(configured),
        Path("/Volumes/测试软件资料/A-生产 工程 品质共用文件夹"),
        Path.home() / "Desktop/共享-测试软件资料/A-生产 工程 品质共用文件夹",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return Path(configured)


def _norm_header(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    return re.sub(r"\s+", "", text.strip())


def _cell_str(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cell_code(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def _cell_float(value, default: float = 0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _header_map(row) -> dict[str, int]:
    return {_norm_header(cell): idx for idx, cell in enumerate(row) if _norm_header(cell)}


def _pick_col(headers: dict[str, int], *names: str) -> Optional[int]:
    for name in names:
        key = _norm_header(name)
        if key in headers:
            return headers[key]
    return None


def _row_header_preview(row, limit: int = 12) -> str:
    vals: list[str] = []
    for cell in row or []:
        h = _norm_header(cell)
        if h:
            vals.append(h)
        if len(vals) >= limit:
            break
    return "、".join(vals) if vals else "(空行)"


def _bom_header_hint(rows: list, max_scan: int = 8) -> str:
    """失败时提示前几行实际读到的表头，方便区分错文件/新格式。"""
    parts: list[str] = []
    for idx, row in enumerate(rows[:max_scan]):
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        parts.append(f"第{idx + 1}行: {_row_header_preview(row)}")
        if len(parts) >= 3:
            break
    if not parts:
        return "文件前几行均为空，请确认是否为 Excel BOM"
    return (
        "；".join(parts)
        + "。该格式需含：主件品号+元件品号（ERP导出），或 元件品号+用量（发料/备料表，机型在标题行）"
    )


def _find_bom_header_row(rows: list, max_scan: int = 60) -> Optional[int]:
    for idx, row in enumerate(rows[:max_scan]):
        headers = _header_map(row)
        has_model = _pick_col(headers, "主件品号", "主件料号", "母件品号", "母件编码", "父项品号") is not None
        has_code = _pick_col(headers, "元件品号", "元件料号", "子件品号", "子件编码", "组件品号") is not None
        if has_model and has_code:
            return idx
        # 恩玖发料/备料简化表：元件品号 + 用量（无主件列，机型在标题）
        if has_code and _pick_col(headers, "用量", "组成用量", "单位组成用量", "单位用量") is not None:
            return idx
        # 永联树状 BOM：子物料编码 + 数量
        if _pick_col(headers, "子物料编码") is not None and _pick_col(headers, "数量") is not None:
            return idx
        # 亿兰科：子项物料编码 + 用量（含 ERP「用量:分子」）
        if _pick_col(headers, "子项物料编码") is not None and _pick_col(
            headers, "用量", "用量:分子", "用量分子", "需求"
        ) is not None:
            return idx
    return None


def _extract_enjiu_title_meta(rows: list, header_idx: int) -> tuple[Optional[str], Optional[str]]:
    """从标题行解析机型/订单号。

    例：客户：A116  03029244  订单200套  订单号：3502-260714005 DIP
    例：客户：A123   120-500099-02   订单102+190=292套  订单号5105-20251226010/...
    """
    model_code = None
    purchase_no = None
    blob_parts: list[str] = []
    for row in rows[: max(header_idx, 0) + 1]:
        if not row:
            continue
        for cell in row:
            if cell is None:
                continue
            text = str(cell).strip()
            if text:
                blob_parts.append(text)
    blob = " ".join(blob_parts)
    if not blob:
        return None, None
    m_po = re.search(r"订单号[：:\s]*([0-9A-Za-z\-]+)", blob)
    if m_po:
        purchase_no = m_po.group(1).strip()
    m_model = re.search(r"A116\s+(\d{7,9})", blob, re.I)
    if m_model:
        model_code = m_model.group(1)
    if not model_code:
        # 菲利斯发料/备料表：客户：A123   120-500099-02
        m_model = re.search(r"A123\s+([0-9A-Za-z][0-9A-Za-z.\-]{5,})", blob, re.I)
        if m_model:
            model_code = m_model.group(1).strip().rstrip("，,;；")
    if not model_code:
        m_model = re.search(r"(?<!\d)(0(?:3029|3019)\d{3,4}|0\d{7})(?!\d)", blob)
        if m_model:
            model_code = m_model.group(1)
    if not model_code:
        # 菲利斯常见机型：xxx-xxxxxx-xx
        m_model = re.search(r"(?<![\dA-Za-z])(\d{2,4}-\d{5,8}-\d{2})(?![\dA-Za-z])", blob)
        if m_model:
            model_code = m_model.group(1)
    return model_code, purchase_no


def _parse_a123_rows(rows: list, header_idx: int) -> ParsedBom:
    if not rows:
        raise ValueError("空文件")
    headers = _header_map(rows[header_idx])
    idx_model = _pick_col(headers, "主件料号", "主件品号")
    idx_model_name = _pick_col(headers, "主件品名")
    idx_model_spec = _pick_col(headers, "主件规格")
    idx_seq = _pick_col(headers, "序号")
    idx_code = _pick_col(headers, "元件料号", "元件品号")
    idx_name = _pick_col(headers, "元件品名")
    idx_spec = _pick_col(headers, "元件规格")
    idx_qty = _pick_col(headers, "单位用量", "用量")
    idx_unit = _pick_col(headers, "单位")
    idx_pos = _pick_col(headers, "插件位置", "位号")
    idx_remark = _pick_col(headers, "备注")
    if idx_code is None:
        raise ValueError("非 A123 BOM 格式（缺少元件料号）")

    title_model, _title_po = _extract_enjiu_title_meta(rows, header_idx)
    model_code = title_model if idx_model is None else None
    model_name = model_spec = None
    lines: list[ParsedBomLine] = []
    sort_order = 0
    for row in rows[header_idx + 1 :]:
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        if idx_model is not None and model_code is None:
            model_code = _cell_code(row[idx_model]) if idx_model < len(row) else None
        if idx_model_name is not None and model_name is None and idx_model_name < len(row):
            model_name = _cell_str(row[idx_model_name])
        if idx_model_spec is not None and model_spec is None and idx_model_spec < len(row):
            model_spec = _cell_str(row[idx_model_spec])
        code = _cell_code(row[idx_code]) if idx_code < len(row) else None
        if not code:
            continue
        sort_order += 1
        lines.append(
            ParsedBomLine(
                seq=_cell_str(row[idx_seq]) if idx_seq is not None and idx_seq < len(row) else None,
                material_code=code,
                material_name=_cell_str(row[idx_name]) if idx_name is not None and idx_name < len(row) else None,
                spec=_cell_str(row[idx_spec]) if idx_spec is not None and idx_spec < len(row) else None,
                unit=(_cell_str(row[idx_unit]) if idx_unit is not None and idx_unit < len(row) else None) or "PCS",
                qty_per=_cell_float(row[idx_qty], 1) if idx_qty is not None and idx_qty < len(row) else 1.0,
                position=_cell_str(row[idx_pos]) if idx_pos is not None and idx_pos < len(row) else None,
                process=None,
                remark=_cell_str(row[idx_remark]) if idx_remark is not None and idx_remark < len(row) else None,
                sort_order=sort_order,
            )
        )
    if not model_code:
        raise ValueError("非 A123 BOM 格式（缺少主件料号，且标题未解析到机型料号）")
    if not lines:
        raise ValueError("未解析到元件行")
    return ParsedBom(
        model_code=model_code,
        model_name=model_name,
        model_spec=model_spec,
        lines=lines,
        folder_name="",
        source_file="",
        source_mtime=0,
    )


def _extract_yonglian_parent(rows: list, header_idx: int) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """从永联 BOM 表头区读取父物料编码/名称/型号。"""
    for i, row in enumerate(rows[:header_idx]):
        headers = _header_map(row)
        idx_code = _pick_col(headers, "父物料编码", "变更BOM编码")
        if idx_code is None:
            continue
        if i + 1 >= len(rows):
            break
        nxt = rows[i + 1]
        code = _cell_code(nxt[idx_code]) if idx_code < len(nxt) else None
        idx_name = _pick_col(headers, "父物料名称")
        idx_spec = _pick_col(headers, "型号", "父物料规格")
        name = _cell_str(nxt[idx_name]) if idx_name is not None and idx_name < len(nxt) else None
        spec = _cell_str(nxt[idx_spec]) if idx_spec is not None and idx_spec < len(nxt) else None
        if code:
            return code, name, spec
    return None, None, None


def _parse_yonglian_rows(rows: list, header_idx: int) -> ParsedBom:
    """永联树状 BOM（父物料编码 + 子物料编码/数量/装配位置）。"""
    if not rows:
        raise ValueError("空文件")
    headers = _header_map(rows[header_idx])
    idx_code = _pick_col(headers, "子物料编码")
    idx_name = _pick_col(headers, "子物料名称")
    idx_spec = _pick_col(headers, "子物料规格")
    idx_qty = _pick_col(headers, "数量")
    idx_pos = _pick_col(headers, "装配位置")
    idx_unit = _pick_col(headers, "子物料基本单位", "BOM单位", "单位")
    idx_seq = _pick_col(headers, "层次")
    idx_process = _pick_col(headers, "子物料装配类型", "MES_工序")
    idx_remark = _pick_col(headers, "BOM备注", "备注")
    if idx_code is None:
        raise ValueError("非该客户 BOM 格式（缺少子物料编码）")

    model_code, model_name, model_spec = _extract_yonglian_parent(rows, header_idx)
    lines: list[ParsedBomLine] = []
    sort_order = 0
    for row in rows[header_idx + 1 :]:
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        code = _cell_code(row[idx_code]) if idx_code < len(row) else None
        if not code:
            continue
        sort_order += 1
        lines.append(
            ParsedBomLine(
                seq=_cell_str(row[idx_seq]) if idx_seq is not None and idx_seq < len(row) else f"{sort_order:04d}",
                material_code=code,
                material_name=_cell_str(row[idx_name]) if idx_name is not None and idx_name < len(row) else None,
                spec=_cell_str(row[idx_spec]) if idx_spec is not None and idx_spec < len(row) else None,
                unit=(
                    _cell_str(row[idx_unit]) if idx_unit is not None and idx_unit < len(row) else None
                )
                or "PCS",
                qty_per=_cell_float(row[idx_qty], 1) if idx_qty is not None and idx_qty < len(row) else 1.0,
                position=_cell_str(row[idx_pos]) if idx_pos is not None and idx_pos < len(row) else None,
                process=_cell_str(row[idx_process]) if idx_process is not None and idx_process < len(row) else None,
                remark=_cell_str(row[idx_remark]) if idx_remark is not None and idx_remark < len(row) else None,
                sort_order=sort_order,
            )
        )
    if not model_code:
        raise ValueError("未解析到父物料编码（机型料号）")
    if not lines:
        raise ValueError("未解析到子物料行")
    return ParsedBom(
        model_code=model_code,
        model_name=model_name,
        model_spec=model_spec,
        lines=lines,
        folder_name="",
        source_file="",
        source_mtime=0,
    )


def _parse_a116_rows(rows: list, header_idx: int) -> ParsedBom:
    if not rows:
        raise ValueError("空文件")
    headers = _header_map(rows[header_idx])
    idx_model = _pick_col(headers, "主件品号", "主件料号", "母件品号", "母件编码", "父项品号")
    idx_model_name = _pick_col(headers, "主件品名", "母件品名")
    idx_model_spec = _pick_col(headers, "主件规格", "母件规格")
    idx_seq = _pick_col(headers, "序号")
    if idx_seq is None and idx_model is None:
        # 发料/备料表常用「工厂」列放行号
        idx_seq = _pick_col(headers, "工厂")
    idx_code = _pick_col(headers, "元件品号", "元件料号", "子件品号", "子件编码", "组件品号")
    idx_name = _pick_col(headers, "元件品名", "子件品名")
    idx_spec = _pick_col(headers, "元件规格", "子件规格")
    idx_qty = _pick_col(headers, "组成用量", "单位组成用量", "用量", "单位用量")
    idx_unit = _pick_col(headers, "单位")
    idx_pos = _pick_col(headers, "插件位置", "位号", "装配位置")
    idx_process = _pick_col(headers, "BOM单身工艺名称", "工艺名称")
    idx_remark = _pick_col(headers, "备注")
    if idx_code is None:
        raise ValueError("非 A116 BOM 格式（缺少元件品号）")

    title_model, _title_po = _extract_enjiu_title_meta(rows, header_idx)
    model_code = title_model if idx_model is None else None
    model_name = model_spec = None
    lines: list[ParsedBomLine] = []
    sort_order = 0
    for row in rows[header_idx + 1 :]:
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        if idx_model is not None and model_code is None:
            model_code = _cell_code(row[idx_model])
        if idx_model_name is not None and model_name is None:
            model_name = _cell_str(row[idx_model_name])
        if idx_model_spec is not None and model_spec is None:
            model_spec = _cell_str(row[idx_model_spec])
        code = _cell_code(row[idx_code]) if idx_code is not None else None
        if not code:
            continue
        # 跳过合计/标题误入数据行
        if code in ("元件品号", "合计", "小计"):
            continue
        sort_order += 1
        seq_val = None
        if idx_seq is not None and idx_seq < len(row):
            seq_val = _cell_str(row[idx_seq])
        lines.append(
            ParsedBomLine(
                seq=seq_val or f"{sort_order:04d}",
                material_code=code,
                material_name=_cell_str(row[idx_name]) if idx_name is not None and idx_name < len(row) else None,
                spec=_cell_str(row[idx_spec]) if idx_spec is not None and idx_spec < len(row) else None,
                unit=(
                    _cell_str(row[idx_unit]) if idx_unit is not None and idx_unit < len(row) else None
                )
                or "PCS",
                qty_per=_cell_float(row[idx_qty], 1) if idx_qty is not None and idx_qty < len(row) else 1.0,
                position=_cell_str(row[idx_pos]) if idx_pos is not None and idx_pos < len(row) else None,
                process=_cell_str(row[idx_process]) if idx_process is not None and idx_process < len(row) else None,
                remark=_cell_str(row[idx_remark]) if idx_remark is not None and idx_remark < len(row) else None,
                sort_order=sort_order,
            )
        )
    if not model_code:
        raise ValueError("未解析到主件品号（ERP 表无主件列时，请在标题行写机型如 A116 03029244）")
    if not lines:
        raise ValueError("未解析到元件行")
    if not model_name:
        model_name = "制成板"
    return ParsedBom(
        model_code=model_code,
        model_name=model_name,
        model_spec=model_spec,
        lines=lines,
        folder_name="",
        source_file="",
        source_mtime=0,
    )


def _parse_bom_sheet(ws, internal_code: str) -> ParsedBom:
    rows = list(ws.iter_rows(values_only=True))
    return _parse_bom_rows(rows, internal_code)


def _parse_bom_rows(rows: list, internal_code: str) -> ParsedBom:
    header_idx = _find_bom_header_row(rows)
    if header_idx is None:
        raise ValueError(f"未找到 BOM 表头。{_bom_header_hint(rows)}")
    headers = _header_map(rows[header_idx])
    from eng_customer_rules import bom_parse_profile_for

    profile = bom_parse_profile_for(internal_code)
    # 亿兰科专用表头（勿与永联「子物料编码」混淆）
    if _pick_col(headers, "子项物料编码") is not None:
        from yilanke_bom import parse_yilanke_rows

        return parse_yilanke_rows(rows, header_idx, filename="")
    if profile in ("yilanke", "a120"):
        from yilanke_bom import parse_yilanke_rows

        return parse_yilanke_rows(rows, header_idx, filename="")
    if _pick_col(headers, "子物料编码") is not None:
        return _parse_yonglian_rows(rows, header_idx)
    if profile == "yonglian":
        return _parse_yonglian_rows(rows, header_idx)
    if profile == "feilisi" or (
        profile == "auto"
        and (
            (internal_code or "").upper() == "A123"
            or _pick_col(headers, "主件料号") is not None
        )
    ):
        return _parse_a123_rows(rows, header_idx)
    return _parse_a116_rows(rows, header_idx)


def _xlrd_sheet_rows(sheet) -> list[list]:
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]


def _parse_with_xlrd(path: Path, internal_code: str) -> ParsedBom:
    import xlrd

    book = xlrd.open_workbook(str(path))
    last_error: Optional[Exception] = None
    preferred: list[int] = []
    rest: list[int] = []
    for i, name in enumerate(book.sheet_names()):
        uname = (name or "").upper()
        if "BOM" in uname or "物料" in uname:
            preferred.append(i)
        else:
            rest.append(i)
    for i in preferred + rest:
        try:
            candidate = _parse_bom_rows(_xlrd_sheet_rows(book.sheet_by_index(i)), internal_code)
            if candidate.lines:
                candidate.source_file = str(path)
                candidate.source_mtime = path.stat().st_mtime
                return candidate
        except Exception as exc:
            last_error = exc
            continue
    raise ValueError(str(last_error) if last_error else "未找到有效 BOM Sheet")


def _parse_with_openpyxl(path: Path, internal_code: str, *, data_only: bool) -> ParsedBom:
    last_error: Optional[Exception] = None
    parsed: Optional[ParsedBom] = None
    wb = load_workbook(path, read_only=True, data_only=data_only)
    try:
        for ws in wb.worksheets:
            try:
                candidate = _parse_bom_sheet(ws, internal_code)
                if candidate.lines:
                    parsed = candidate
                    break
            except Exception as exc:
                last_error = exc
                continue
    finally:
        wb.close()
    if parsed is None:
        raise ValueError(str(last_error) if last_error else "未找到有效 BOM Sheet")
    parsed.source_file = str(path)
    parsed.source_mtime = path.stat().st_mtime
    return parsed


def parse_bom_workbook(path: Path, internal_code: str) -> ParsedBom:
    suffix = path.suffix.lower()
    errors: list[str] = []

    if suffix == ".xls":
        return _parse_with_xlrd(path, internal_code)

    # 先按标准 xlsx 读；失败再试非 data_only；.xls 误存为 .xlsx 时再试 xlrd
    for data_only in (True, False):
        try:
            return _parse_with_openpyxl(path, internal_code, data_only=data_only)
        except Exception as exc:
            errors.append(f"openpyxl(data_only={data_only}): {exc}")
    # 仅当文件看起来不像 zip/xlsx 时才回退 xlrd，避免把「表头不匹配」掩盖成 xlsx not supported
    head = b""
    try:
        head = path.read_bytes()[:8]
    except Exception:
        pass
    if not head.startswith(b"PK"):
        try:
            return _parse_with_xlrd(path, internal_code)
        except Exception as exc:
            errors.append(f"xlrd: {exc}")
    # 优先抛出「未找到表头」类信息（含行预览）
    for msg in errors:
        if "未找到 BOM 表头" in msg:
            raise ValueError(msg.split(": ", 1)[-1] if ": " in msg else msg)
    # 去掉无意义的 xlrd/xlsx 兜底噪音
    useful = [m for m in errors if "xlsx file; not supported" not in m]
    raise ValueError((useful or errors)[-1] if (useful or errors) else "未找到有效 BOM Sheet")


def _sheet_has_bom_header(ws) -> bool:
    try:
        for row in ws.iter_rows(min_row=1, max_row=30, values_only=True):
            headers = {_norm_header(c) for c in row if _norm_header(c)}
            if ("主件品号" in headers or "主件料号" in headers) and (
                "元件品号" in headers or "元件料号" in headers
            ):
                return True
            # 恩玖发料/备料简化表
            if ("元件品号" in headers or "元件料号" in headers) and (
                "用量" in headers or "组成用量" in headers or "单位组成用量" in headers
            ):
                return True
    except StopIteration:
        return False
    return False


def _workbook_has_bom_header(path: Path) -> bool:
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return any(_sheet_has_bom_header(ws) for ws in wb.worksheets)
        finally:
            wb.close()
    except Exception:
        return False


def _latest_xlsx(folder: Path) -> Optional[Path]:
    """取机型文件夹内最新 BOM（含日期子目录，排除旧资料）"""
    files: list[Path] = []
    for path in folder.rglob("*.xlsx"):
        if path.name.startswith("~") or path.name.startswith("."):
            continue
        rel_parts = path.relative_to(folder).parts
        if len(rel_parts) > 1 and any(part in SKIP_SUBFOLDER_NAMES for part in rel_parts[:-1]):
            continue
        files.append(path)
    if not files:
        return None
    bom_candidates = []
    for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
        if _workbook_has_bom_header(f):
            bom_candidates.append(f)
    if bom_candidates:
        return bom_candidates[0]
    return None


def _norm_model_code(value: Optional[str]) -> str:
    return (value or "").strip().upper().replace(" ", "")


def _upsert_identity_codes(internal_code: str, *codes: str) -> list[str]:
    """导入身份料号集合：自身 + 客户变体（如 03019↔03029）。"""
    from model_linkage import model_code_variants_for

    out: list[str] = []
    for raw in codes:
        text = (raw or "").strip()
        if not text:
            continue
        for variant in model_code_variants_for(internal_code, text):
            norm = _norm_model_code(variant)
            if norm and norm not in out:
                out.append(norm)
    return out


def _codes_compatible(internal_code: str, left: str, right: str) -> bool:
    a = _norm_model_code(left)
    b = _norm_model_code(right)
    if not a or not b:
        return False
    if a == b:
        return True
    left_ids = set(_upsert_identity_codes(internal_code, left))
    right_ids = set(_upsert_identity_codes(internal_code, right))
    return bool(left_ids & right_ids)


def _strict_order_model_match(internal_code: str, order_code: str, model_code: str) -> bool:
    """开发补齐：严格匹配订单料号与 BOM 机型。"""
    return _codes_compatible(internal_code, order_code, model_code)


def _alias_evidence(order_code: str, erp_code: str, folder_name: str, source_file: str) -> bool:
    """文件名/文件夹同时出现订单料号与 ERP 主件（如 99010163（03029614））。"""
    blob = f"{folder_name or ''}{source_file or ''}"
    if not blob:
        return False
    return bool(order_code and order_code in blob and erp_code and erp_code in blob)


def _bom_row_matches_identities(row: BomModel, identities: list[str]) -> bool:
    if not identities:
        return False
    mc = _norm_model_code(row.model_code)
    if mc and mc in identities:
        return True
    blob = _norm_model_code(f"{row.remark or ''}{row.folder_name or ''}{row.source_file or ''}")
    return any(code in blob for code in identities if code)


def upsert_bom_model(
    db: Session,
    internal_code: str,
    customer_id: str,
    customer_name: str,
    parsed: ParsedBom,
    purchase_no: str = "",
) -> tuple[BomModel, int, int]:
    from models import SrmOrder

    pn = (purchase_no or "").strip()
    erp_code = (parsed.model_code or "").strip()
    order_code = ""
    codes: list[str] = []
    folder_name = parsed.folder_name or ""
    source_file = parsed.source_file or ""
    if pn:
        order_rows = (
            db.query(SrmOrder)
            .filter(
                SrmOrder.purchase_no == pn,
                SrmOrder.customer_id == customer_id,
                SrmOrder.product_goods_no.isnot(None),
                SrmOrder.product_goods_no != "",
            )
            .all()
        )
        for o in order_rows:
            c = str(o.product_goods_no).strip()
            if c and c not in codes:
                codes.append(c)
        if len(codes) == 1:
            sole = codes[0]
            # 同单仅一料号：优先用订单料号（兼容 99…↔03…）；若与 Excel 主件明显是另一机型则不用
            if (
                not erp_code
                or _codes_compatible(internal_code, sole, erp_code)
                or _alias_evidence(sole, erp_code, folder_name, source_file)
            ):
                order_code = sole
        elif codes and erp_code:
            # 文件名常为 99010163（03029614）：订单料号与 ERP 主件并存
            for c in codes:
                if (
                    c == erp_code
                    or _codes_compatible(internal_code, c, erp_code)
                    or c in folder_name
                    or c in source_file
                ):
                    order_code = c
                    break
            # 同单多机型时禁止盲取 codes[0]，避免把 A 机型 BOM 写到 B 料号上

    store_code = order_code or erp_code
    identities = _upsert_identity_codes(internal_code, store_code, erp_code, order_code)

    row = None
    if pn:
        # 同采购单仅复用「同一机型」（含变体/备注证据）；禁止跨机型覆盖
        candidates = (
            db.query(BomModel)
            .filter(
                BomModel.internal_code == internal_code,
                BomModel.purchase_no == pn,
                BomModel.is_active.is_(True),
            )
            .order_by(BomModel.updated_at.desc(), BomModel.id.desc())
            .all()
        )
        for cand in candidates:
            if _bom_row_matches_identities(cand, identities):
                row = cand
                break
        # 同单仅一订单料号 + 仅一份 BOM：允许 99…/03… 无变体规则时的复用
        if not row and len(candidates) == 1 and len(codes) <= 1:
            only = candidates[0]
            if not identities or _bom_row_matches_identities(only, identities):
                row = only
            elif not erp_code:
                row = only
    if not row and store_code:
        row = (
            db.query(BomModel)
            .filter(
                BomModel.internal_code == internal_code,
                BomModel.model_code == store_code,
                BomModel.purchase_no == pn,
            )
            .first()
        )
    created = 0
    updated = 0
    now = datetime.utcnow()
    if row:
        updated = 1
    else:
        row = BomModel(
            internal_code=internal_code,
            customer_id=customer_id,
            model_code=store_code,
            purchase_no=pn,
        )
        db.add(row)
        created = 1
    row.customer_name = customer_name
    row.purchase_no = pn
    row.model_code = store_code
    row.model_name = parsed.model_name
    row.model_spec = parsed.model_spec
    row.folder_name = parsed.folder_name
    row.source_file = parsed.source_file
    row.source_mtime = parsed.source_mtime
    row.line_count = len(parsed.lines)
    row.is_active = True
    alias = folder_alias_note(parsed.folder_name, internal_code, store_code)
    if alias:
        row.remark = merge_remark(row.remark, alias)
    if erp_code and order_code and erp_code != order_code:
        row.remark = merge_remark(row.remark, f"ERP主件:{erp_code}")
    row.synced_at = now
    row.updated_at = now
    db.flush()

    db.query(BomLine).filter(BomLine.bom_model_id == row.id).delete()
    for line in parsed.lines:
        db.add(
            BomLine(
                bom_model_id=row.id,
                seq=line.seq,
                material_code=line.material_code,
                material_name=line.material_name,
                spec=line.spec,
                unit=line.unit,
                qty_per=line.qty_per,
                position=line.position,
                process=line.process,
                remark=line.remark,
                sort_order=line.sort_order,
                is_active=True,
                source="import",
            )
        )
    from eng_asset_scope import refresh_bom_content_hash

    refresh_bom_content_hash(db, row)

    # 回写订单绑定：只绑本机型（含变体），避免同单其它机型被串绑
    if pn and row.id:
        q = db.query(SrmOrder).filter(SrmOrder.purchase_no == pn, SrmOrder.customer_id == customer_id)
        for o in q.all():
            og = (o.product_goods_no or "").strip()
            if not og:
                continue
            if order_code:
                if og != order_code and not _codes_compatible(internal_code, og, order_code):
                    continue
            elif identities:
                if _norm_model_code(og) not in identities and not any(
                    _codes_compatible(internal_code, og, code) for code in (store_code, erp_code) if code
                ):
                    continue
            o.bom_model_id = row.id

    return row, created, updated


def _customer_bom_roots(customer: dict, base: Path) -> list[Path]:
    folders = customer.get("bom_folders")
    if isinstance(folders, list) and folders:
        return [base / str(name).strip() for name in folders if str(name).strip()]
    bom_folder = (customer.get("bom_folder") or "").strip()
    return [base / bom_folder] if bom_folder else []


def _iter_bom_files(root: Path):
    """遍历目录下各机型 BOM 文件（子文件夹 + 根目录 xlsx）"""
    if not root.is_dir():
        return
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        if any(sub.name.startswith(p) for p in SKIP_FOLDER_PREFIXES):
            continue
        if sub.name in SKIP_TOP_FOLDERS:
            continue
        xlsx = _latest_xlsx(sub)
        if xlsx:
            yield sub.name, xlsx
    for xlsx in sorted(root.glob("*.xlsx"), key=lambda f: f.name):
        if xlsx.name.startswith("~") or xlsx.name.startswith("."):
            continue
        if _workbook_has_bom_header(xlsx):
            yield xlsx.stem, xlsx


def _import_bom_file(
    db: Session,
    internal_code: str,
    customer_id: str,
    customer_name: str,
    folder_name: str,
    xlsx: Path,
    purchase_no: str = "",
) -> dict:
    item = {
        "internal_code": internal_code,
        "folder": folder_name,
        "file": xlsx.name,
        "status": "success",
        "message": "",
        "model_code": "",
        "lines": 0,
        "purchase_no": (purchase_no or "").strip(),
    }
    try:
        parsed = parse_bom_workbook(xlsx, internal_code)
        parsed.folder_name = folder_name
        row, created, updated = upsert_bom_model(
            db, internal_code, customer_id, customer_name, parsed, purchase_no=purchase_no
        )
        item["model_code"] = parsed.model_code
        item["lines"] = len(parsed.lines)
        item["bom_model_id"] = row.id
        item["purchase_no"] = row.purchase_no or ""
        item["_created"] = created
        item["_updated"] = updated
        db.add(
            ExcelImportLog(
                source_file=str(xlsx),
                customer_name=f"{internal_code}/{parsed.model_code}",
                rows_imported=len(parsed.lines),
                rows_updated=updated,
                status="success",
                message=f"BOM 导入 {parsed.model_code}"
                + (f" / {row.purchase_no}" if row.purchase_no else ""),
            )
        )
    except Exception as exc:
        logger.exception("BOM 导入失败 %s", xlsx)
        item["status"] = "failed"
        item["message"] = str(exc)
        item["_created"] = 0
        item["_updated"] = 0
        db.add(
            ExcelImportLog(
                source_file=str(xlsx),
                customer_name=f"{internal_code}/{folder_name}",
                rows_imported=0,
                rows_updated=0,
                status="failed",
                message=str(exc),
            )
        )
    return item


def sync_all_boms(db: Session) -> dict:
    """已停用：工程 BOM 仅人工导入，不再扫描本地共享盘。"""
    return {
        "status": "disabled",
        "message": "工程 BOM 已改为人工导入，不再从本地共享盘同步",
        "files": [],
        "models_created": 0,
        "models_updated": 0,
        "share_path": "",
    }


def import_bom_bytes(
    db: Session,
    content: bytes,
    filename: str,
    *,
    internal_code: str,
    folder_name: Optional[str] = None,
    purchase_no: Optional[str] = None,
) -> dict:
    import shutil
    import tempfile
    from datetime import datetime as _dt

    ic = internal_code.strip().upper()
    pn = (purchase_no or "").strip()
    customer = get_engineering_customer_by_code(ic)
    if not customer:
        return {
            "status": "failed",
            "message": f"未知内部代码: {internal_code}",
            "model_code": "",
            "lines": 0,
            "bom_model_id": 0,
            "file": filename,
            "internal_code": ic,
            "purchase_no": pn,
        }
    if not pn:
        return {
            "status": "failed",
            "message": "请先选择在制订单后再导入 BOM（按订单号确认，不可仅按机型共用）",
            "model_code": "",
            "lines": 0,
            "bom_model_id": 0,
            "file": filename,
            "internal_code": ic,
            "purchase_no": "",
        }
    customer_id = (customer.get("customer_id") or "").strip()
    customer_name = customer.get("name") or customer_id
    safe_name = Path(filename).name or "bom.xlsx"
    if not safe_name.lower().endswith((".xlsx", ".xlsm", ".xls")):
        return {
            "status": "failed",
            "message": "请上传 Excel 文件（.xlsx / .xls）",
            "model_code": "",
            "lines": 0,
            "bom_model_id": 0,
            "file": safe_name,
            "internal_code": ic,
            "purchase_no": pn,
        }
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / safe_name
        path.write_bytes(content)
        fn = (folder_name or f"upload:{safe_name}").strip()
        item = _import_bom_file(db, ic, customer_id, customer_name, fn, path, purchase_no=pn)
        if item.get("status") == "success" and item.get("bom_model_id"):
            row = db.query(BomModel).filter(BomModel.id == item["bom_model_id"]).first()
            if row:
                row.source_file = f"upload:{safe_name}"
        elif item.get("status") == "failed":
            # 失败留档，便于对照表头（临时目录会随请求销毁）
            try:
                fail_dir = Path(__file__).resolve().parent / "data" / "failed_bom_uploads"
                fail_dir.mkdir(parents=True, exist_ok=True)
                stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
                keep = fail_dir / f"{ic}_{pn}_{stamp}_{safe_name}"
                shutil.copy2(path, keep)
                item["message"] = f"{item.get('message') or '导入失败'}（已留档 {keep.name}）"
            except OSError:
                pass
        item.setdefault("bom_model_id", 0)
        item["internal_code"] = ic
        item["file"] = safe_name
        item["purchase_no"] = pn
        return item
