"""成品库存：按订单行汇总包装入库，供仓库出库。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from models import SrmOrder
from packing_service import get_scan_stats


def list_finished_goods(
    db: Session,
    *,
    customer_id: str = "",
    keyword: str = "",
    include_completed: bool = False,
    only_with_inbound: bool = False,
    limit: int = 2000,
) -> list[dict]:
    """成品库存行。

    口径（不含旧站迁移历史）：
    - 入库数 = 新系统包装扫码（pending + shipped）
    - 客户收货数 = SRM receive_qty
    - 订单结存数 = 订单数量 − 客户收货数 − 入库数
    - 待出库 = 新系统 pending（可点发货出库）
    旧站 wang123 迁入数据只留冷表/条码防重，不计入入库数与结存。
    """
    q = db.query(SrmOrder).order_by(
        SrmOrder.customer_name.asc(),
        SrmOrder.purchase_no.desc(),
        SrmOrder.line_key.asc(),
    )
    cid = (customer_id or "").strip()
    if cid:
        q = q.filter(SrmOrder.customer_id == cid)
    if not include_completed:
        q = q.filter(SrmOrder.is_completed.is_(False))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (SrmOrder.purchase_no.ilike(like))
            | (SrmOrder.product_goods_no.ilike(like))
            | (SrmOrder.product_goods_name.ilike(like))
            | (SrmOrder.customer_name.ilike(like))
        )

    # 先取订单再聚合扫码；「仅有入库」时不能先截断订单，否则会漏掉后面客户
    cap = max(1, min(int(limit or 2000), 5000))
    fetch_cap = 8000 if only_with_inbound else cap
    orders = q.limit(fetch_cap).all()
    stats_map = get_scan_stats(db, [o.line_key for o in orders])

    rows: list[dict] = []
    for order in orders:
        stats = stats_map.get(order.line_key, {"pending": 0, "shipped": 0})
        pending = int(stats.get("pending") or 0)
        shipped = int(stats.get("shipped") or 0)
        inbound = pending + shipped
        if only_with_inbound and inbound <= 0:
            continue
        order_qty = float(order.batch_pur_qty or order.output_qty or 0)
        receive_qty = float(order.receive_qty or 0)
        balance = order_qty - receive_qty - float(inbound)
        rows.append(
            {
                "line_key": order.line_key,
                "customer_id": order.customer_id or "",
                "customer_name": order.customer_name or order.customer_id or "",
                "purchase_no": order.purchase_no or "",
                "model_code": order.product_goods_no or "",
                "model_name": order.product_goods_name or "",
                "order_qty": order_qty,
                "receive_qty": receive_qty,
                "inbound_qty": inbound,
                "pending_qty": pending,
                "shipped_qty": shipped,
                "balance_qty": balance,
                "is_completed": bool(order.is_completed),
            }
        )
        if len(rows) >= cap:
            break
    return rows
