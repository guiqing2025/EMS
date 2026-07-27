"""物料进出账详情：关联订单、来料记录、库存是否够用。"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from models import StockInRecord, StockLedger, WarehouseMaterial, WarehouseMovement
from warehouse_movements import MOVEMENT_ISSUE, MOVEMENT_LABELS, MOVEMENT_OVERISSUE, MOVEMENT_RETURN
from warehouse_service import INBOUND_SOURCE_LABELS, get_material


def _movement_out(row: WarehouseMovement) -> dict:
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name,
        "movement_type": row.movement_type,
        "movement_type_name": MOVEMENT_LABELS.get(row.movement_type, row.movement_type),
        "material_code": row.material_code,
        "material_name": row.material_name,
        "spec": row.spec,
        "unit": row.unit or "PCS",
        "qty": row.qty,
        "qty_delta": row.qty_delta,
        "order_no": row.order_no or "",
        "product_model": row.product_model or "",
        "order_qty": row.order_qty,
        "process": row.process,
        "doc_date": row.doc_date or "",
        "ref_no": row.ref_no or "",
        "source": row.source,
        "operator": row.operator,
        "giver": getattr(row, "giver", None),
        "receiver": getattr(row, "receiver", None),
        "remark": row.remark,
        "created_at": row.created_at,
    }


def get_material_detail(db: Session, material_id: int) -> dict:
    material = get_material(db, material_id)
    code = material.material_code

    movements = (
        db.query(WarehouseMovement)
        .filter(
            WarehouseMovement.customer_id == material.customer_id,
            WarehouseMovement.material_code == code,
        )
        .order_by(WarehouseMovement.doc_date.desc(), WarehouseMovement.id.desc())
        .limit(300)
        .all()
    )

    stock_ins = (
        db.query(StockInRecord)
        .filter(StockInRecord.material_id == material_id)
        .order_by(StockInRecord.created_at.desc())
        .limit(100)
        .all()
    )

    ledger = (
        db.query(StockLedger)
        .filter(StockLedger.material_id == material_id)
        .order_by(StockLedger.created_at.desc())
        .limit(100)
        .all()
    )

    order_buckets: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "order_no": "",
            "product_model": "",
            "issued_qty": 0.0,
            "returned_qty": 0.0,
            "inbound_qty": 0.0,
            "last_date": "",
        }
    )

    inbound_total = 0.0
    outbound_total = 0.0
    for m in movements:
        if m.qty_delta > 0:
            inbound_total += float(m.qty)
        elif m.qty_delta < 0:
            outbound_total += abs(float(m.qty_delta))

        if not m.order_no:
            continue
        key = (m.order_no, m.product_model or "")
        bucket = order_buckets[key]
        bucket["order_no"] = m.order_no
        bucket["product_model"] = m.product_model or ""
        if m.movement_type in (MOVEMENT_ISSUE, MOVEMENT_OVERISSUE):
            bucket["issued_qty"] += float(m.qty)
        elif m.movement_type == MOVEMENT_RETURN:
            bucket["returned_qty"] += float(m.qty)
        if m.doc_date and m.doc_date >= bucket["last_date"]:
            bucket["last_date"] = m.doc_date

    orders = sorted(
        order_buckets.values(),
        key=lambda x: (x["last_date"], x["order_no"]),
        reverse=True,
    )

    count_qty = float(material.excel_count_qty or 0)
    in_qty = float(material.excel_in_qty or 0)
    demand_qty = float(material.excel_demand_qty) if material.excel_demand_qty is not None else None
    current_qty = float(material.qty)
    available = max(current_qty - float(material.locked_qty), 0)

    stock_status = "unknown"
    stock_gap: Optional[float] = None
    if demand_qty is not None:
        stock_gap = current_qty - demand_qty
        stock_status = "enough" if stock_gap >= 0 else "short"

    last_inbound = stock_ins[0] if stock_ins else None

    return {
        "material": {
            "id": material.id,
            "customer_id": material.customer_id,
            "customer_name": material.customer_name,
            "material_code": material.material_code,
            "material_name": material.material_name,
            "spec": material.spec,
            "unit": material.unit or "PCS",
            "qty": current_qty,
            "locked_qty": float(material.locked_qty),
            "available_qty": available,
            "excel_count_qty": material.excel_count_qty,
            "excel_in_qty": material.excel_in_qty,
            "excel_demand_qty": material.excel_demand_qty,
            "excel_synced_at": material.excel_synced_at,
            "remark": material.remark,
            "last_inbound_at": last_inbound.created_at if last_inbound else None,
            "last_inbound_qty": last_inbound.qty if last_inbound else None,
            "last_inbound_source": last_inbound.source if last_inbound else None,
            "last_inbound_source_name": INBOUND_SOURCE_LABELS.get(last_inbound.source, last_inbound.source)
            if last_inbound
            else None,
        },
        "summary": {
            "current_qty": current_qty,
            "available_qty": available,
            "locked_qty": float(material.locked_qty),
            "excel_count_qty": count_qty,
            "excel_in_qty": in_qty,
            "excel_demand_qty": demand_qty,
            "stock_status": stock_status,
            "stock_gap": stock_gap,
            "inbound_total": inbound_total,
            "outbound_total": outbound_total,
            "order_count": len(orders),
            "movement_count": len(movements),
        },
        "orders": orders,
        "movements": [_movement_out(m) for m in movements],
        "stock_ins": [
            {
                "id": r.id,
                "receipt_no": r.receipt_no,
                "qty": r.qty,
                "source": r.source,
                "source_name": INBOUND_SOURCE_LABELS.get(r.source, r.source),
                "operator": r.operator,
                "giver": getattr(r, "giver", None),
                "receiver": getattr(r, "receiver", None),
                "remark": r.remark,
                "created_at": r.created_at,
            }
            for r in stock_ins
        ],
        "ledger": [
            {
                "id": r.id,
                "movement_type": r.movement_type,
                "qty_delta": r.qty_delta,
                "qty_after": r.qty_after,
                "ref_no": r.ref_no,
                "operator": r.operator,
                "giver": getattr(r, "giver", None),
                "receiver": getattr(r, "receiver", None),
                "remark": r.remark,
                "created_at": r.created_at,
            }
            for r in ledger
        ],
    }
