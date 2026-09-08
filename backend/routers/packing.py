from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import OrderScan, Shipment, ShipmentBox, SrmOrder
from laser_service import filter_orders_by_laser_register
from packing_service import (
    approve_shipments,
    attach_inbound_barcode_to_open_box,
    attach_scan_to_open_box,
    absorb_loose_pending_into_box,
    build_delivery_slip,
    build_delivery_slip_for_slip,
    build_pending_product_labels,
    build_product_label_for_box,
    build_product_labels,
    create_historical_ship_backfill,
    create_multi_shipment,
    create_shipment,
    delete_inbound_scan_by_barcode,
    delete_pack_box,
    get_box_trace,
    get_box_trace_by_barcode,
    get_latest_shipment,
    get_line_reconcile,
    get_order_or_404,
    get_scan_stats,
    get_shipment_record_barcodes,
    list_pack_boxes,
    list_pending_label_jobs,
    list_pending_ship_approvals,
    list_shipment_records,
    lookup_pack_box_query,
    lookup_shipment_record,
    mark_box_label_printed,
    open_pack_box,
    pack_box_barcode_hint,
    pack_box_station_state,
    register_scan,
    resume_pack_box,
    revoke_shipment,
    seal_pack_box,
)
from scan_station_policy import assert_scan_kind_allowed
from schemas import (
    PackingOrderOut,
    PackingScanIn,
    PackingScanOut,
    PackingSearchOrderOut,
    PackBoxAbsorbIn,
    PackScanDeleteIn,
    PackBoxOpenIn,
    PackBoxResumeIn,
    PackBoxSealIn,
    ShipmentApproveIn,
    ShipmentApproveOut,
    ShipmentBackfillIn,
    ShipmentBackfillOut,
    ShipmentCreateIn,
    ShipmentMultiCreateIn,
    ShipmentMultiOut,
    ShipmentOut,
    ShipmentRevokeIn,
    ShipmentRevokeOut,
)
from system_auth import (
    is_ship_approver_username,
    is_ship_operator_username,
    require_admin_or_planner,
    require_system_auth,
)

router = APIRouter(
    prefix="/api/packing",
    tags=["packing"],
    dependencies=[Depends(require_system_auth)],
)

public_router = APIRouter(
    prefix="/api/packing",
    tags=["packing-public"],
)


def _require_ship_operate(principal) -> None:
    """扫码专岗无发货；发货员白名单目前为空（dxbz001/002 仅入库/入箱）。"""
    if is_ship_operator_username(getattr(principal, "username", None)):
        return
    if principal.role in ("floor", "packing", "smt_scan"):
        raise HTTPException(status_code=403, detail="扫码账号无发货权限")


def _require_ship_pending_view(principal) -> None:
    """待审核列表：审核人 dxgc/dxgc002/WGQ、发货员、仓管/计划/管理员可看。"""
    name = getattr(principal, "username", None)
    if is_ship_approver_username(name) or is_ship_operator_username(name):
        return
    if getattr(principal, "role", None) in (
        "admin",
        "planner",
        "warehouse",
        "pmc",
        "eng_auditor",
    ):
        return
    raise HTTPException(status_code=403, detail="无待审核发货查看权限")


def _order_payload(order: SrmOrder, stats: dict) -> PackingOrderOut:
    pending = int(stats.get("pending", 0) or 0)
    awaiting = int(stats.get("awaiting", 0) or 0)
    shipped = int(stats.get("shipped", 0) or 0)
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
        remain_scan_qty=max(order_qty - pending - awaiting - shipped, 0) if order_qty else 0,
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
    orders = q.order_by(SrmOrder.purchase_date.desc(), SrmOrder.id.desc()).limit(limit * 3).all()
    # 同采购单若已有镭雕登记，只展示登记机型对应行（避免 9384/9547 串行）；
    # 用户明确搜了机型时保留命中行，避免 PDA/包装搜不到电脑列表已有的在制单
    orders = filter_orders_by_laser_register(db, orders, preserve_keyword=keyword.strip())[:limit]
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
    if principal.role == "smt_scan":
        raise HTTPException(status_code=403, detail="SMT扫码账号仅可使用 SMT 人工扫码")
    assert_scan_kind_allowed(principal, "packing")
    # 入库操作人固定为当前登录账号持有者，不采信前端随意填写
    operator = (principal.display_name or principal.username or "").strip()
    scan = None
    stats = {}
    box_info = {}
    try:
        scan, stats = register_scan(
            db,
            line_key=payload.line_key,
            barcode=payload.barcode,
            code_type=payload.code_type,
            operator=operator,
        )
        box_info = attach_scan_to_open_box(db, scan, line_key=scan.line_key)
        db.commit()
    except ValueError as exc:
        db.rollback()
        msg = str(exc)
        if "已扫过" not in msg:
            raise HTTPException(status_code=400, detail=msg) from exc
        try:
            scan, box_info = attach_inbound_barcode_to_open_box(
                db, barcode=payload.barcode, line_key=payload.line_key
            )
            stats = get_scan_stats(db, [scan.line_key]).get(
                scan.line_key, {"pending": 0, "shipped": 0}
            )
            db.commit()
        except ValueError as exc2:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc2)) from exc2
    db.refresh(scan)
    resolved_key = stats.get("line_key") or scan.line_key
    order = get_order_or_404(db, resolved_key)
    order_qty = float(order.batch_pur_qty or order.output_qty or 0)
    sealed = bool(box_info.get("sealed"))
    if sealed:
        msg = (
            f"本箱已满并封箱 {box_info.get('box_no')}（{box_info.get('qty')}片），"
            "请到入箱记录打印二维码"
        )
    else:
        msg = f"已入箱 {box_info.get('box_no')} {box_info.get('qty')}/{box_info.get('qty_target')}"
    return PackingScanOut(
        id=scan.id,
        barcode=scan.barcode,
        code_type=scan.code_type,
        pending_ship_qty=stats["pending"],
        shipped_local_qty=stats["shipped"],
        order_qty=order_qty,
        message=msg,
        line_key=resolved_key,
        purchase_no=stats.get("purchase_no") or order.purchase_no,
        product_goods_no=stats.get("product_goods_no")
        or (order.product_goods_no or ""),
        box_id=box_info.get("id"),
        box_no=box_info.get("box_no"),
        box_qty=box_info.get("qty"),
        box_qty_target=box_info.get("qty_target"),
        box_sealed=sealed,
    )


@router.post("/box/open")
def packing_box_open(
    payload: PackBoxOpenIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    assert_scan_kind_allowed(principal, "packing")
    operator = (principal.display_name or principal.username or "").strip()
    try:
        data = open_pack_box(
            db,
            line_key=payload.line_key,
            qty_target=payload.qty_target,
            operator=operator,
        )
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="无法开始记录本箱，请刷新后重试") from exc


@router.post("/box/seal")
def packing_box_seal(
    payload: PackBoxSealIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    assert_scan_kind_allowed(principal, "packing")
    operator = (principal.display_name or principal.username or "").strip()
    try:
        data = seal_pack_box(db, box_id=payload.box_id, operator=operator)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/box/resume")
def packing_box_resume(
    payload: PackBoxResumeIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    assert_scan_kind_allowed(principal, "packing")
    operator = (principal.display_name or principal.username or "").strip()
    try:
        data = resume_pack_box(db, box_id=payload.box_id, operator=operator)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/box/absorb-loose")
def packing_box_absorb_loose(
    payload: PackBoxAbsorbIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """把本单未入箱散板并入当前开着的箱。不改 register_scan。"""
    assert_scan_kind_allowed(principal, "packing")
    operator = (principal.display_name or principal.username or "").strip()
    try:
        data = absorb_loose_pending_into_box(db, box_id=payload.box_id, operator=operator)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/scan/delete")
def packing_scan_delete(
    payload: PackScanDeleteIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """扫错板码：删这一片的入库，并从箱子里拿掉。空箱才删箱。不改产线过站。"""
    assert_scan_kind_allowed(principal, "packing")
    operator = (principal.display_name or principal.username or "").strip()
    try:
        data = delete_inbound_scan_by_barcode(
            db, barcode=payload.barcode, operator=operator
        )
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/box/{box_id}")
def packing_box_delete(
    box_id: int,
    db: Session = Depends(get_db),
    principal=Depends(require_admin_or_planner),
):
    operator = (principal.display_name or principal.username or "").strip()
    try:
        data = delete_pack_box(db, box_id=box_id, operator=operator)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/box/current")
def packing_box_current(
    line_key: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    return pack_box_station_state(db, line_key)


@router.get("/boxes")
def packing_box_list(
    line_key: str = Query("", min_length=0),
    status: str = Query(""),
    available: bool = Query(False),
    scan_only: bool = Query(False),
    keyword: str = Query(""),
    limit: int = Query(300, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    items = list_pack_boxes(
        db,
        line_key=line_key,
        status=status,
        available=available,
        scan_only=scan_only,
        keyword=keyword,
        limit=limit,
    )
    hint = pack_box_barcode_hint(db, keyword) if (keyword or "").strip() else {}
    return {"items": items, **hint}


@router.get("/shipment-records")
def shipment_records_list(
    keyword: str = Query(""),
    status: str = Query(""),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """出库批次记录列表（只读）。可搜 SH-/订单/品号/板码。"""
    return list_shipment_records(db, keyword=keyword, status=status, limit=limit)


@router.get("/shipment-records/lookup")
def shipment_records_lookup(
    q: str = Query(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    """扫/输入板码或 SH 批次号，查所属批次及同批板码。"""
    try:
        return lookup_shipment_record(db, q)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/shipment-records/{shipment_id}/barcodes")
def shipment_records_barcodes(
    shipment_id: int,
    limit: int = Query(20000, ge=1, le=20000),
    db: Session = Depends(get_db),
):
    try:
        return get_shipment_record_barcodes(db, shipment_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/shipment-records/{shipment_id}/export")
def shipment_records_export(
    shipment_id: int,
    db: Session = Depends(get_db),
):
    """导出某出库批次的板码清单 XLSX。"""
    from io import BytesIO
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    try:
        data = get_shipment_record_barcodes(db, shipment_id, limit=20000)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    shipment = data.get("shipment") or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "批次板码"
    ws.append(
        [
            "批次号",
            "订单号",
            "品号",
            "品名",
            "客户",
            "出库日期",
            "本批数量",
            "出库人",
            "审核人",
        ]
    )
    ws.append(
        [
            shipment.get("shipment_no") or "",
            shipment.get("purchase_no") or "",
            shipment.get("product_goods_no") or "",
            shipment.get("product_goods_name") or "",
            shipment.get("customer_name") or "",
            shipment.get("ship_date") or "",
            shipment.get("qty") or 0,
            shipment.get("operator") or "",
            shipment.get("approved_by") or "",
        ]
    )
    ws.append([])
    ws.append(["序号", "板码/编码", "入库人", "入库时间", "出库时间", "状态"])
    for idx, row in enumerate(data.get("items") or [], start=1):
        ws.append(
            [
                idx,
                row.get("barcode") or "",
                row.get("operator") or "",
                row.get("scanned_at") or "",
                row.get("shipped_at") or "",
                row.get("status_label") or "",
            ]
        )
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    no = (shipment.get("shipment_no") or str(shipment_id)).replace("/", "-")
    filename = f"批次板码_{no}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/box-lookup")
def packing_box_lookup(
    q: str = Query(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    """PDA 查箱号：扫板码或箱号，只读。"""
    try:
        return lookup_pack_box_query(db, q)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/box-label/{box_no}")
def packing_box_label(box_no: str, db: Session = Depends(get_db)):
    try:
        return build_product_label_for_box(db, box_no)
    except ValueError as exc:
        msg = str(exc)
        code = 409 if "已打印" in msg else 404
        raise HTTPException(status_code=code, detail=msg) from exc


@router.post("/box-label/{box_no}/printed")
def packing_box_label_printed(
    box_no: str,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    operator = (principal.display_name or principal.username or "").strip()
    try:
        data = mark_box_label_printed(db, box_no, operator)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        msg = str(exc)
        code = 409 if "已打印" in msg else 404
        raise HTTPException(status_code=code, detail=msg) from exc


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


def _inbound_scan_query(
    db: Session,
    *,
    line_key: str,
    status: str = "all",
    keyword: str = "",
):
    q = db.query(OrderScan).filter(OrderScan.line_key == line_key)
    if status in ("pending", "shipped"):
        q = q.filter(OrderScan.status == status)
    kw = (keyword or "").strip()
    if kw.upper().startswith("BX-"):
        box = db.query(ShipmentBox).filter(ShipmentBox.box_no == kw).first()
        if not box:
            box = (
                db.query(ShipmentBox)
                .filter(ShipmentBox.box_no.like(f"%{kw}%"))
                .first()
            )
        if box:
            q = q.filter(OrderScan.box_id == box.id)
        else:
            q = q.filter(OrderScan.id == -1)
    elif kw:
        q = q.filter(OrderScan.barcode.like(f"%{kw}%"))
    return q


@router.get("/inbound-detail/{line_key}")
def inbound_detail(
    line_key: str,
    status: str = Query("all", pattern="^(pending|shipped|all)$"),
    keyword: str = "",
    limit: int = Query(5000, ge=1, le=20000),
    db: Session = Depends(get_db),
):
    """订单中心只读：入库完整明细（编码/状态/操作人/时间）。不改扫码写入。"""
    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    base = db.query(OrderScan).filter(OrderScan.line_key == line_key)
    pending_count = base.filter(OrderScan.status == "pending").count()
    shipped_count = base.filter(OrderScan.status == "shipped").count()
    q = _inbound_scan_query(db, line_key=line_key, status=status, keyword=keyword)
    total = q.count()
    rows = q.order_by(OrderScan.scanned_at.desc(), OrderScan.id.desc()).limit(limit).all()
    box_ids = [int(r.box_id) for r in rows if getattr(r, "box_id", None)]
    boxes = {}
    if box_ids:
        for b in db.query(ShipmentBox).filter(ShipmentBox.id.in_(set(box_ids))).all():
            boxes[b.id] = b.box_no
    return {
        "line_key": line_key,
        "purchase_no": (order.purchase_no if order else "") or "",
        "model_code": (order.product_goods_no if order else "") or "",
        "model_name": (order.product_goods_name if order else "") or "",
        "pending_count": int(pending_count),
        "shipped_count": int(shipped_count),
        "total": int(total),
        "items": [
            {
                "id": row.id,
                "barcode": row.barcode,
                "code_type": row.code_type,
                "status": row.status,
                "status_label": (
                    "待发"
                    if row.status == "pending"
                    else (
                        "待审核"
                        if row.status == "awaiting_approve"
                        else ("已出库" if row.status == "shipped" else (row.status or ""))
                    )
                ),
                "operator": row.operator,
                "scanned_at": row.scanned_at.isoformat(sep=" ", timespec="seconds") if row.scanned_at else None,
                "shipped_at": row.shipped_at.isoformat(sep=" ", timespec="seconds") if row.shipped_at else None,
                "shipment_id": row.shipment_id,
                "box_no": boxes.get(int(row.box_id)) if getattr(row, "box_id", None) else "",
            }
            for row in rows
        ],
    }


@router.get("/inbound-detail/{line_key}/export")
def inbound_detail_export(
    line_key: str,
    status: str = Query("all", pattern="^(pending|shipped|all)$"),
    keyword: str = "",
    db: Session = Depends(get_db),
):
    """导出入库编码明细 XLSX（只读）。"""
    from io import BytesIO
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    q = _inbound_scan_query(db, line_key=line_key, status=status, keyword=keyword)
    rows = q.order_by(OrderScan.scanned_at.asc(), OrderScan.id.asc()).limit(20000).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "入库明细"
    ws.append(
        [
            "订单号",
            "机型",
            "品名",
            "条码/编码",
            "码类型",
            "状态",
            "操作人",
            "入库时间",
            "出库时间",
            "发货单ID",
            "箱号",
        ]
    )
    pn = (order.purchase_no if order else "") or ""
    model = (order.product_goods_no if order else "") or ""
    name = (order.product_goods_name if order else "") or ""
    box_ids = [int(r.box_id) for r in rows if getattr(r, "box_id", None)]
    boxes = {}
    if box_ids:
        for b in db.query(ShipmentBox).filter(ShipmentBox.id.in_(set(box_ids))).all():
            boxes[b.id] = b.box_no
    for row in rows:
        st = "待发" if row.status == "pending" else ("已出库" if row.status == "shipped" else (row.status or ""))
        ws.append(
            [
                pn,
                model,
                name,
                row.barcode or "",
                row.code_type or "",
                st,
                row.operator or "",
                row.scanned_at.strftime("%Y-%m-%d %H:%M:%S") if row.scanned_at else "",
                row.shipped_at.strftime("%Y-%m-%d %H:%M:%S") if row.shipped_at else "",
                row.shipment_id or "",
                boxes.get(int(row.box_id), "") if getattr(row, "box_id", None) else "",
            ]
        )
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    safe_pn = (pn or line_key).replace("/", "-").replace("\\", "-")
    filename = f"入库明细_{safe_pn}_{model or 'all'}.xlsx"
    headers = {
        "Content-Disposition": (
            f"attachment; filename=\"inbound.xlsx\"; filename*=UTF-8''{quote(filename)}"
        ),
    }
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/ship", response_model=ShipmentOut)
def ship_order(
    payload: ShipmentCreateIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    _require_ship_operate(principal)
    try:
        shipment = create_shipment(
            db,
            line_key=payload.line_key,
            ship_date=payload.ship_date or date.today().isoformat(),
            box_count=payload.box_count or 1,
            qty_per_box=payload.qty_per_box or 0,
            qty=payload.qty,
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


@router.post("/ship-multi", response_model=ShipmentMultiOut)
def ship_multi_orders(
    payload: ShipmentMultiCreateIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """同客户多订单合并发货；每单手填数量且不得超过待发。不影响扫码入库。"""
    _require_ship_operate(principal)
    operator = (payload.operator or "").strip() or (
        principal.display_name or principal.username or ""
    ).strip()
    try:
        result = create_multi_shipment(
            db,
            customer_id=payload.customer_id,
            ship_date=payload.ship_date or date.today().isoformat(),
            lines=[x.model_dump() for x in payload.lines],
            logistics=payload.logistics or "",
            remark=payload.remark or "",
            operator=operator,
        )
        db.commit()
        return ShipmentMultiOut(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/shipment/{shipment_id}", response_model=ShipmentOut)
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="发货单不存在")
    return ShipmentOut.model_validate(shipment)


@router.get("/shipment/{shipment_id}/slip")
def get_shipment_delivery_slip(shipment_id: int, db: Session = Depends(get_db)):
    """菲利斯风格送货单打印数据（只读）。合并单会返回多行。"""
    try:
        return build_delivery_slip(db, shipment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/slip/{slip_id}")
def get_delivery_slip(slip_id: int, db: Session = Depends(get_db)):
    """按合并送货单 id 取打印数据。"""
    try:
        return build_delivery_slip_for_slip(db, slip_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/shipment/{shipment_id}/labels")
def get_shipment_product_labels(shipment_id: int, db: Session = Depends(get_db)):
    """产品标签（每箱一张）。"""
    try:
        data = build_product_labels(db, shipment_id=shipment_id)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/slip/{slip_id}/labels")
def get_slip_product_labels(slip_id: int, db: Session = Depends(get_db)):
    """合并送货单产品标签（每箱一张）。"""
    try:
        data = build_product_labels(db, slip_id=slip_id)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reconcile/{line_key}")
def reconcile_line(line_key: str, db: Session = Depends(get_db)):
    """订单行内部对账（只读，不改扫码）。"""
    try:
        return get_line_reconcile(db, line_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/shipments/latest", response_model=ShipmentOut)
def latest_shipment(
    line_key: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """查询订单行最近一次出库单（供撤销确认）。"""
    _require_ship_operate(principal)
    shipment = get_latest_shipment(db, line_key)
    if not shipment:
        raise HTTPException(status_code=404, detail="该订单没有出库记录")
    return ShipmentOut.model_validate(shipment)


@router.post("/ship/revoke", response_model=ShipmentRevokeOut)
def revoke_ship_order(
    payload: ShipmentRevokeIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """撤销出库：默认撤销该订单行最近一次；数量回到待出库。"""
    _require_ship_operate(principal)
    operator = (principal.display_name or principal.username or "").strip()
    try:
        info = revoke_shipment(
            db,
            shipment_id=payload.shipment_id,
            line_key=payload.line_key or "",
            operator=operator,
        )
        db.commit()
        if info.get("is_backfill") or int(info.get("deleted_backfill_qty") or 0) > 0:
            msg = (
                f"已撤销补录单 {info['shipment_no']}，"
                f"清除历史补录 {info.get('deleted_backfill_qty') or 0} 片"
            )
        else:
            msg = f"已撤销 {info['shipment_no']}，恢复待出库 {info['restored_qty']} 片"
        return ShipmentRevokeOut(
            id=info["id"],
            shipment_no=info["shipment_no"],
            line_key=info["line_key"],
            purchase_no=info["purchase_no"],
            qty=info["qty"],
            restored_qty=info["restored_qty"],
            ship_date=info["ship_date"],
            message=msg,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ship/pending-approvals")
def pending_ship_approvals(
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """待审核出库单列表（只读）。审核人必须能拉到，否则顶栏无法推送。"""
    _require_ship_pending_view(principal)
    return {
        "items": list_pending_ship_approvals(db, limit=limit),
        "can_approve": is_ship_approver_username(principal.username),
        "approver_usernames": ["dxgc", "dxgc002", "WGQ"],
    }


@router.get("/ship/pending-labels")
def pending_ship_labels(
    limit: int = Query(200, ge=1, le=500),
    include_labels: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """待打印产品标签（待审核发货）。dxgc/dxgc002 弹窗使用。"""
    if include_labels:
        data = build_pending_product_labels(db, limit=limit)
        db.commit()
        return data
    return list_pending_label_jobs(db, limit=limit)


@router.post("/ship/approve", response_model=ShipmentApproveOut)
def approve_ship_order(
    payload: ShipmentApproveIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """确认已发货：仅 dxgc / dxgc002 / WGQ。确认后才计入成品发货「已发货」。"""
    if not is_ship_approver_username(principal.username):
        raise HTTPException(
            status_code=403,
            detail="仅 dxgc / dxgc002 / WGQ 可确认已发货",
        )
    try:
        result = approve_shipments(
            db,
            shipment_id=payload.shipment_id,
            slip_id=payload.slip_id,
            approver=(principal.username or "").strip(),
        )
        db.commit()
        return ShipmentApproveOut(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ship/backfill", response_model=ShipmentBackfillOut)
def backfill_historical_ship(
    payload: ShipmentBackfillIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """历史发货补录：对齐上线前客户已收货。不改动生产扫码 register_scan。"""
    _require_ship_operate(principal)
    operator = (payload.operator or "").strip() or (
        principal.display_name or principal.username or ""
    ).strip()
    try:
        result = create_historical_ship_backfill(
            db,
            line_key=payload.line_key,
            add_qty=payload.add_qty,
            target_shipped_qty=payload.target_shipped_qty,
            ship_date=payload.ship_date or date.today().isoformat(),
            remark=payload.remark or "",
            operator=operator,
        )
        db.commit()
        return ShipmentBackfillOut(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    if principal.role in ("floor", "packing", "smt_scan"):
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
    if principal.role in ("floor", "packing", "smt_scan"):
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
    if principal.role in ("floor", "packing", "smt_scan"):
        raise HTTPException(status_code=403, detail="无权限")
    from wang123_packing_sync import sync_packaged_from_wang123

    client = _wang123_client_from_config()
    try:
        result = sync_packaged_from_wang123(db, client, full=full, default_status="shipped")
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/legacy-wang123/sync-smt-aoi")
def legacy_wang123_sync_smt_aoi(
    purchase_no: str = Query(..., min_length=3, description="采购订单号"),
    max_pages: int = Query(0, ge=0, le=500, description="0=按远端 total 拉全"),
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    """旧站 SMT 通过记录 → aoi_board_results（只补写，不覆盖已有 AOI，不影响扫码逻辑）。"""
    if principal.role in ("floor", "packing", "smt_scan"):
        raise HTTPException(status_code=403, detail="无权限")
    from wang123_smt_sync import sync_smt_aoi_for_purchase

    client = _wang123_client_from_config()
    try:
        result = sync_smt_aoi_for_purchase(
            db, client, purchase_no, max_pages=max_pages
        )
        return result
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@public_router.get("/box/{box_no}")
def public_box_trace(box_no: str, db: Session = Depends(get_db)):
    """扫箱码：本箱板码 + 订单/型号/出货日。内网只读，无需登录。"""
    try:
        return get_box_trace(db, box_no)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@public_router.get("/box-by-barcode")
def public_box_by_barcode(
    barcode: str = Query(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    """用板码反查所在发货箱。"""
    try:
        return get_box_trace_by_barcode(db, barcode)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
