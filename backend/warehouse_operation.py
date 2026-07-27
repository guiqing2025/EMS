"""仓库进出账统一操作：进账 / 发料扣账 / 退料 / 退客 / 超领 / 损耗 / 盘亏。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import WarehouseMaterial, WarehouseMovement
from warehouse_movements import (
    MOVEMENT_ADJUST,
    MOVEMENT_CUSTOMER_RETURN,
    MOVEMENT_INBOUND,
    MOVEMENT_ISSUE,
    MOVEMENT_LABELS,
    MOVEMENT_OVERISSUE,
    MOVEMENT_RETURN,
    MOVEMENT_SMT_LOSS,
    _dedupe_key,
)
from warehouse_service import _append_ledger, _next_no, get_material, record_inbound

# movement_type -> (qty 符号, 流水类型)
# 退客：产线不良退仓后还要退回客户，库存应减少（出库）
_MOVEMENT_RULES: dict[str, tuple[int, str]] = {
    MOVEMENT_INBOUND: (1, "stock_in"),
    MOVEMENT_ISSUE: (-1, "issue_out"),
    MOVEMENT_RETURN: (1, "return_in"),
    MOVEMENT_CUSTOMER_RETURN: (-1, "issue_out"),
    MOVEMENT_OVERISSUE: (-1, "issue_out"),
    MOVEMENT_SMT_LOSS: (-1, "issue_out"),
    MOVEMENT_ADJUST: (-1, "issue_out"),
}

_OUTBOUND_TYPES = {
    MOVEMENT_ISSUE,
    MOVEMENT_OVERISSUE,
    MOVEMENT_SMT_LOSS,
    MOVEMENT_ADJUST,
    MOVEMENT_CUSTOMER_RETURN,
}

# 人手操作要求填写接收人的类型
_REQUIRE_RECEIVER = {
    MOVEMENT_INBOUND,
    MOVEMENT_ISSUE,
    MOVEMENT_OVERISSUE,
    MOVEMENT_CUSTOMER_RETURN,
    MOVEMENT_RETURN,
}

# 发料侧默认「给方」= 操作人
_DEFAULT_GIVER_AS_OPERATOR = {
    MOVEMENT_ISSUE,
    MOVEMENT_OVERISSUE,
    MOVEMENT_SMT_LOSS,
    MOVEMENT_ADJUST,
    MOVEMENT_CUSTOMER_RETURN,
}


def apply_movement(
    db: Session,
    material_id: int,
    movement_type: str,
    qty: float,
    operator: str,
    *,
    order_no: str = "",
    product_model: str = "",
    order_qty: Optional[float] = None,
    process: Optional[str] = None,
    ref_no: str = "",
    remark: str = "",
    doc_date: Optional[str] = None,
    department: Optional[str] = None,
    allow_negative: bool = True,
    giver: Optional[str] = None,
    receiver: Optional[str] = None,
) -> WarehouseMovement:
    """执行一笔仓库进出账，同步更新库存、流水与进出账明细。"""
    movement_type = (movement_type or "").strip()
    if movement_type not in _MOVEMENT_RULES:
        raise HTTPException(status_code=400, detail=f"不支持的进出账类型: {movement_type}")

    qty_val = abs(float(qty or 0))
    if qty_val <= 0:
        raise HTTPException(status_code=400, detail="数量须大于 0")

    giver_val = (giver or "").strip() or None
    receiver_val = (receiver or "").strip() or None
    operator_val = (operator or "").strip() or None

    if movement_type in _DEFAULT_GIVER_AS_OPERATOR and not giver_val:
        giver_val = operator_val
    if movement_type in (MOVEMENT_INBOUND,) and not receiver_val:
        receiver_val = operator_val

    if movement_type in _REQUIRE_RECEIVER and not receiver_val:
        raise HTTPException(status_code=400, detail="请填写接收人")

    material = get_material(db, material_id)
    sign, ledger_type = _MOVEMENT_RULES[movement_type]
    qty_delta = sign * qty_val

    if movement_type in _OUTBOUND_TYPES and not allow_negative:
        available = float(material.qty) - float(material.locked_qty)
        if qty_val > available + 1e-6:
            raise HTTPException(status_code=400, detail=f"可用库存不足（可用 {available:g}）")

    material.qty = float(material.qty) + qty_delta
    material.updated_at = datetime.utcnow()

    voucher_no = ref_no.strip() or _next_no(db, WarehouseMovement, "ref_no", "MV")
    if not doc_date:
        doc_date = datetime.now().strftime("%Y-%m-%d")

    movement = WarehouseMovement(
        customer_id=material.customer_id,
        customer_name=material.customer_name,
        movement_type=movement_type,
        material_code=material.material_code,
        material_name=material.material_name or "",
        spec=material.spec or "",
        unit=material.unit or "PCS",
        qty=qty_val,
        qty_delta=qty_delta,
        order_no=(order_no or "").strip(),
        product_model=(product_model or "").strip(),
        order_qty=order_qty,
        process=(process or "").strip().lower() or None,
        doc_date=doc_date,
        ref_no=voucher_no,
        source="system",
        source_file="",
        dedupe_key=_dedupe_key("system", material.customer_id, voucher_no, movement_type, material.material_code),
        remark=remark.strip(),
        operator=operator_val,
        giver=giver_val,
        receiver=receiver_val,
    )
    db.add(movement)
    db.flush()

    label = MOVEMENT_LABELS.get(movement_type, movement_type)
    ledger_remark = remark.strip() or label
    if order_no:
        ledger_remark = f"{label} · 订单 {order_no}" + (f" · {remark}" if remark else "")

    if movement_type == MOVEMENT_INBOUND:
        record_inbound(
            db,
            material,
            qty_val,
            "manual",
            operator=operator_val,
            remark=ledger_remark,
            ref_no=voucher_no,
            giver=giver_val,
            receiver=receiver_val,
        )
    else:
        _append_ledger(
            db,
            material,
            ledger_type,
            qty_delta,
            ref_no=voucher_no,
            department=department,
            operator=operator_val,
            remark=ledger_remark,
            giver=giver_val,
            receiver=receiver_val,
        )

    db.flush()
    return movement
