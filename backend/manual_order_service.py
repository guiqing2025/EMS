"""小客户手动录单（不参与 SRM 同步）"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.orm import Session

from models import SrmOrder
from srm_client import make_line_key

MANUAL_DATA_SOURCE = "手动录入"


def manual_customer_id(customer_name: str) -> str:
    name = (customer_name or "").strip() or "未命名客户"
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    return f"manual_{digest}"


def create_manual_order(db: Session, payload: dict) -> SrmOrder:
    customer_name = (payload.get("customer_name") or "").strip()
    purchase_no = (payload.get("purchase_no") or "").strip()
    if not customer_name:
        raise ValueError("请填写客户名称")
    if not purchase_no:
        raise ValueError("请填写订单号")

    seq = str(payload.get("purchase_seq") or "1").strip() or "1"
    phase = str(payload.get("purchase_phase_seq") or "1").strip() or "1"
    qty = float(payload.get("batch_pur_qty") or 0)
    if qty <= 0:
        raise ValueError("订单量须大于 0")

    customer_id = manual_customer_id(customer_name)
    line_key = make_line_key(customer_id, purchase_no, seq, phase)
    existing = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if existing:
        raise ValueError(f"订单 {purchase_no} 第{seq}行已存在")

    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    order = SrmOrder(
        line_key=line_key,
        customer_id=customer_id,
        customer_name=customer_name,
        purchase_no=purchase_no,
        purchase_seq=seq,
        purchase_phase_seq=phase,
        product_goods_no=(payload.get("product_goods_no") or "").strip() or None,
        product_goods_name=(payload.get("product_goods_name") or "").strip() or None,
        product_spec=(payload.get("product_spec") or "").strip() or None,
        batch_pur_qty=qty,
        output_qty=qty,
        un_delivery_qty=qty,
        un_receive_qty=qty,
        purchase_date=(payload.get("purchase_date") or "").strip() or today,
        expect_arrival_date=(payload.get("expect_arrival_date") or "").strip() or None,
        order_type_name="手动录单",
        srm_status_name="进行中",
        is_completed=False,
        data_source=MANUAL_DATA_SOURCE,
        remark=(payload.get("remark") or "").strip() or None,
        synced_at=now,
    )
    db.add(order)
    return order


def list_manual_customers(db: Session) -> list[dict]:
    rows = (
        db.query(SrmOrder.customer_id, SrmOrder.customer_name)
        .filter(SrmOrder.data_source == MANUAL_DATA_SOURCE)
        .distinct()
        .order_by(SrmOrder.customer_name)
        .all()
    )
    return [{"id": cid, "name": name or cid} for cid, name in rows]
