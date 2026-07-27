"""SMT/DIP 排产"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from engineering_service import compute_kitting, order_kitting
from models import ProductionSchedule, SrmOrder


MATERIAL_STATUS_LABELS = {
    "unknown": "未算",
    "unbound": "未绑BOM",
    "ready": "齐套",
    "partial": "部分齐",
    "shortage": "欠料",
}

SCHEDULE_STATUS_LABELS = {
    "planned": "待产",
    "running": "生产中",
    "done": "完工",
    "hold": "暂停",
}

TOOLING_STATUS_LABELS = {
    "unknown": "—",
    "pending": "工装未登",
    "partial": "工装部分",
    "ready": "工装齐全",
}


def schedule_to_dict(db: Session, row: ProductionSchedule) -> dict:
    from tooling_service import tooling_summary_for_model

    payload = {
        "id": row.id,
        "line_type": row.line_type,
        "sort_order": row.sort_order,
        "line_name": row.line_name,
        "line_key": row.line_key,
        "internal_code": row.internal_code,
        "customer_id": row.customer_id,
        "purchase_no": row.purchase_no,
        "model_code": row.model_code,
        "model_name": row.model_name,
        "process": row.process,
        "order_qty": row.order_qty or 0,
        "due_date": row.due_date,
        "material_status": row.material_status or "unknown",
        "daily_plan": row.daily_plan,
        "schedule_status": row.schedule_status or "planned",
        "remark": row.remark,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }
    payload.update(tooling_summary_for_model(db, row.internal_code, row.model_code))
    return payload


def refresh_material_status(db: Session, row: ProductionSchedule) -> str:
    if row.line_key:
        kit = order_kitting(db, row.line_key)
        return kit.get("material_status", "unknown")
    if row.model_code and row.customer_id and row.order_qty:
        from engineering_service import normalize_code, suggest_bom_model
        from models import BomModel

        q = db.query(BomModel).filter(
            BomModel.customer_id == row.customer_id,
            BomModel.model_code == row.model_code,
            BomModel.is_active.is_(True),
            BomModel.line_count > 0,
        )
        pn = (row.purchase_no or "").strip()
        if pn:
            q = q.filter(BomModel.purchase_no == pn)
        else:
            q = q.filter(BomModel.purchase_no != "")
        bom = q.order_by(BomModel.id.desc()).first()
        if not bom and pn:
            order = SrmOrder(
                customer_id=row.customer_id,
                product_goods_no=row.model_code,
                purchase_no=pn,
                batch_pur_qty=row.order_qty,
            )
            bom = suggest_bom_model(db, order)
        if bom:
            kit = compute_kitting(db, bom.id, row.order_qty or 0)
            return kit.get("material_status", "unknown")
    return row.material_status or "unknown"


def list_schedules(db: Session, line_type: str) -> list[ProductionSchedule]:
    return (
        db.query(ProductionSchedule)
        .filter(ProductionSchedule.line_type == line_type)
        .order_by(ProductionSchedule.sort_order.asc(), ProductionSchedule.id.asc())
        .all()
    )


def create_schedule(db: Session, data: dict, operator: str) -> ProductionSchedule:
    max_sort = (
        db.query(ProductionSchedule.sort_order)
        .filter(ProductionSchedule.line_type == data["line_type"])
        .order_by(ProductionSchedule.sort_order.desc())
        .first()
    )
    row = ProductionSchedule(
        line_type=data["line_type"],
        sort_order=data.get("sort_order") if data.get("sort_order") is not None else ((max_sort[0] + 1) if max_sort else 1),
        line_name=data.get("line_name"),
        line_key=data.get("line_key"),
        internal_code=data.get("internal_code"),
        customer_id=data.get("customer_id"),
        purchase_no=data.get("purchase_no"),
        model_code=data.get("model_code"),
        model_name=data.get("model_name"),
        process=data.get("process"),
        order_qty=float(data.get("order_qty") or 0),
        due_date=data.get("due_date"),
        material_status=data.get("material_status") or "unknown",
        daily_plan=data.get("daily_plan"),
        schedule_status=data.get("schedule_status") or "planned",
        remark=data.get("remark"),
        updated_by=operator,
    )
    row.material_status = refresh_material_status(db, row)
    db.add(row)
    db.flush()
    return row


def update_schedule(db: Session, schedule_id: int, data: dict, operator: str) -> ProductionSchedule:
    row = db.query(ProductionSchedule).filter(ProductionSchedule.id == schedule_id).first()
    if not row:
        raise ValueError("排产行不存在")
    for key in (
        "line_name", "line_key", "internal_code", "customer_id", "purchase_no",
        "model_code", "model_name", "process", "due_date", "daily_plan",
        "schedule_status", "remark", "sort_order",
    ):
        if key in data:
            setattr(row, key, data[key])
    if "order_qty" in data and data["order_qty"] is not None:
        row.order_qty = float(data["order_qty"])
    if "material_status" in data and data["material_status"]:
        row.material_status = data["material_status"]
    row.updated_by = operator
    row.updated_at = datetime.utcnow()
    if data.get("refresh_kitting"):
        row.material_status = refresh_material_status(db, row)
    return row


def delete_schedule(db: Session, schedule_id: int) -> None:
    row = db.query(ProductionSchedule).filter(ProductionSchedule.id == schedule_id).first()
    if not row:
        raise ValueError("排产行不存在")
    db.delete(row)


def reorder_schedules(db: Session, line_type: str, ids: list[int]) -> None:
    for idx, schedule_id in enumerate(ids, start=1):
        row = (
            db.query(ProductionSchedule)
            .filter(ProductionSchedule.id == schedule_id, ProductionSchedule.line_type == line_type)
            .first()
        )
        if row:
            row.sort_order = idx


def import_from_order(db: Session, line_key: str, line_type: str, operator: str) -> ProductionSchedule:
    from customer_kitting import compute_customer_kit_status, is_customer_kit_tracked

    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise ValueError("订单不存在")
    if is_customer_kit_tracked(order.customer_id):
        order_qty = order.batch_pur_qty or order.output_qty or 0
        kit_status = compute_customer_kit_status(
            order.collected_sets_qty, order_qty, order.customer_id, order.material_status
        )
        if kit_status == "unkit":
            raise ValueError(
                f"客户尚未齐套（已齐套 {int(order.collected_sets_qty or 0)} 套 / 订单 {int(order_qty)} 套），暂不可导入排产"
            )
    from config import get_engineering_customer_by_srm_id

    eng = get_engineering_customer_by_srm_id(order.customer_id)
    data = {
        "line_type": line_type,
        "line_key": order.line_key,
        "internal_code": eng.get("internal_code") if eng else None,
        "customer_id": order.customer_id,
        "purchase_no": order.purchase_no,
        "model_code": order.product_goods_no,
        "model_name": order.product_goods_name,
        "process": line_type.upper(),
        "order_qty": order.batch_pur_qty or 0,
        "due_date": order.expect_arrival_date,
    }
    return create_schedule(db, data, operator)
