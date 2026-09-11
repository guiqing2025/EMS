"""流程图对齐：工程 BOM 主数据（销售订单绑定 / MRP 展开），不依赖 SRM 客户目录。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import BomLine, BomModel


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    row.updated_at = _now()


def list_boms(db: Session, *, q: str = "", active_only: bool = True, limit: int = 200) -> list[BomModel]:
    query = db.query(BomModel)
    if active_only:
        query = query.filter(BomModel.is_active.is_(True))
    kw = (q or "").strip()
    if kw:
        like = f"%{kw}%"
        query = query.filter(
            (BomModel.model_code.ilike(like))
            | (BomModel.model_name.ilike(like))
            | (BomModel.customer_name.ilike(like))
            | (BomModel.purchase_no.ilike(like))
        )
    return query.order_by(BomModel.id.desc()).limit(limit).all()


def get_bom(db: Session, bom_id: int) -> tuple[BomModel, list[BomLine]]:
    bom = db.query(BomModel).filter(BomModel.id == bom_id).first()
    if not bom:
        raise ValueError("BOM 不存在")
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == bom_id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order, BomLine.id)
        .all()
    )
    return bom, lines


def create_bom(db: Session, data: dict, *, user: str = "") -> BomModel:
    model_code = (data.get("model_code") or "").strip()
    if not model_code:
        raise ValueError("成品料号必填")
    bom = BomModel(
        internal_code=(data.get("internal_code") or "ERP").strip().upper() or "ERP",
        customer_id=(data.get("customer_id") or "internal").strip() or "internal",
        customer_name=(data.get("customer_name") or "").strip(),
        model_code=model_code,
        purchase_no=(data.get("purchase_no") or "").strip(),
        model_name=(data.get("model_name") or "").strip() or model_code,
        model_spec=(data.get("model_spec") or "").strip() or None,
        remark=(data.get("remark") or "").strip() or None,
        line_count=0,
        content_hash="",
        is_active=True,
        eng_review_status="approved",
        eng_reviewed_by=user or None,
        eng_reviewed_at=_now() if user else None,
        updated_at=_now(),
    )
    db.add(bom)
    db.flush()
    lines = data.get("lines") or []
    if lines:
        _replace_lines(db, bom, lines)
    return bom


def update_bom(db: Session, bom_id: int, data: dict, *, user: str = "") -> BomModel:
    bom, _ = get_bom(db, bom_id)
    for field in ("customer_id", "customer_name", "model_code", "model_name", "model_spec", "purchase_no", "remark", "internal_code"):
        if field in data and data[field] is not None:
            val = data[field]
            if field in ("customer_id", "customer_name", "model_code", "model_name", "model_spec", "purchase_no", "remark", "internal_code"):
                val = str(val).strip()
            if field == "internal_code":
                val = val.upper() or "ERP"
            if field == "model_code" and not val:
                raise ValueError("成品料号必填")
            setattr(bom, field, val or (None if field in ("model_spec", "remark") else val))
    if "is_active" in data:
        bom.is_active = bool(data["is_active"])
    if "lines" in data:
        _replace_lines(db, bom, data.get("lines") or [])
    _touch(bom)
    db.flush()
    return bom


def _replace_lines(db: Session, bom: BomModel, lines: list[dict]) -> None:
    db.query(BomLine).filter(BomLine.bom_model_id == bom.id).delete(synchronize_session=False)
    count = 0
    for i, raw in enumerate(lines):
        code = (raw.get("material_code") or "").strip()
        if not code:
            continue
        qty = float(raw.get("qty_per") or 0)
        if qty <= 0:
            continue
        db.add(
            BomLine(
                bom_model_id=bom.id,
                seq=str(raw.get("seq") or i + 1),
                material_code=code,
                material_name=(raw.get("material_name") or "").strip() or None,
                spec=(raw.get("spec") or "").strip() or None,
                unit=(raw.get("unit") or "PCS").strip() or "PCS",
                qty_per=qty,
                position=(raw.get("position") or "").strip() or None,
                process=(raw.get("process") or "").strip() or None,
                remark=(raw.get("remark") or "").strip() or None,
                sort_order=int(raw.get("sort_order") or i),
                is_active=True,
                source="erp",
            )
        )
        count += 1
    bom.line_count = count
    _touch(bom)
    db.flush()


def deactivate_bom(db: Session, bom_id: int) -> BomModel:
    bom, _ = get_bom(db, bom_id)
    bom.is_active = False
    _touch(bom)
    db.flush()
    return bom


def bom_to_dict(bom: BomModel, lines: Optional[list[BomLine]] = None) -> dict:
    out = {
        "id": bom.id,
        "internal_code": bom.internal_code,
        "customer_id": bom.customer_id,
        "customer_name": bom.customer_name,
        "model_code": bom.model_code,
        "model_name": bom.model_name or "",
        "model_spec": bom.model_spec or "",
        "purchase_no": bom.purchase_no or "",
        "line_count": bom.line_count,
        "is_active": bool(bom.is_active),
        "eng_review_status": bom.eng_review_status,
        "remark": bom.remark or "",
        "updated_at": bom.updated_at.isoformat() if bom.updated_at else "",
    }
    if lines is not None:
        out["lines"] = [
            {
                "id": ln.id,
                "seq": ln.seq or "",
                "material_code": ln.material_code,
                "material_name": ln.material_name or "",
                "spec": ln.spec or "",
                "unit": ln.unit or "PCS",
                "qty_per": float(ln.qty_per or 0),
                "position": ln.position or "",
                "process": ln.process or "",
                "remark": ln.remark or "",
                "sort_order": ln.sort_order,
            }
            for ln in lines
        ]
    return out
