"""从共享盘「钢网明细 / 治具明细」同步到工装登记。

规则（产品确认）：
1. 仅同步系统已有 4 家：菲利斯 A123 / 恩玖 A116 / 永联 A067 / 亿兰科 A120
2. 钢网品名多机型按空格等拆分，共用同一 DX 编码
3. 共享盘为准，覆盖手工登记（含 source=manual）
4. 治具默认波峰；备注含 ICT/FCT/测试架等才进 ICT/FCT
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from config import (
    get_tooling_fixture_path,
    get_tooling_stencil_path,
    get_tooling_warehouse_dir,
)
from engineering_service import normalize_code
from models import ModelToolingEntry
from tooling_service import TOOL_TYPES, _link_bom_model

logger = logging.getLogger(__name__)

# Excel 客户简称 → 内部代码（仅 1A 范围内）
CUSTOMER_ALIASES: dict[str, str] = {
    "菲利斯": "A123",
    "恩玖": "A116",
    "恩 玖": "A116",
    "恩玖·鼎雄": "A116",
    "恩玖鼎雄": "A116",
    "永联": "A067",
    "亿兰科": "A120",
}

ALLOWED_INTERNAL = frozenset({"A123", "A116", "A067", "A120"})

ICT_KEYWORDS = ("ICT", "FCT", "测试架", "测试工装", "ICT/FCT", "ICT治具", "FCT治具")

_NOISE_MODEL = re.compile(
    r"^(试产|外发|外发文件|外发资料|工艺文件|同面|客供|客供治具|BOM|V\d+(\.\d+)?)$",
    re.I,
)
_DX_CODE = re.compile(r"^DX\d+", re.I)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip()


def _date_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        d = value.date()
        if d.year < 2000:
            return ""
        return d.isoformat()
    if isinstance(value, date):
        if value.year < 2000:
            return ""
        return value.isoformat()
    text = _text(value)
    if not text:
        return ""
    m = re.match(r"^(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 2000:
            return ""
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return text[:16]
    return text[:16]


def _qty(value: Any) -> int:
    text = _text(value)
    if not text:
        return 1
    try:
        n = int(float(text))
        return max(n, 0) or 1
    except ValueError:
        return 1


def resolve_customer_internal(name: str) -> Optional[str]:
    raw = (name or "").strip()
    if not raw:
        return None
    if raw.upper() in ALLOWED_INTERNAL:
        return raw.upper()
    compact = re.sub(r"\s+", "", raw)
    for alias, code in CUSTOMER_ALIASES.items():
        if alias == raw or re.sub(r"\s+", "", alias) == compact:
            return code
    # 前缀匹配：如「恩玖治具」sheet 名已是客户名
    for alias, code in CUSTOMER_ALIASES.items():
        a = re.sub(r"\s+", "", alias)
        if compact.startswith(a) or a.startswith(compact):
            return code
    return None


def _is_ict_remark(remark: str) -> bool:
    t = (remark or "").upper().replace(" ", "")
    for kw in ICT_KEYWORDS:
        if kw.upper().replace(" ", "") in t:
            return True
    return False


def split_model_names(raw: str) -> list[str]:
    """钢网品名：按空白/逗号拆成多机型。"""
    text = _text(raw)
    if not text:
        return []
    parts = re.split(r"[\s,，;；]+", text)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        token = _clean_model_token(part)
        if not token:
            continue
        key = normalize_code(token)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _clean_model_token(part: str) -> str:
    s = _text(part)
    if not s:
        return ""
    for junk in ("工艺文件", "外发文件", "外发资料", "外发", "试产"):
        if s.endswith(junk):
            s = s[: -len(junk)].rstrip("-_ ")
    s = re.sub(r"[（(][^）)]*[）)]$", "", s).strip()
    if not s or _NOISE_MODEL.match(s):
        return ""
    if normalize_code(s) in ALLOWED_INTERNAL:
        return ""
    # 至少含数字或长度够，过滤纯中文备注碎片
    if not re.search(r"[0-9A-Za-z]", s):
        return ""
    if len(s) < 3:
        return ""
    return s


def _header_index_map(header_row: tuple) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        label = _text(cell)
        if label:
            mapping[label] = idx
    return mapping


def _col(mapping: dict[str, int], *names: str) -> Optional[int]:
    for name in names:
        if name in mapping:
            return mapping[name]
    # 模糊：列名包含关键字
    for name in names:
        for key, idx in mapping.items():
            if name in key:
                return idx
    return None


def _cell(row: tuple, idx: Optional[int]) -> Any:
    if idx is None or idx < 0 or idx >= len(row):
        return None
    return row[idx]


def _resolve_workbook(configured: str, *name_keywords: str) -> Path:
    path = Path(configured).expanduser() if configured else None
    if path and path.is_file() and not path.name.startswith("~$"):
        return path
    base = Path(get_tooling_warehouse_dir())
    if not base.is_dir():
        raise FileNotFoundError(f"工装共享目录不可访问: {base}")
    candidates: list[Path] = []
    for p in base.iterdir():
        if not p.is_file() or p.suffix.lower() not in (".xlsx", ".xlsm"):
            continue
        if p.name.startswith("~$"):
            continue
        if all(kw in p.name for kw in name_keywords):
            candidates.append(p)
    if not candidates:
        hint = configured or str(base / ("+".join(name_keywords)))
        raise FileNotFoundError(f"未找到工装 Excel: {hint}")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def resolve_stencil_path() -> Path:
    return _resolve_workbook(get_tooling_stencil_path(), "钢网")


def resolve_fixture_path() -> Path:
    return _resolve_workbook(get_tooling_fixture_path(), "治具")


def parse_stencil_rows(path: Path) -> tuple[list[dict], list[str]]:
    """返回 (待写入记录, 未映射客户列表)。"""
    wb = load_workbook(path, read_only=True, data_only=True)
    records: list[dict] = []
    unmapped: list[str] = []
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            header_map: Optional[dict[str, int]] = None
            for row in ws.iter_rows(values_only=True):
                vals = tuple(row)
                labels = [_text(v) for v in vals[:12]]
                if header_map is None:
                    joined = "".join(labels)
                    if "内部编号" in joined and ("客户" in joined or "品名" in joined):
                        header_map = _header_index_map(vals[:16])
                    continue
                assert header_map is not None
                code = _text(_cell(vals, _col(header_map, "内部编号")))
                if not code or not _DX_CODE.match(code):
                    continue
                customer = _text(_cell(vals, _col(header_map, "客户")))
                ic = resolve_customer_internal(customer)
                if not ic:
                    if customer:
                        unmapped.append(customer)
                    continue
                models = split_model_names(_text(_cell(vals, _col(header_map, "品名"))))
                if not models:
                    continue
                thickness = _text(_cell(vals, _col(header_map, "厚度")))
                location = _text(_cell(vals, _col(header_map, "存放位置")))
                supplier = _text(_cell(vals, _col(header_map, "供应商")))
                remark_raw = _text(_cell(vals, _col(header_map, "备注")))
                stored = _date_text(_cell(vals, _col(header_map, "到厂日期"))) or _date_text(
                    _cell(vals, _col(header_map, "下单日期"))
                )
                remark_parts = [p for p in (location and f"位置:{location}", supplier and f"供应商:{supplier}", remark_raw) if p]
                remark = "；".join(remark_parts)[:256] or None
                for model in models:
                    records.append(
                        {
                            "internal_code": ic,
                            "model_code": model,
                            "tool_type": "stencil",
                            "tool_code": code.upper(),
                            "version": thickness,
                            "qty": 1,
                            "stored_at": stored,
                            "remark": remark,
                            "customer_name": customer,
                            "source_sheet": sheet_name,
                        }
                    )
    finally:
        wb.close()
    return records, sorted(set(unmapped))


def parse_fixture_rows(path: Path) -> tuple[list[dict], list[str]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    records: list[dict] = []
    unmapped_sheets: list[str] = []
    try:
        for sheet_name in wb.sheetnames:
            ic = resolve_customer_internal(sheet_name)
            if not ic:
                # sheet「鼎雄」「1」「A135」等跳过或记未映射
                if sheet_name.strip() and sheet_name.strip() not in ("1",):
                    unmapped_sheets.append(sheet_name)
                continue
            ws = wb[sheet_name]
            header_map: Optional[dict[str, int]] = None
            for row in ws.iter_rows(values_only=True):
                vals = tuple(row)
                labels = [_text(v) for v in vals[:14]]
                joined = "".join(labels)
                if header_map is None:
                    if "序号" in joined or "来料日期" in joined or "入库日期" in joined:
                        if any(
                            k in joined
                            for k in ("产品型号", "规格型号", "治具型号", "型号", "客户料号")
                        ):
                            header_map = _header_index_map(vals[:14])
                    continue
                assert header_map is not None
                model_raw = ""
                for key in ("客户料号", "产品型号", "规格型号", "治具型号", "型号"):
                    idx = _col(header_map, key)
                    candidate = _text(_cell(vals, idx))
                    if candidate:
                        model_raw = candidate
                        break
                if not model_raw:
                    continue
                models = split_model_names(model_raw)
                # 若拆分后为空，整串清洗一次
                if not models:
                    cleaned = _clean_model_token(model_raw)
                    if cleaned:
                        models = [cleaned]
                if not models:
                    continue
                stored = _date_text(
                    _cell(vals, _col(header_map, "来料日期", "入库日期", "下单日期"))
                )
                qty = _qty(_cell(vals, _col(header_map, "数量")))
                ab = _text(_cell(vals, _col(header_map, "A/B")))
                spec = _text(_cell(vals, _col(header_map, "规格", "规格/型号")))
                supplier = _text(_cell(vals, _col(header_map, "供应商")))
                remark_raw = _text(_cell(vals, _col(header_map, "备注")))
                remark_parts = [
                    p
                    for p in (
                        ab and f"面:{ab}",
                        spec and f"规格:{spec}",
                        supplier and f"供应商:{supplier}",
                        remark_raw,
                    )
                    if p
                ]
                remark = "；".join(remark_parts)[:256] or None
                tool_type = "ict_fct_fixture" if _is_ict_remark(remark or "") else "wave_fixture"
                for model in models:
                    # tool_code 用机型料号（治具台账通常无独立编码）
                    records.append(
                        {
                            "internal_code": ic,
                            "model_code": model,
                            "tool_type": tool_type,
                            "tool_code": model,
                            "version": ab or "",
                            "qty": qty,
                            "stored_at": stored,
                            "remark": remark,
                            "customer_name": sheet_name,
                            "source_sheet": sheet_name,
                        }
                    )
    finally:
        wb.close()
    return records, sorted(set(unmapped_sheets))


def _merge_records(rows: list[dict]) -> list[dict]:
    """同一 (ic, model, tool_type) 合并：数量相加，保留较新入库日与备注。"""
    merged: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        ic = row["internal_code"]
        mc = row["model_code"]
        tt = row["tool_type"]
        key = (ic, normalize_code(mc), tt)
        prev = merged.get(key)
        if not prev:
            merged[key] = dict(row)
            continue
        prev["qty"] = int(prev.get("qty") or 0) + int(row.get("qty") or 0)
        if (row.get("stored_at") or "") > (prev.get("stored_at") or ""):
            prev["stored_at"] = row.get("stored_at") or prev.get("stored_at")
            if row.get("tool_code"):
                prev["tool_code"] = row["tool_code"]
            if row.get("version"):
                prev["version"] = row["version"]
        # 合并备注片段
        remarks = []
        for r in (prev.get("remark"), row.get("remark")):
            if r and r not in remarks:
                remarks.append(r)
        prev["remark"] = "；".join(remarks)[:256] or None
    return list(merged.values())


def _upsert_entry(
    db: Session,
    row: dict,
    *,
    operator: Optional[str],
    now: datetime,
) -> str:
    """返回 created / updated。共享盘覆盖手工。"""
    ic = row["internal_code"]
    mc = row["model_code"]
    tt = row["tool_type"]
    norm = normalize_code(mc)
    candidates = (
        db.query(ModelToolingEntry)
        .filter(ModelToolingEntry.internal_code == ic, ModelToolingEntry.tool_type == tt)
        .all()
    )
    target = None
    for item in candidates:
        if normalize_code(item.model_code) == norm:
            target = item
            break
    bom_id = _link_bom_model(db, ic, mc)
    created = target is None
    if created:
        target = ModelToolingEntry(internal_code=ic, model_code=mc, tool_type=tt)
        db.add(target)
    target.model_code = mc
    target.bom_model_id = bom_id
    target.tool_code = (row.get("tool_code") or "").strip()
    target.version = (row.get("version") or "") or None
    target.qty = max(int(row.get("qty") or 1), 0) or 1
    target.stored_at = (row.get("stored_at") or "") or None
    target.remark = row.get("remark")
    target.source = "excel"
    target.updated_by = operator
    target.updated_at = now
    return "created" if created else "updated"


def sync_tooling_from_share(
    db: Session,
    *,
    dry_run: bool = False,
    operator: Optional[str] = None,
) -> dict:
    stencil_path = resolve_stencil_path()
    fixture_path = resolve_fixture_path()

    stencil_rows, stencil_unmapped = parse_stencil_rows(stencil_path)
    fixture_rows, fixture_unmapped = parse_fixture_rows(fixture_path)

    all_rows = _merge_records(stencil_rows + fixture_rows)
    now = datetime.utcnow()

    created = updated = 0
    by_type: dict[str, int] = {t: 0 for t in TOOL_TYPES}
    by_customer: dict[str, int] = {}
    samples: list[dict] = []

    for row in all_rows:
        by_type[row["tool_type"]] = by_type.get(row["tool_type"], 0) + 1
        by_customer[row["internal_code"]] = by_customer.get(row["internal_code"], 0) + 1
        if len(samples) < 12:
            samples.append(
                {
                    "internal_code": row["internal_code"],
                    "model_code": row["model_code"],
                    "tool_type": row["tool_type"],
                    "tool_code": row["tool_code"],
                    "qty": row["qty"],
                    "stored_at": row.get("stored_at") or "",
                }
            )
        if dry_run:
            continue
        action = _upsert_entry(db, row, operator=operator, now=now)
        if action == "created":
            created += 1
        else:
            updated += 1

    if not dry_run:
        db.flush()

    summary = (
        f"{'试运行' if dry_run else '同步完成'}：钢网源 {len(stencil_rows)} 行 → "
        f"治具源 {len(fixture_rows)} 行 → 合并后 {len(all_rows)} 条"
        + (f"；新建 {created} / 更新 {updated}" if not dry_run else "")
    )
    logger.info("%s | stencil=%s fixture=%s", summary, stencil_path.name, fixture_path.name)

    return {
        "ok": True,
        "dry_run": dry_run,
        "message": summary,
        "stencil_file": str(stencil_path),
        "fixture_file": str(fixture_path),
        "stencil_parsed": len(stencil_rows),
        "fixture_parsed": len(fixture_rows),
        "merged_count": len(all_rows),
        "created": created,
        "updated": updated,
        "by_tool_type": by_type,
        "by_internal_code": by_customer,
        "unmapped_stencil_customers": stencil_unmapped[:40],
        "unmapped_fixture_sheets": fixture_unmapped[:40],
        "samples": samples,
    }
