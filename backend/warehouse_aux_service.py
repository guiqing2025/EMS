"""阶段8：仓储辅助 — 盘点、调拨、库存出库"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import StocktakeDoc, StocktakeLine, TransferDoc, TransferLine, WarehouseMaterial
from warehouse_service import record_inbound, record_outbound


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _get_or_create(db: Session, *, owner: str, code: str, name: str = "") -> WarehouseMaterial:
    owner = (owner or "internal").strip() or "internal"
    code = (code or "").strip()
    if not code:
        raise ValueError("料号不能为空")
    row = (
        db.query(WarehouseMaterial)
        .filter(WarehouseMaterial.customer_id == owner, WarehouseMaterial.material_code == code)
        .first()
    )
    if row:
        return row
    row = WarehouseMaterial(
        customer_id=owner,
        customer_name="内部库存" if owner == "internal" else owner,
        material_code=code,
        material_name=name or code,
        qty=0,
        locked_qty=0,
    )
    db.add(row)
    db.flush()
    return row


def stocktake_to_dict(row: StocktakeDoc, lines: list[StocktakeLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "stocktake_no": row.stocktake_no,
        "stock_owner": row.stock_owner,
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "posted_at": row.posted_at,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "book_qty": ln.book_qty,
                "count_qty": ln.count_qty,
                "diff_qty": round(float(ln.count_qty or 0) - float(ln.book_qty or 0), 4),
            }
            for ln in lines
        ]
    return d


def list_stocktakes(db: Session, *, limit: int = 100) -> list[StocktakeDoc]:
    return db.query(StocktakeDoc).order_by(StocktakeDoc.id.desc()).limit(limit).all()


def get_stocktake(db: Session, sid: int) -> tuple[StocktakeDoc, list[StocktakeLine]]:
    row = db.query(StocktakeDoc).filter(StocktakeDoc.id == sid).first()
    if not row:
        raise ValueError("盘点单不存在")
    lines = db.query(StocktakeLine).filter(StocktakeLine.stocktake_id == sid).all()
    return row, lines


def create_stocktake(db: Session, data: dict, *, user: str) -> StocktakeDoc:
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("盘点至少一行")
    owner = (data.get("stock_owner") or "internal").strip() or "internal"
    row = StocktakeDoc(
        stocktake_no=next_doc_number(db, "stocktake"),
        stock_owner=owner,
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    for raw in lines:
        code = (raw.get("material_code") or "").strip()
        mat = (
            db.query(WarehouseMaterial)
            .filter(WarehouseMaterial.customer_id == owner, WarehouseMaterial.material_code == code)
            .first()
        )
        book = float(raw.get("book_qty") if raw.get("book_qty") is not None else (mat.qty if mat else 0))
        db.add(
            StocktakeLine(
                stocktake_id=row.id,
                material_code=code,
                material_name=(raw.get("material_name") or (mat.material_name if mat else "") or code),
                book_qty=book,
                count_qty=float(raw.get("count_qty") if raw.get("count_qty") is not None else book),
                unit=(raw.get("unit") or "PCS"),
            )
        )
    db.flush()
    return row


def post_stocktake(db: Session, sid: int, *, user: str) -> StocktakeDoc:
    row, lines = get_stocktake(db, sid)
    if row.status != "draft":
        raise ValueError(f"盘点单状态 {row.status} 不可过账")
    for ln in lines:
        diff = round(float(ln.count_qty or 0) - float(ln.book_qty or 0), 4)
        if abs(diff) < 1e-9:
            continue
        mat = _get_or_create(db, owner=row.stock_owner, code=ln.material_code, name=ln.material_name)
        if diff > 0:
            mat.qty = round(float(mat.qty or 0) + diff, 4)
            mat.updated_at = _now()
            record_inbound(
                db, mat, diff, "manual", operator=user, remark=f"盘盈 {row.stocktake_no}", ref_no=row.stocktake_no
            )
        else:
            record_outbound(
                db,
                mat,
                abs(diff),
                "other",
                operator=user,
                remark=f"盘亏 {row.stocktake_no}",
                ref_no=row.stocktake_no,
            )
    row.status = "posted"
    row.posted_by = user
    row.posted_at = _now()
    _touch(row)
    db.flush()
    return row


def transfer_to_dict(row: TransferDoc, lines: list[TransferLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "doc_no": row.doc_no,
        "kind": row.kind,
        "from_owner": row.from_owner,
        "to_owner": row.to_owner or "",
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "posted_at": row.posted_at,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {"id": ln.id, "material_code": ln.material_code, "material_name": ln.material_name, "qty": ln.qty}
            for ln in lines
        ]
    return d


def list_transfers(db: Session, *, kind: str = "", limit: int = 100) -> list[TransferDoc]:
    q = db.query(TransferDoc)
    if kind.strip():
        q = q.filter(TransferDoc.kind == kind.strip())
    return q.order_by(TransferDoc.id.desc()).limit(limit).all()


def get_transfer(db: Session, tid: int) -> tuple[TransferDoc, list[TransferLine]]:
    row = db.query(TransferDoc).filter(TransferDoc.id == tid).first()
    if not row:
        raise ValueError("调拨/出库单不存在")
    lines = db.query(TransferLine).filter(TransferLine.transfer_id == tid).all()
    return row, lines


def create_transfer(db: Session, data: dict, *, user: str) -> TransferDoc:
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("至少一行")
    kind = (data.get("kind") or "transfer").strip() or "transfer"
    if kind not in ("transfer", "out"):
        raise ValueError("kind 须为 transfer 或 out")
    from_owner = (data.get("from_owner") or "internal").strip() or "internal"
    to_owner = (data.get("to_owner") or "").strip()
    if kind == "transfer" and not to_owner:
        raise ValueError("调拨须填写目标库存归属")
    if kind == "transfer" and to_owner == from_owner:
        raise ValueError("调拨目标不能与来源相同")
    doc_type = "transfer" if kind == "transfer" else "inventory_out"
    row = TransferDoc(
        doc_no=next_doc_number(db, doc_type),
        kind=kind,
        from_owner=from_owner,
        to_owner=to_owner,
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    for raw in lines:
        db.add(
            TransferLine(
                transfer_id=row.id,
                material_code=(raw.get("material_code") or "").strip(),
                material_name=(raw.get("material_name") or "").strip(),
                qty=float(raw.get("qty") or 0),
                unit=(raw.get("unit") or "PCS"),
            )
        )
    db.flush()
    return row


def post_transfer(db: Session, tid: int, *, user: str) -> TransferDoc:
    row, lines = get_transfer(db, tid)
    if row.status != "draft":
        raise ValueError(f"单据状态 {row.status} 不可过账")
    for ln in lines:
        qty = float(ln.qty or 0)
        if qty <= 0:
            raise ValueError("数量须大于 0")
        src = _get_or_create(db, owner=row.from_owner, code=ln.material_code, name=ln.material_name)
        record_outbound(
            db,
            src,
            qty,
            "transfer" if row.kind == "transfer" else "other",
            operator=user,
            remark=f"{'调拨' if row.kind == 'transfer' else '库存出库'} {row.doc_no}",
            ref_no=row.doc_no,
        )
        if row.kind == "transfer":
            dst = _get_or_create(db, owner=row.to_owner, code=ln.material_code, name=ln.material_name)
            dst.qty = round(float(dst.qty or 0) + qty, 4)
            dst.updated_at = _now()
            record_inbound(
                db,
                dst,
                qty,
                "manual",
                operator=user,
                remark=f"调拨入 {row.doc_no} ← {row.from_owner}",
                ref_no=row.doc_no,
            )
    row.status = "posted"
    row.posted_by = user
    row.posted_at = _now()
    _touch(row)
    db.flush()
    return row
