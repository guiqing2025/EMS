from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models import OrderScan, Shipment, SrmOrder
from packing_service import create_shipment, get_order_or_404, get_scan_stats, register_scan
from schemas import (
    PackingOrderOut,
    PackingScanIn,
    PackingScanOut,
    PackingSearchOrderOut,
    ShipmentCreateIn,
    ShipmentOut,
)
from system_auth import require_system_auth

router = APIRouter(
    prefix="/api/packing",
    tags=["packing"],
    dependencies=[Depends(require_system_auth)],
)


def _order_payload(order: SrmOrder, stats: dict) -> PackingOrderOut:
    pending = stats.get("pending", 0)
    shipped = stats.get("shipped", 0)
    order_qty = float(order.batch_pur_qty or order.output_qty or 0)
    return PackingOrderOut(
        line_key=order.line_key,
        purchase_no=order.purchase_no,
        purchase_seq=order.purchase_seq,
        purchase_phase_seq=order.purchase_phase_seq,
        customer_name=order.customer_name,
        remark=order.remark,
        product_goods_no=order.product_goods_no,
        product_goods_name=order.product_goods_name,
        product_spec=order.product_spec,
        batch_pur_qty=order_qty,
        un_delivery_qty=float(order.un_delivery_qty or 0),
        expect_arrival_date=order.expect_arrival_date,
        pending_ship_qty=pending,
        shipped_local_qty=shipped,
        remain_scan_qty=max(order_qty - pending - shipped, 0) if order_qty else 0,
        is_completed=order.is_completed,
    )


@router.get("/search", response_model=List[PackingSearchOrderOut])
def search_orders(
    keyword: str = Query("", min_length=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    q = db.query(SrmOrder).filter(SrmOrder.is_completed.is_(False))
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        q = q.filter(
            (SrmOrder.purchase_no.like(like))
            | (SrmOrder.product_goods_no.like(like))
            | (SrmOrder.product_goods_name.like(like))
        )
    orders = q.order_by(SrmOrder.purchase_date.desc(), SrmOrder.id.desc()).limit(limit).all()
    stats_map = get_scan_stats(db, [o.line_key for o in orders])
    return [
        PackingSearchOrderOut(
            line_key=o.line_key,
            purchase_no=o.purchase_no,
            customer_name=o.customer_name,
            product_goods_no=o.product_goods_no,
            product_goods_name=o.product_goods_name,
            batch_pur_qty=float(o.batch_pur_qty or o.output_qty or 0),
            pending_ship_qty=stats_map.get(o.line_key, {}).get("pending", 0),
        )
        for o in orders
    ]


@router.get("/order/{line_key}", response_model=PackingOrderOut)
def get_packing_order(line_key: str, db: Session = Depends(get_db)):
    try:
        order = get_order_or_404(db, line_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    stats = get_scan_stats(db, [line_key]).get(line_key, {"pending": 0, "shipped": 0})
    return _order_payload(order, stats)


@router.post("/scan", response_model=PackingScanOut)
def scan_piece(
    payload: PackingScanIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    # 入库操作人固定为当前登录账号持有者，不采信前端随意填写
    operator = (principal.display_name or principal.username or "").strip()
    try:
        scan, stats = register_scan(
            db,
            line_key=payload.line_key,
            barcode=payload.barcode,
            code_type=payload.code_type,
            operator=operator,
        )
        db.commit()
        db.refresh(scan)
        order = get_order_or_404(db, payload.line_key)
        order_qty = float(order.batch_pur_qty or order.output_qty or 0)
        return PackingScanOut(
            id=scan.id,
            barcode=scan.barcode,
            code_type=scan.code_type,
            pending_ship_qty=stats["pending"],
            shipped_local_qty=stats["shipped"],
            order_qty=order_qty,
            message="扫码成功",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/scans/{line_key}")
def list_scans(
    line_key: str,
    status: str = Query("pending", pattern="^(pending|shipped|all)$"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(OrderScan).filter(OrderScan.line_key == line_key)
    if status != "all":
        q = q.filter(OrderScan.status == status)
    rows = q.order_by(OrderScan.id.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "barcode": row.barcode,
            "code_type": row.code_type,
            "status": row.status,
            "operator": row.operator,
            "scanned_at": row.scanned_at,
            "shipped_at": row.shipped_at,
        }
        for row in rows
    ]


@router.post("/ship", response_model=ShipmentOut)
def ship_order(
    payload: ShipmentCreateIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    if principal.role in ("floor", "packing"):
        raise HTTPException(status_code=403, detail="扫码账号无发货权限")
    try:
        shipment = create_shipment(
            db,
            line_key=payload.line_key,
            ship_date=payload.ship_date or date.today().isoformat(),
            box_count=payload.box_count or 1,
            logistics=payload.logistics or "",
            remark=payload.remark or "",
            operator=payload.operator or "",
        )
        db.commit()
        db.refresh(shipment)
        return ShipmentOut.model_validate(shipment)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/shipment/{shipment_id}", response_model=ShipmentOut)
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="发货单不存在")
    return ShipmentOut.model_validate(shipment)


def _wang123_client_from_config(token: str = ""):
    from config import load_config
    from wang123_client import Wang123Client

    cfg = (load_config().get("wang123_legacy") or {})
    return Wang123Client(
        api_base=cfg.get("api_base") or "https://zym.wang123.online",
        username=cfg.get("username") or "blue",
        password=cfg.get("password") or "blue1",
        token=token or Wang123Client.load_token(),
    )


@router.get("/legacy-wang123/captcha")
def legacy_wang123_captcha(principal=Depends(require_system_auth)):
    """代理旧站验证码（数学题）。"""
    if principal.role in ("floor", "packing"):
        raise HTTPException(status_code=403, detail="无权限")
    client = _wang123_client_from_config()
    try:
        return client.fetch_captcha()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"旧站验证码失败: {exc}") from exc


@router.post("/legacy-wang123/login")
def legacy_wang123_login(
    payload: dict,
    principal=Depends(require_system_auth),
):
    """用验证码登录旧站并缓存 token，供全量/增量同步。"""
    if principal.role in ("floor", "packing"):
        raise HTTPException(status_code=403, detail="无权限")
    code = str(payload.get("code") or "").strip()
    uuid = str(payload.get("uuid") or "").strip()
    if not code or not uuid:
        raise HTTPException(status_code=400, detail="请提供验证码 code 与 uuid")
    client = _wang123_client_from_config()
    try:
        token = client.login_with_code(code, uuid)
        return {"status": "ok", "message": "旧站登录成功", "token_len": len(token)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/legacy-wang123/sync")
def legacy_wang123_sync(
    full: bool = Query(True),
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """同步旧站已包装 → 冷表 + 订单入库（默认 shipped）。"""
    if principal.role in ("floor", "packing"):
        raise HTTPException(status_code=403, detail="无权限")
    from wang123_packing_sync import sync_packaged_from_wang123

    client = _wang123_client_from_config()
    try:
        result = sync_packaged_from_wang123(db, client, full=full, default_status="shipped")
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/legacy-wang123/stats")
def legacy_wang123_stats(db: Session = Depends(get_db), principal=Depends(require_system_auth)):
    from sqlalchemy import func
    from models import LegacyPackingScan, OrderScan

    cold = db.query(func.count(LegacyPackingScan.id)).scalar() or 0
    matched = (
        db.query(func.count(LegacyPackingScan.id))
        .filter(LegacyPackingScan.match_status == "matched")
        .scalar()
        or 0
    )
    unmatched = (
        db.query(func.count(LegacyPackingScan.id))
        .filter(LegacyPackingScan.match_status == "unmatched")
        .scalar()
        or 0
    )
    legacy_scans = (
        db.query(func.count(OrderScan.id))
        .filter(OrderScan.operator == "legacy:wang123")
        .scalar()
        or 0
    )
    return {
        "cold_total": cold,
        "matched": matched,
        "unmatched": unmatched,
        "order_scans_legacy": legacy_scans,
    }
