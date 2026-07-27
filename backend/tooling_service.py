"""机型工装登记（钢网 / 波峰治具 / ICT·FCT 测试工装）"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from engineering_service import list_bom_model_catalog, normalize_code
from models import BomModel, ModelToolingEntry

TOOL_TYPES = ("stencil", "wave_fixture", "ict_fct_fixture")

TOOL_TYPE_LABELS = {
    "stencil": "钢网",
    "wave_fixture": "波峰治具",
    "ict_fct_fixture": "ICT/FCT测试工装",
}


def _link_bom_model(db: Session, internal_code: str, model_code: str) -> Optional[int]:
    ic = internal_code.strip().upper()
    code = normalize_code(model_code)
    rows = (
        db.query(BomModel)
        .filter(BomModel.internal_code == ic, BomModel.is_active.is_(True))
        .all()
    )
    for item in rows:
        if normalize_code(item.model_code) == code:
            return item.id
    for item in rows:
        mc = normalize_code(item.model_code)
        if mc and (code.startswith(mc) or mc.startswith(code)):
            return item.id
    return None


def _entry_registered(row: Optional[ModelToolingEntry]) -> bool:
    return bool(row and (row.tool_code or "").strip())


def entry_to_dict(row: ModelToolingEntry) -> dict:
    return {
        "id": row.id,
        "internal_code": row.internal_code,
        "model_code": row.model_code,
        "model_name": row.model_name,
        "bom_model_id": row.bom_model_id,
        "tool_type": row.tool_type,
        "tool_type_label": TOOL_TYPE_LABELS.get(row.tool_type, row.tool_type),
        "tool_code": row.tool_code or "",
        "version": row.version or "",
        "qty": row.qty or 0,
        "stored_at": row.stored_at or "",
        "remark": row.remark or "",
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


def empty_entry(tool_type: str, internal_code: str = "", model_code: str = "") -> dict:
    return {
        "id": None,
        "internal_code": internal_code,
        "model_code": model_code,
        "model_name": None,
        "bom_model_id": None,
        "tool_type": tool_type,
        "tool_type_label": TOOL_TYPE_LABELS.get(tool_type, tool_type),
        "tool_code": "",
        "version": "",
        "qty": 1,
        "stored_at": "",
        "remark": "",
        "updated_by": None,
        "updated_at": None,
    }


def _index_tooling(db: Session, internal_code: str = "") -> dict[tuple[str, str, str], ModelToolingEntry]:
    q = db.query(ModelToolingEntry)
    if internal_code:
        q = q.filter(ModelToolingEntry.internal_code == internal_code.strip().upper())
    indexed: dict[tuple[str, str, str], ModelToolingEntry] = {}
    for row in q.all():
        key = (row.internal_code, normalize_code(row.model_code), row.tool_type)
        indexed[key] = row
    return indexed


def list_tooling_catalog(
    db: Session,
    internal_code: str = "",
    keyword: str = "",
) -> list[dict]:
    indexed = _index_tooling(db, internal_code)
    results: list[dict] = []
    for bom in list_bom_model_catalog(db, internal_code, "", keyword):
        ic = bom["internal_code"]
        mc = bom["model_code"]
        norm = normalize_code(mc)
        stencil = indexed.get((ic, norm, "stencil"))
        wave = indexed.get((ic, norm, "wave_fixture"))
        ict = indexed.get((ic, norm, "ict_fct_fixture"))
        registered = sum(1 for r in (stencil, wave, ict) if _entry_registered(r))
        results.append(
            {
                "internal_code": ic,
                "model_code": mc,
                "model_name": bom.get("model_name"),
                "bom_model_id": bom.get("id"),
                "order_count": bom.get("order_count", 0),
                "stencil_registered": _entry_registered(stencil),
                "wave_fixture_registered": _entry_registered(wave),
                "ict_fct_fixture_registered": _entry_registered(ict),
                "registered_count": registered,
                "tooling_complete": registered >= 3,
            }
        )
    return results


def get_tooling_for_model(
    db: Session,
    internal_code: str,
    model_code: str,
) -> dict:
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    norm = normalize_code(mc)
    indexed = _index_tooling(db, ic)
    entries = []
    for tool_type in TOOL_TYPES:
        row = indexed.get((ic, norm, tool_type))
        entries.append(entry_to_dict(row) if row else empty_entry(tool_type, ic, mc))
    model_name = None
    bom_id = _link_bom_model(db, ic, mc)
    if bom_id:
        bom = db.query(BomModel).filter(BomModel.id == bom_id).first()
        if bom:
            model_name = bom.model_name
    for item in entries:
        if not item.get("model_name"):
            item["model_name"] = model_name
        if not item.get("bom_model_id"):
            item["bom_model_id"] = bom_id
    return {
        "internal_code": ic,
        "model_code": mc,
        "model_name": model_name,
        "bom_model_id": bom_id,
        "entries": entries,
        "registered_count": sum(1 for e in entries if (e.get("tool_code") or "").strip()),
        "tooling_complete": all((e.get("tool_code") or "").strip() for e in entries),
    }


def save_tooling(
    db: Session,
    internal_code: str,
    model_code: str,
    entries: list[dict],
    *,
    model_name: Optional[str] = None,
    operator: Optional[str] = None,
) -> dict:
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    if not ic or not mc:
        raise ValueError("请填写内部代码和机型料号")
    norm = normalize_code(mc)
    bom_id = _link_bom_model(db, ic, mc)
    now = datetime.utcnow()
    saved: list[dict] = []

    by_type = {str(e.get("tool_type") or "").strip(): e for e in entries}
    for tool_type in TOOL_TYPES:
        payload = by_type.get(tool_type) or {}
        tool_code = str(payload.get("tool_code") or "").strip()
        version = str(payload.get("version") or "").strip()
        qty = int(payload.get("qty") or 0)
        stored_at = str(payload.get("stored_at") or "").strip()
        remark = str(payload.get("remark") or "").strip() or None

        row = (
            db.query(ModelToolingEntry)
            .filter(
                ModelToolingEntry.internal_code == ic,
                ModelToolingEntry.tool_type == tool_type,
            )
            .all()
        )
        target = None
        for item in row:
            if normalize_code(item.model_code) == norm:
                target = item
                break

        if not tool_code and not version and qty <= 0 and not stored_at:
            if target:
                db.delete(target)
            saved.append(empty_entry(tool_type, ic, mc))
            continue

        if not target:
            target = ModelToolingEntry(
                internal_code=ic,
                model_code=mc,
                tool_type=tool_type,
            )
            db.add(target)
        target.model_name = model_name or target.model_name
        target.bom_model_id = bom_id
        target.tool_code = tool_code
        target.version = version
        target.qty = max(qty, 0) or 1
        target.stored_at = stored_at
        target.remark = remark
        target.source = "manual"
        target.updated_by = operator
        target.updated_at = now
        db.flush()
        saved.append(entry_to_dict(target))

    return get_tooling_for_model(db, ic, mc)


def empty_tooling_summary() -> dict:
    return {
        "tooling_registered_count": 0,
        "tooling_complete": False,
        "tooling_status": "unknown",
        "tooling_status_label": "—",
    }


def _summary_from_registered(count: int) -> dict:
    complete = count >= 3
    if complete:
        status, label = "ready", "工装齐全"
    elif count > 0:
        status, label = "partial", f"工装 {count}/3"
    else:
        status, label = "pending", "工装未登"
    return {
        "tooling_registered_count": count,
        "tooling_complete": complete,
        "tooling_status": status,
        "tooling_status_label": label,
    }


def tooling_summary_for_model(
    db: Session,
    internal_code: Optional[str],
    model_code: Optional[str],
) -> dict:
    ic = (internal_code or "").strip().upper()
    mc = (model_code or "").strip()
    if not ic or not mc:
        return empty_tooling_summary()
    data = get_tooling_for_model(db, ic, mc)
    return _summary_from_registered(int(data.get("registered_count") or 0))


def tooling_summaries_for_orders(
    db: Session,
    pairs: list[tuple[Optional[str], Optional[str]]],
) -> dict[tuple[str, str], dict]:
    """批量工装摘要。键为 (internal_code, normalize_code(model_code))。"""
    needed: set[tuple[str, str]] = set()
    ics: set[str] = set()
    for internal_code, model_code in pairs:
        ic = (internal_code or "").strip().upper()
        mc = (model_code or "").strip()
        if not ic or not mc:
            continue
        needed.add((ic, normalize_code(mc)))
        ics.add(ic)
    if not needed:
        return {}

    q = db.query(ModelToolingEntry)
    if len(ics) == 1:
        q = q.filter(ModelToolingEntry.internal_code == next(iter(ics)))
    else:
        q = q.filter(ModelToolingEntry.internal_code.in_(list(ics)))
    registered: dict[tuple[str, str], set[str]] = {}
    for row in q.all():
        key = (row.internal_code, normalize_code(row.model_code))
        if key not in needed:
            continue
        if not _entry_registered(row):
            continue
        registered.setdefault(key, set()).add(row.tool_type)

    out: dict[tuple[str, str], dict] = {}
    for key in needed:
        count = len(registered.get(key, set()) & set(TOOL_TYPES))
        out[key] = _summary_from_registered(count)
    return out
