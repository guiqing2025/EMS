import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from board_gate import check_packing_gate, norm_barcode
from models import OrderScan, Shipment, SrmOrder

SCAN_LOG_DIR = Path(__file__).parent / "data" / "scans"
SCAN_STATUS_PENDING = "pending"
SCAN_STATUS_SHIPPED = "shipped"


def detect_code_type(barcode: str) -> str:
    text = (barcode or "").strip()
    if not text:
        return "unknown"
    if text.isdigit() and len(text) >= 12:
        return "1d"
    return "qr"


def append_scan_log(record: dict) -> None:
    SCAN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    daily = SCAN_LOG_DIR / f"scans_{datetime.now().strftime('%Y%m%d')}.jsonl"
    with open(daily, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_scan_stats(
    db: Session,
    line_keys: list[str],
    *,
    exclude_legacy: bool = True,
) -> Dict[str, Dict[str, int]]:
    """按订单行统计包装扫码。

    exclude_legacy=True（默认）：不计旧站迁移（operator 以 legacy: 开头），
    避免历史数据当成「现在的入库/已发」。
    """
    if not line_keys:
        return {}
    from sqlalchemy import or_

    q = db.query(
        OrderScan.line_key,
        OrderScan.status,
        func.count(OrderScan.id),
    ).filter(OrderScan.line_key.in_(line_keys))
    if exclude_legacy:
        q = q.filter(
            or_(OrderScan.operator.is_(None), ~OrderScan.operator.like("legacy:%"))
        )
    rows = q.group_by(OrderScan.line_key, OrderScan.status).all()
    stats: Dict[str, Dict[str, int]] = {}
    for line_key, status, count in rows:
        bucket = stats.setdefault(line_key, {"pending": 0, "shipped": 0})
        bucket[status] = int(count)
    return stats


def get_order_or_404(db: Session, line_key: str) -> SrmOrder:
    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise ValueError("订单不存在")
    return order


def register_scan(
    db: Session,
    *,
    line_key: str,
    barcode: str,
    code_type: Optional[str] = None,
    operator: str = "",
) -> Tuple[OrderScan, Dict[str, int]]:
    raw = (barcode or "").strip()
    if not raw:
        raise ValueError("条码不能为空")
    if len(raw) > 128:
        raise ValueError("条码过长")

    barcode = norm_barcode(raw)
    if not barcode:
        raise ValueError("条码不能为空")

    order = get_order_or_404(db, line_key)
    if order.is_completed:
        raise ValueError("订单已结案，不能继续扫码")

    gate = check_packing_gate(db, barcode)
    if not gate.get("ok"):
        raise ValueError(gate.get("message") or "工序卡控未通过")

    existing = db.query(OrderScan).filter(OrderScan.barcode == barcode).first()
    if existing:
        if existing.line_key == line_key:
            raise ValueError("该条码已扫过")
        raise ValueError(f"该条码已属于其他订单（{existing.line_key}）")

    pending = (
        db.query(func.count(OrderScan.id))
        .filter(OrderScan.line_key == line_key, OrderScan.status == SCAN_STATUS_PENDING)
        .scalar()
        or 0
    )
    order_qty = int(order.batch_pur_qty or order.output_qty or 0)
    if order_qty > 0 and pending >= order_qty:
        raise ValueError(f"已达订单量 {order_qty}，请先发货或检查是否扫错单")

    resolved_type = (code_type or detect_code_type(barcode)).strip() or "unknown"
    scan = OrderScan(
        line_key=line_key,
        purchase_no=order.purchase_no,
        barcode=barcode,
        code_type=resolved_type,
        status=SCAN_STATUS_PENDING,
        operator=(operator or "").strip() or None,
        scanned_at=datetime.utcnow(),
    )
    db.add(scan)
    db.flush()

    stats = get_scan_stats(db, [line_key]).get(line_key, {"pending": 0, "shipped": 0})
    append_scan_log(
        {
            "event": "scan",
            "line_key": line_key,
            "purchase_no": order.purchase_no,
            "barcode": barcode,
            "code_type": resolved_type,
            "operator": operator,
            "pending_qty": stats.get("pending", 0) + 1,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return scan, {"pending": stats.get("pending", 0) + 1, "shipped": stats.get("shipped", 0)}


def _next_shipment_no(db: Session) -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"SH-{today}-"
    last = (
        db.query(Shipment)
        .filter(Shipment.shipment_no.like(f"{prefix}%"))
        .order_by(Shipment.id.desc())
        .first()
    )
    if not last:
        return f"{prefix}001"
    try:
        seq = int(last.shipment_no.rsplit("-", 1)[-1]) + 1
    except ValueError:
        seq = 1
    return f"{prefix}{seq:03d}"


def create_shipment(
    db: Session,
    *,
    line_key: str,
    ship_date: str,
    box_count: int = 1,
    logistics: str = "",
    remark: str = "",
    operator: str = "",
) -> Shipment:
    order = get_order_or_404(db, line_key)
    pending_scans = (
        db.query(OrderScan)
        .filter(OrderScan.line_key == line_key, OrderScan.status == SCAN_STATUS_PENDING)
        .order_by(OrderScan.id.asc())
        .all()
    )
    if not pending_scans:
        raise ValueError("没有待发货的扫码记录")

    qty = len(pending_scans)
    shipment = Shipment(
        shipment_no=_next_shipment_no(db),
        line_key=line_key,
        purchase_no=order.purchase_no,
        customer_name=order.customer_name,
        product_goods_no=order.product_goods_no,
        product_goods_name=order.product_goods_name,
        qty=qty,
        ship_date=ship_date,
        box_count=max(box_count, 1),
        logistics=(logistics or "").strip() or None,
        remark=(remark or "").strip() or None,
        operator=(operator or "").strip() or None,
        created_at=datetime.utcnow(),
    )
    db.add(shipment)
    db.flush()

    for scan in pending_scans:
        scan.status = SCAN_STATUS_SHIPPED
        scan.shipment_id = shipment.id
        scan.shipped_at = datetime.utcnow()

    append_scan_log(
        {
            "event": "ship",
            "shipment_no": shipment.shipment_no,
            "line_key": line_key,
            "purchase_no": order.purchase_no,
            "qty": qty,
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return shipment
