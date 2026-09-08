"""客户侧齐套 / 备料齐套追踪"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from models import SrmOrder

# 菲利斯：SRM collectedSetsQty
CUSTOMER_KIT_SRM_IDS = frozenset({"feilisi"})
# 恩玖等：无客户齐套字段，用 EMS BOM×库存算 material_status
CUSTOMER_KIT_EMS_IDS = frozenset({"enjiu"})

CUSTOMER_KIT_LABELS = {
    "unkit": "未齐套",
    "partial": "部分齐套",
    "ready": "已齐套",
    "unbound": "未绑BOM",
    "na": "—",
}


def is_customer_kit_tracked(customer_id: Optional[str]) -> bool:
    cid = customer_id or ""
    return cid in CUSTOMER_KIT_SRM_IDS or cid in CUSTOMER_KIT_EMS_IDS


def is_customer_kit_srm(customer_id: Optional[str]) -> bool:
    return (customer_id or "") in CUSTOMER_KIT_SRM_IDS


def is_customer_kit_ems(customer_id: Optional[str]) -> bool:
    return (customer_id or "") in CUSTOMER_KIT_EMS_IDS


def ems_material_status_to_kit_status(material_status: Optional[str]) -> str:
    if material_status == "ready":
        return "ready"
    if material_status == "partial":
        return "partial"
    if material_status == "unbound":
        return "unbound"
    return "unkit"


def is_order_fulfillment_done(
    *,
    order_qty: float = 0,
    delivery_qty: Optional[float] = None,
    un_delivery_qty: Optional[float] = None,
    receive_qty: Optional[float] = None,
    is_completed: Optional[bool] = None,
) -> bool:
    """已结案或交货/收货已盖订单量 → 业务上视为出完，齐套列不再显示未齐套。"""
    if is_completed:
        return True
    qty = float(order_qty or 0)
    if qty <= 0:
        return False
    delivered = float(delivery_qty or 0)
    if delivered + 1e-6 >= qty:
        return True
    received = float(receive_qty or 0)
    if received + 1e-6 >= qty:
        return True
    if un_delivery_qty is not None and delivered > 0 and float(un_delivery_qty) <= 1e-6:
        return True
    return False


def compute_customer_kit_status(
    collected_sets_qty: float,
    order_qty: float,
    customer_id: Optional[str] = None,
    material_status: Optional[str] = None,
    *,
    fulfillment_done: Optional[bool] = None,
    delivery_qty: Optional[float] = None,
    un_delivery_qty: Optional[float] = None,
    receive_qty: Optional[float] = None,
    is_completed: Optional[bool] = None,
) -> str:
    if not is_customer_kit_tracked(customer_id):
        return "na"
    done = fulfillment_done
    if done is None and (
        delivery_qty is not None
        or un_delivery_qty is not None
        or receive_qty is not None
        or is_completed is not None
    ):
        done = is_order_fulfillment_done(
            order_qty=order_qty,
            delivery_qty=delivery_qty,
            un_delivery_qty=un_delivery_qty,
            receive_qty=receive_qty,
            is_completed=is_completed,
        )
    if done:
        return "ready"
    if is_customer_kit_ems(customer_id):
        if material_status:
            return ems_material_status_to_kit_status(material_status)
        qty = float(order_qty or 0)
        if qty <= 0:
            return "na"
        return "unkit"
    collected = float(collected_sets_qty or 0)
    qty = float(order_qty or 0)
    if qty <= 0:
        return "na"
    if collected <= 0:
        return "unkit"
    if collected + 1e-6 >= qty:
        return "ready"
    return "partial"


def is_customer_kitted(
    collected_sets_qty: float,
    order_qty: float,
    customer_id: Optional[str] = None,
    material_status: Optional[str] = None,
) -> bool:
    return compute_customer_kit_status(
        collected_sets_qty, order_qty, customer_id, material_status
    ) in ("ready", "partial")


def ems_kitting_to_collected_sets(kit: dict, order_qty: float) -> float:
    """将 EMS 备料齐套结果折算为「已齐套套数」供订单列表统一展示。"""
    status = kit.get("material_status")
    qty = float(order_qty or 0)
    if qty <= 0:
        return 0
    if status == "ready":
        return qty
    lines = kit.get("lines") or []
    if lines:
        min_sets = None
        for line in lines:
            req_per = float(line.get("qty_per") or 0)
            if req_per <= 0:
                continue
            avail = float(line.get("available_qty") or 0)
            can = avail / req_per
            min_sets = can if min_sets is None else min(min_sets, can)
        if min_sets is not None and min_sets > 0:
            return round(min(min_sets, qty), 4)
    if status == "partial":
        total = int(kit.get("total_lines") or 0)
        ready = int(kit.get("ready_count") or 0)
        if total > 0 and ready > 0:
            return round(qty * ready / total, 4)
    return 0


def _record_kitting_alert(
    kitting_alerts: Optional[list],
    order: SrmOrder,
    new_qty: float,
    order_qty: float,
    kitted_at: datetime,
    kit_source: str,
) -> None:
    if kitting_alerts is None:
        return
    kitting_alerts.append(
        {
            "line_key": order.line_key,
            "customer_id": order.customer_id,
            "customer_name": order.customer_name,
            "purchase_no": order.purchase_no,
            "product_goods_no": order.product_goods_no,
            "product_goods_name": order.product_goods_name,
            "collected_sets_qty": new_qty,
            "batch_pur_qty": order_qty,
            "kitted_at": kitted_at.isoformat(),
            "kit_source": kit_source,
        }
    )


def apply_ems_material_kitting_state(
    order: SrmOrder,
    kit: dict,
    kitting_alerts: Optional[list] = None,
) -> bool:
    """恩玖等客户：用 BOM×库存刷新 material_status 与 collected_sets_qty。"""
    if not is_customer_kit_ems(order.customer_id):
        return False

    order_qty = float(order.batch_pur_qty or order.output_qty or 0)
    # 已出完/结案：冻结为已齐套，避免库存被消耗后刷回「未齐套」
    if is_order_fulfillment_done(
        order_qty=order_qty,
        delivery_qty=getattr(order, "delivery_qty", None),
        un_delivery_qty=getattr(order, "un_delivery_qty", None),
        receive_qty=getattr(order, "receive_qty", None),
        is_completed=bool(getattr(order, "is_completed", False)),
    ):
        order.material_status = "ready"
        order.collected_sets_qty = order_qty if order_qty > 0 else float(order.collected_sets_qty or 0)
        if not order.customer_kitted_at:
            order.customer_kitted_at = datetime.utcnow()
        return True

    old_qty = float(order.collected_sets_qty or 0)
    old_status = (order.material_status or "").strip()
    new_qty = ems_kitting_to_collected_sets(kit, order_qty)
    new_status = kit.get("material_status") or "unknown"

    # 曾齐套后不因库存回落改成欠料（生产领料后常见）
    if old_status == "ready" and new_status != "ready":
        order.collected_sets_qty = max(old_qty, new_qty, order_qty if order_qty > 0 else 0)
        order.material_status = "ready"
        if not order.customer_kitted_at:
            order.customer_kitted_at = datetime.utcnow()
        return True

    order.material_status = new_status
    order.collected_sets_qty = new_qty

    if order.customer_kitted_at:
        return True
    if new_qty > 0:
        now = datetime.utcnow()
        order.customer_kitted_at = now
        if old_qty <= 0:
            _record_kitting_alert(kitting_alerts, order, new_qty, order_qty, now, "ems_bom")
    else:
        order.customer_kitted_at = None
    return True


def apply_customer_kitting_state(
    existing: Optional[SrmOrder],
    order_data: dict,
    kitting_alerts: Optional[list] = None,
) -> dict:
    """菲利斯 SRM 同步：更新 customer_kitted_at，并在 0→>0 时记录提醒。"""
    customer_id = order_data.get("customer_id")
    if not is_customer_kit_srm(customer_id):
        return order_data

    new_qty = float(order_data.get("collected_sets_qty") or 0)
    old_qty = float(existing.collected_sets_qty or 0) if existing else 0
    order_qty = float(order_data.get("batch_pur_qty") or order_data.get("output_qty") or 0)

    if existing and existing.customer_kitted_at:
        order_data["customer_kitted_at"] = existing.customer_kitted_at
    elif new_qty > 0:
        now = datetime.utcnow()
        order_data["customer_kitted_at"] = now
        if existing and old_qty <= 0 and kitting_alerts is not None:
            kitting_alerts.append(
                {
                    "line_key": order_data.get("line_key"),
                    "customer_id": customer_id,
                    "customer_name": order_data.get("customer_name"),
                    "purchase_no": order_data.get("purchase_no"),
                    "product_goods_no": order_data.get("product_goods_no"),
                    "product_goods_name": order_data.get("product_goods_name"),
                    "collected_sets_qty": new_qty,
                    "batch_pur_qty": order_qty,
                    "kitted_at": now.isoformat(),
                    "kit_source": "srm_sets",
                }
            )
    else:
        order_data["customer_kitted_at"] = None

    return order_data


def strip_client_kitting_if_unavailable(order_data: dict) -> dict:
    """客户 SRM 无齐套字段时：不同步覆盖齐料列。

    - 菲利斯：保留 SRM 下发的 collected_sets_qty
    - 恩玖等 EMS 齐套客户：弹出字段，避免把库内 BOM×库存结果冲成空
    - 其他客户：显式清零，避免脏数据
    """
    cid = order_data.get("customer_id")
    if cid in CUSTOMER_KIT_SRM_IDS:
        return order_data
    if cid in CUSTOMER_KIT_EMS_IDS:
        order_data.pop("collected_sets_qty", None)
        order_data.pop("material_status", None)
        order_data.pop("customer_kitted_at", None)
        return order_data
    order_data["collected_sets_qty"] = 0
    order_data["material_status"] = None
    order_data["customer_kitted_at"] = None
    return order_data


def save_synced_order(
    db,
    existing: Optional[SrmOrder],
    order_data: dict,
    new_orders: Optional[list],
    kitting_alerts: Optional[list],
) -> None:
    order_data = strip_client_kitting_if_unavailable(order_data)
    order_data = apply_customer_kitting_state(existing, order_data, kitting_alerts)
    # 内部工单号已停用：同步不得写入/覆盖该字段
    order_data.pop("internal_wo_no", None)
    # tax_price 仅用于单价缓存，非 SrmOrder 列
    tax_price = order_data.pop("tax_price", None)
    try:
        from order_biz_kind import apply_biz_kind

        apply_biz_kind(order_data)
    except Exception:
        order_data.setdefault("biz_kind", "processing")
    if existing:
        for key, value in order_data.items():
            if key in ("remark", "is_controlled", "internal_wo_no"):
                continue
            setattr(existing, key, value)
        try:
            from order_price_service import upsert_from_order_data

            payload = dict(order_data)
            if tax_price is not None:
                payload["tax_price"] = tax_price
            upsert_from_order_data(db, payload, source="srm_sync")
        except Exception:
            pass
        return
    order_data.setdefault("is_controlled", False)
    db.add(SrmOrder(**order_data))
    try:
        from order_price_service import upsert_from_order_data

        payload = dict(order_data)
        if tax_price is not None:
            payload["tax_price"] = tax_price
        upsert_from_order_data(db, payload, source="srm_sync")
    except Exception:
        pass
    if new_orders is not None:
        new_orders.append(
            {
                "customer_id": order_data.get("customer_id"),
                "customer_name": order_data.get("customer_name"),
                "purchase_no": order_data.get("purchase_no"),
                "purchase_seq": order_data.get("purchase_seq"),
                "purchase_phase_seq": order_data.get("purchase_phase_seq"),
                "product_goods_no": order_data.get("product_goods_no"),
                "product_goods_name": order_data.get("product_goods_name"),
                "batch_pur_qty": order_data.get("batch_pur_qty"),
            }
        )
