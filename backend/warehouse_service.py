"""仓库进销存业务"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import StockInRecord, StockIssue, StockLedger, StockReturn, WarehouseMaterial
from system_auth import AuthPrincipal

ISSUE_STATUS_PENDING = "pending_confirm"
ISSUE_STATUS_CONFIRMED = "confirmed"
ISSUE_STATUS_REJECTED = "rejected"
RETURN_STATUS_PENDING = "pending_warehouse"
RETURN_STATUS_CONFIRMED = "confirmed"
RETURN_STATUS_REJECTED = "rejected"

INBOUND_SOURCE_LABELS = {
    "manual": "手工来料",
    "excel_sync": "共享盘同步",
    "return": "退料入库",
    "customer_return": "退客出库",
    "purchase": "采购入库",
    "production": "成品入库",
    "outsource": "委托入库",
}

OUTBOUND_SOURCE_LABELS = {
    "sales": "销售出库",
    "transfer": "调拨出库",
    "other": "其他出库",
}


def record_inbound(
    db: Session,
    material: WarehouseMaterial,
    qty: float,
    source: str,
    operator: Optional[str] = None,
    remark: Optional[str] = None,
    ref_no: Optional[str] = None,
    giver: Optional[str] = None,
    receiver: Optional[str] = None,
) -> StockInRecord:
    if qty <= 0:
        raise ValueError("入库数量须大于 0")
    receipt_no = ref_no or _next_no(db, StockInRecord, "receipt_no", "SI")
    row = StockInRecord(
        receipt_no=receipt_no,
        material_id=material.id,
        customer_id=material.customer_id,
        customer_name=material.customer_name,
        material_code=material.material_code,
        material_name=material.material_name,
        qty=qty,
        source=source,
        operator=operator,
        giver=giver,
        receiver=receiver,
        remark=remark,
    )
    db.add(row)
    movement = "return_in" if source == "return" else ("excel_sync" if source == "excel_sync" else "stock_in")
    _append_ledger(
        db,
        material,
        movement,
        qty,
        ref_no=receipt_no,
        department=None,
        operator=operator,
        remark=remark or INBOUND_SOURCE_LABELS.get(source, source),
        giver=giver,
        receiver=receiver,
    )
    db.flush()
    return row


def record_outbound(
    db: Session,
    material: WarehouseMaterial,
    qty: float,
    source: str,
    operator: Optional[str] = None,
    remark: Optional[str] = None,
    ref_no: Optional[str] = None,
) -> None:
    """销售等出库：扣可用量并记 ledger（qty_delta 为负）。"""
    if qty <= 0:
        raise ValueError("出库数量须大于 0")
    avail = round(float(material.qty or 0) - float(material.locked_qty or 0), 4)
    if qty > avail + 1e-6:
        raise ValueError(f"{material.material_code} 可用库存不足（可用 {avail}）")
    material.qty = round(float(material.qty or 0) - qty, 4)
    material.updated_at = datetime.utcnow()
    _append_ledger(
        db,
        material,
        "sales_out" if source == "sales" else "stock_out",
        -qty,
        ref_no=ref_no,
        operator=operator,
        remark=remark or OUTBOUND_SOURCE_LABELS.get(source, source),
    )
    db.flush()


def _today_prefix(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d')}"


def _next_no(db: Session, model, field: str, prefix: str) -> str:
    head = _today_prefix(prefix)
    last = (
        db.query(model)
        .filter(getattr(model, field).like(f"{head}-%"))
        .order_by(getattr(model, field).desc())
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(getattr(last, field).split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{head}-{seq:03d}"


def get_material(db: Session, material_id: int) -> WarehouseMaterial:
    row = db.query(WarehouseMaterial).filter(WarehouseMaterial.id == material_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="物料不存在")
    return row


def _append_ledger(
    db: Session,
    material: WarehouseMaterial,
    movement_type: str,
    qty_delta: float,
    ref_no: Optional[str] = None,
    department: Optional[str] = None,
    operator: Optional[str] = None,
    remark: Optional[str] = None,
    giver: Optional[str] = None,
    receiver: Optional[str] = None,
) -> None:
    db.add(
        StockLedger(
            material_id=material.id,
            customer_id=material.customer_id,
            material_code=material.material_code,
            movement_type=movement_type,
            qty_delta=qty_delta,
            qty_after=material.qty,
            ref_no=ref_no,
            department=department,
            operator=operator,
            giver=giver,
            receiver=receiver,
            remark=remark,
        )
    )


def stock_in(
    db: Session,
    material_id: int,
    qty: float,
    operator: str,
    remark: Optional[str] = None,
) -> StockLedger:
    if qty <= 0:
        raise HTTPException(status_code=400, detail="来料数量须大于 0")
    material = get_material(db, material_id)
    material.qty += qty
    material.updated_at = datetime.utcnow()
    record_inbound(db, material, qty, "manual", operator=operator, remark=remark)
    db.flush()
    return db.query(StockLedger).order_by(StockLedger.id.desc()).first()


def create_issue(
    db: Session,
    material_id: int,
    qty: float,
    department: str,
    operator: str,
    remark: Optional[str] = None,
) -> StockIssue:
    department = (department or "").strip().lower()
    if department not in ("smt", "dip"):
        raise HTTPException(status_code=400, detail="发料部门仅支持 SMT 或 DIP")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="发料数量须大于 0")
    material = get_material(db, material_id)
    available = material.qty - material.locked_qty
    if qty > available:
        raise HTTPException(status_code=400, detail=f"可用库存不足（可用 {available}）")
    material.locked_qty += qty
    material.updated_at = datetime.utcnow()
    issue = StockIssue(
        issue_no=_next_no(db, StockIssue, "issue_no", "IS"),
        material_id=material.id,
        customer_id=material.customer_id,
        customer_name=material.customer_name,
        material_code=material.material_code,
        material_name=material.material_name,
        qty=qty,
        department=department,
        status=ISSUE_STATUS_PENDING,
        remark=remark,
        operator=operator,
    )
    db.add(issue)
    db.flush()
    return issue


def confirm_issue(db: Session, issue_id: int, principal: AuthPrincipal) -> StockIssue:
    issue = db.query(StockIssue).filter(StockIssue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="发料单不存在")
    if issue.status != ISSUE_STATUS_PENDING:
        raise HTTPException(status_code=400, detail="发料单状态不可确认")
    if principal.is_dept and principal.department != issue.department:
        raise HTTPException(status_code=403, detail="只能确认本部门发料单")
    material = get_material(db, issue.material_id)
    if material.locked_qty < issue.qty:
        raise HTTPException(status_code=400, detail="锁定库存异常")
    material.locked_qty -= issue.qty
    material.qty -= issue.qty
    material.updated_at = datetime.utcnow()
    issue.status = ISSUE_STATUS_CONFIRMED
    issue.confirmed_by = principal.display_name or principal.username
    issue.confirmed_at = datetime.utcnow()
    _append_ledger(
        db,
        material,
        "issue_out",
        -issue.qty,
        ref_no=issue.issue_no,
        department=issue.department,
        operator=issue.confirmed_by,
        remark=issue.remark,
        giver=issue.operator,
        receiver=issue.confirmed_by,
    )
    db.flush()
    return issue


def reject_issue(db: Session, issue_id: int, principal: AuthPrincipal, remark: Optional[str] = None) -> StockIssue:
    issue = db.query(StockIssue).filter(StockIssue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="发料单不存在")
    if issue.status != ISSUE_STATUS_PENDING:
        raise HTTPException(status_code=400, detail="发料单状态不可拒收")
    if principal.is_dept and principal.department != issue.department:
        raise HTTPException(status_code=403, detail="只能操作本部门发料单")
    material = get_material(db, issue.material_id)
    material.locked_qty = max(material.locked_qty - issue.qty, 0)
    material.updated_at = datetime.utcnow()
    issue.status = ISSUE_STATUS_REJECTED
    issue.confirmed_by = principal.display_name or principal.username
    issue.confirmed_at = datetime.utcnow()
    if remark:
        issue.remark = (issue.remark or "") + f" | 拒收: {remark}"
    db.flush()
    return issue


def create_return(
    db: Session,
    material_id: int,
    qty: float,
    department: str,
    applicant: str,
    remark: Optional[str] = None,
) -> StockReturn:
    department = (department or "").strip().lower()
    if department not in ("smt", "dip"):
        raise HTTPException(status_code=400, detail="退料部门仅支持 SMT 或 DIP")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="退料数量须大于 0")
    material = get_material(db, material_id)
    row = StockReturn(
        return_no=_next_no(db, StockReturn, "return_no", "RT"),
        material_id=material.id,
        customer_id=material.customer_id,
        customer_name=material.customer_name,
        material_code=material.material_code,
        material_name=material.material_name,
        qty=qty,
        department=department,
        status=RETURN_STATUS_PENDING,
        remark=remark,
        applicant=applicant,
    )
    db.add(row)
    db.flush()
    return row


def confirm_return(db: Session, return_id: int, operator: str, remark: Optional[str] = None) -> StockReturn:
    row = db.query(StockReturn).filter(StockReturn.id == return_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="退料单不存在")
    if row.status != RETURN_STATUS_PENDING:
        raise HTTPException(status_code=400, detail="退料单状态不可确认")
    material = get_material(db, row.material_id)
    material.qty += row.qty
    material.updated_at = datetime.utcnow()
    row.status = RETURN_STATUS_CONFIRMED
    row.confirmed_by = operator
    row.confirmed_at = datetime.utcnow()
    if remark:
        row.remark = (row.remark or "") + f" | 仓库: {remark}"
    record_inbound(
        db,
        material,
        row.qty,
        "return",
        operator=operator,
        remark=row.remark,
        ref_no=row.return_no,
        giver=row.applicant,
        receiver=operator,
    )
    db.flush()
    return row


def reject_return(db: Session, return_id: int, operator: str, remark: Optional[str] = None) -> StockReturn:
    row = db.query(StockReturn).filter(StockReturn.id == return_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="退料单不存在")
    if row.status != RETURN_STATUS_PENDING:
        raise HTTPException(status_code=400, detail="退料单状态不可驳回")
    row.status = RETURN_STATUS_REJECTED
    row.confirmed_by = operator
    row.confirmed_at = datetime.utcnow()
    if remark:
        row.remark = (row.remark or "") + f" | 驳回: {remark}"
    db.flush()
    return row
