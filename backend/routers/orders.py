from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from excel_export import build_orders_xlsx, export_content_disposition
from manual_order_service import create_manual_order, list_manual_customers
from models import SrmOrder
from order_newness import NEW_ORDER_DAYS, is_new_order, new_order_date_from_str
from packing_service import get_scan_stats
from schemas import ManualOrderIn, OrderDeleteIn, OrderRemarkUpdate, SrmOrderOut, KittingOut
from ops_secrets import order_delete_password
from system_auth import AuthPrincipal, require_manual_order, require_order_delete, require_system_auth
from tooling_service import empty_tooling_summary, tooling_summaries_for_orders
from order_biz_kind import BIZ_KIND_LABELS

router = APIRouter(
    prefix="/api/orders",
    tags=["orders"],
    dependencies=[Depends(require_system_auth)],
)


def _require_order_delete_password(password: str) -> None:
    if (password or "").strip() != order_delete_password():
        raise HTTPException(status_code=403, detail="操作密码错误")


def _apply_filters(
    db: Session,
    q,
    keyword: str = "",
    completed: str = "all",
    srm_status: str = "",
    date_from: str = "",
    date_to: str = "",
    receive_filter: str = "all",
    customer_id: str = "",
    controlled: str = "all",
    new_only: bool = False,
    biz_kind: str = "processing",
):
    if customer_id:
        from config import expand_customer_ids_for_filter

        cids = expand_customer_ids_for_filter(customer_id)
        if len(cids) <= 1:
            q = q.filter(SrmOrder.customer_id == (cids[0] if cids else customer_id))
        else:
            q = q.filter(SrmOrder.customer_id.in_(cids))
    if biz_kind in ("processing", "expense"):
        q = q.filter(SrmOrder.biz_kind == biz_kind)
    if new_only:
        # 近 N 天下单：字符串日期 YYYY-MM-DD 可直接比较
        q = q.filter(
            SrmOrder.purchase_date.isnot(None),
            SrmOrder.purchase_date != "",
            SrmOrder.purchase_date >= new_order_date_from_str(),
        )
    if completed == "incomplete":
        q = q.filter(SrmOrder.is_completed.is_(False))
    elif completed == "completed":
        q = q.filter(SrmOrder.is_completed.is_(True))

    if srm_status:
        q = q.filter(SrmOrder.srm_status_name == srm_status)

    if date_from:
        q = q.filter(SrmOrder.purchase_date >= date_from)
    if date_to:
        q = q.filter(SrmOrder.purchase_date <= date_to)

    if receive_filter == "unreceived":
        q = q.filter(SrmOrder.un_receive_qty > 0)
    elif receive_filter == "received":
        q = q.filter(SrmOrder.receive_qty > 0)
    elif receive_filter == "undelivered":
        q = q.filter(SrmOrder.delivery_qty <= 0)

    if controlled == "yes":
        from material_control_service import _order_has_control_exists

        exists_q = _order_has_control_exists(db, include_draft=True)
        q = q.filter((SrmOrder.is_controlled.is_(True)) | exists_q)
    elif controlled == "no":
        from material_control_service import _order_has_control_exists

        exists_q = _order_has_control_exists(db, include_draft=True)
        q = q.filter(SrmOrder.is_controlled.is_(False), ~exists_q)

    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (SrmOrder.purchase_no.like(like))
            | (SrmOrder.product_goods_no.like(like))
            | (SrmOrder.product_goods_name.like(like))
            | (SrmOrder.product_spec.like(like))
        )
    return q


def _serialize_orders(
    orders: list[SrmOrder],
    db: Session,
    *,
    include_device_stats: bool = True,
) -> list[SrmOrderOut]:
    from config import get_engineering_customer_by_srm_id
    from engineering_service import batch_live_order_kit_summaries, normalize_code
    from material_control_service import control_summary_by_purchase_model
    from models import ProductionMasterPlan
    from process_scan_service import counts_by_purchase_model as process_counts_by_purchase_model

    # 入库/发货数量始终带上（扫码展示依赖）；AOI/ICT/工序/工装可按需跳过以减轻列表高峰锁库
    from datetime import date as _date

    from packing_service import shipped_qty_by_ship_date

    stats_map = get_scan_stats(db, [o.line_key for o in orders])
    today_ship_map = shipped_qty_by_ship_date(
        db, [o.line_key for o in orders], ship_date=_date.today().isoformat()
    )
    ctrl_tree = control_summary_by_purchase_model(db, [o.purchase_no for o in orders])

    # 列表齐套：BOM×库存现算（只读，不写订单表，不影响扫码）
    live_kit_map: dict[str, dict] = {}
    try:
        live_kit_map = batch_live_order_kit_summaries(db, orders)
    except Exception:
        live_kit_map = {}

    purchase_nos = sorted({(o.purchase_no or "").strip() for o in orders if (o.purchase_no or "").strip()})
    aoi_map: dict[tuple[str, str], int] = {}
    pre_oven_map: dict[tuple[str, str], int] = {}
    ict_map: dict[tuple[str, str], int] = {}
    process_map: dict[tuple[str, str], dict[str, int]] = {}
    if include_device_stats and purchase_nos:
        from device_board_archive import counts_by_purchase_model
        from pre_oven_aoi_sync import counts_by_purchase_model as pre_oven_counts

        # 按采购单+机型，避免同 PO 多行共享整单数量
        aoi_map = counts_by_purchase_model(db, purchase_nos, kind="aoi")
        try:
            pre_oven_map = pre_oven_counts(db, purchase_nos)
        except Exception:
            db.rollback()
            pre_oven_map = {}
        ict_map = counts_by_purchase_model(db, purchase_nos, kind="ict")
        process_map = process_counts_by_purchase_model(db, purchase_nos)

    # 计划状态：按 line_key 是否已在「生产主计划」
    line_keys = [o.line_key for o in orders if (o.line_key or "").strip()]
    in_plan_keys: set[str] = set()
    if line_keys:
        planned_rows = (
            db.query(ProductionMasterPlan.line_key)
            .filter(
                ProductionMasterPlan.line_key.in_(line_keys),
                ProductionMasterPlan.line_key.isnot(None),
                ProductionMasterPlan.line_key != "",
            )
            .distinct()
            .all()
        )
        in_plan_keys = {(r[0] or "").strip() for r in planned_rows if (r[0] or "").strip()}

    eng_cache: dict[str, Optional[dict]] = {}
    tooling_pairs: list[tuple[Optional[str], Optional[str]]] = []
    order_ics: list[Optional[str]] = []
    for order in orders:
        cid = order.customer_id or ""
        if cid not in eng_cache:
            eng_cache[cid] = get_engineering_customer_by_srm_id(cid)
        eng = eng_cache[cid]
        ic = eng.get("internal_code") if eng else None
        order_ics.append(ic)
        if include_device_stats:
            tooling_pairs.append((ic, order.product_goods_no))
    tooling_map = tooling_summaries_for_orders(db, tooling_pairs) if include_device_stats else {}
    empty_tooling = empty_tooling_summary()

    result = []
    for order, ic in zip(orders, order_ics):
        stats = stats_map.get(order.line_key, {"pending": 0, "awaiting": 0, "shipped": 0})
        payload = SrmOrderOut.model_validate(order)
        pending = int(stats.get("pending", 0) or 0)
        awaiting = int(stats.get("awaiting", 0) or 0)
        shipped = int(stats.get("shipped", 0) or 0)
        payload.pending_ship_qty = pending
        payload.shipped_local_qty = shipped
        payload.shipped_today_qty = int(today_ship_map.get(order.line_key, 0) or 0)
        payload.awaiting_ship_qty = awaiting
        # 未入库 = 未收 − 入库（入库=pending+awaiting+shipped）；已结案未收按 0
        inbound = pending + awaiting + shipped
        un_recv = 0.0 if order.is_completed else float(order.un_receive_qty or 0)
        payload.stock_balance_qty = int(round(un_recv - inbound))
        pn_key = (order.purchase_no or "").strip()
        model_norm = normalize_code(order.product_goods_no)
        line_key = (pn_key, model_norm)
        payload.aoi_test_qty = aoi_map.get(line_key, 0)
        payload.pre_oven_aoi_qty = pre_oven_map.get(line_key, 0)
        payload.ict_test_qty = ict_map.get(line_key, 0)
        ps = process_map.get(line_key) or {}
        payload.plugin_qty = int(ps.get("plugin") or 0)
        payload.post_solder_qty = int(ps.get("post_solder") or 0)
        payload.coating_qty = int(ps.get("coating") or 0)
        pn = pn_key
        info = (ctrl_tree.get(pn) or {}).get(model_norm) or {}
        payload.control_nos = info.get("active_nos") or []
        payload.control_draft_nos = info.get("draft_nos") or []
        # 以机型命中为准（避免同 PO 其它机型被整单打标）
        payload.is_controlled = bool(payload.control_nos)
        payload.has_control = bool(payload.control_nos or payload.control_draft_nos)
        # 齐套：BOM×库存现算（只读）；失败时回退订单存值
        live = live_kit_map.get(order.line_key) or {}
        if live:
            payload.material_status = live.get("material_status") or order.material_status
            payload.collected_sets_qty = float(live.get("collected_sets_qty") or 0)
            payload.customer_kit_status = live.get("customer_kit_status") or "na"
            payload.customer_kit_status_label = live.get("customer_kit_status_label") or "—"
        else:
            from customer_kitting import CUSTOMER_KIT_LABELS, compute_customer_kit_status

            material_status = order.material_status
            payload.material_status = material_status
            order_qty = order.batch_pur_qty or order.output_qty or 0
            kit_status = compute_customer_kit_status(
                order.collected_sets_qty,
                order_qty,
                order.customer_id,
                material_status,
                delivery_qty=getattr(order, "delivery_qty", None),
                un_delivery_qty=getattr(order, "un_delivery_qty", None),
                receive_qty=getattr(order, "receive_qty", None),
                is_completed=bool(getattr(order, "is_completed", False)),
            )
            payload.customer_kit_status = kit_status
            payload.customer_kit_status_label = CUSTOMER_KIT_LABELS.get(kit_status, "—")
        if ic and order.product_goods_no:
            tooling = tooling_map.get(
                ((ic or "").strip().upper(), normalize_code(order.product_goods_no)),
                empty_tooling,
            )
        else:
            tooling = empty_tooling
        payload.tooling_registered_count = tooling["tooling_registered_count"]
        payload.tooling_complete = tooling["tooling_complete"]
        payload.tooling_status = tooling["tooling_status"]
        payload.tooling_status_label = tooling["tooling_status_label"]
        payload.is_new_order = is_new_order(order.purchase_date)
        kind = (getattr(order, "biz_kind", None) or "processing").strip() or "processing"
        payload.biz_kind = kind
        payload.biz_kind_label = BIZ_KIND_LABELS.get(kind, kind)
        in_plan = (order.line_key or "").strip() in in_plan_keys
        payload.in_plan = in_plan
        payload.plan_status = "done" if in_plan else "pending"
        payload.plan_status_label = "已转计划" if in_plan else "待转计划"
        result.append(payload)
    return result


@router.get("/new-orders")
def list_new_orders(
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """近 3 个自然日下单的订单（弹窗列表用）。"""
    date_from = new_order_date_from_str()
    q = (
        db.query(SrmOrder)
        .filter(
            SrmOrder.purchase_date.isnot(None),
            SrmOrder.purchase_date != "",
            SrmOrder.purchase_date >= date_from,
        )
        .order_by(SrmOrder.purchase_date.desc(), SrmOrder.id.desc())
    )
    total = q.count()
    rows = q.limit(limit).all()
    return {
        "days": NEW_ORDER_DAYS,
        "date_from": date_from,
        "count": total,
        "items": _serialize_orders(rows, db),
    }


@router.get("/status-options")
def get_status_options(customer_id: str = "", db: Session = Depends(get_db)):
    q = db.query(SrmOrder.srm_status_name, func.count(SrmOrder.id))
    if customer_id:
        from config import expand_customer_ids_for_filter

        cids = expand_customer_ids_for_filter(customer_id)
        if len(cids) <= 1:
            q = q.filter(SrmOrder.customer_id == (cids[0] if cids else customer_id))
        else:
            q = q.filter(SrmOrder.customer_id.in_(cids))
    rows = (
        q.filter(SrmOrder.srm_status_name.isnot(None), SrmOrder.srm_status_name != "")
        .group_by(SrmOrder.srm_status_name)
        .order_by(func.count(SrmOrder.id).desc())
        .all()
    )
    return [{"name": name, "count": count} for name, count in rows]


@router.get("/manual-customers")
def get_manual_customers(db: Session = Depends(get_db)):
    return list_manual_customers(db)


@router.post("/manual", response_model=SrmOrderOut)
def create_manual_order_api(
    payload: ManualOrderIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_manual_order),
):
    try:
        order = create_manual_order(db, payload.model_dump())
        db.commit()
        db.refresh(order)
        return _serialize_orders([order], db)[0]
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{line_key}/kitting", response_model=KittingOut)
def get_order_kitting_detail(line_key: str, db: Session = Depends(get_db)):
    """订单齐套明细（BOM×库存现算，只读展示；不涉及扫码卡控）。"""
    from engineering_service import order_kitting

    try:
        result = order_kitting(db, line_key)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{line_key}/remark", response_model=SrmOrderOut)
def update_order_remark(
    line_key: str,
    payload: OrderRemarkUpdate,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    text = (payload.remark or "").strip()
    order.remark = text or None
    db.commit()
    db.refresh(order)
    return _serialize_orders([order], db)[0]


@router.get("/hub-inbox")
def order_hub_inbox(
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """与我相关的订单下一步（只读聚合，不扫盘）。"""
    from order_hub_service import build_order_hub, role_matches_hint

    rows = (
        db.query(SrmOrder)
        .filter(SrmOrder.is_completed.is_(False))
        .order_by(SrmOrder.expect_arrival_date.asc(), SrmOrder.id.desc())
        .limit(min(120, limit * 3))
        .all()
    )
    if not rows:
        return {"items": [], "count": 0, "checked_at": datetime.utcnow().isoformat()}
    payloads = _serialize_orders(rows, db, include_device_stats=True)
    by_key = {p.line_key: p for p in payloads}
    items = []
    for order in rows:
        payload = by_key.get(order.line_key)
        if not payload:
            continue
        try:
            hub = build_order_hub(db, order.line_key, payload)
        except Exception:
            continue
        ns = hub.get("next_step") or {}
        if not role_matches_hint(principal.role or "", principal.username or "", ns.get("role_hint") or ""):
            continue
        items.append(
            {
                "line_key": order.line_key,
                "purchase_no": order.purchase_no,
                "product_goods_no": order.product_goods_no,
                "customer_name": order.customer_name,
                "expect_arrival_date": order.expect_arrival_date,
                "next_step": ns,
            }
        )
        if len(items) >= limit:
            break
    return {"items": items, "count": len(items), "checked_at": datetime.utcnow().isoformat()}


@router.get("/{line_key}/hub")
def order_hub(
    line_key: str,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """订单工作台只读聚合。"""
    from order_hub_service import build_order_hub

    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    payload = _serialize_orders([order], db, include_device_stats=True)[0]
    try:
        return build_order_hub(db, line_key, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{line_key}/hub/bom-export")
def order_hub_bom_export(
    line_key: str,
    mount_type: str = Query("", max_length=16),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """工作台导出 BOM：mount_type 空=总BOM；SMT/DIP=仅筛选行。只读，不影响扫码。"""
    from order_hub_service import export_order_hub_bom

    _ = principal
    try:
        content, disposition = export_order_hub_bom(db, line_key, mount_type=mount_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )


@router.post("/{line_key}/nudge")
def order_nudge(
    line_key: str,
    body: dict | None = None,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """单内催办（写审计日志，不影响扫码）。"""
    from ops_audit_service import write_audit
    from order_hub_service import list_nudges

    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    data = body or {}
    message = str(data.get("message") or "请尽快处理该订单下一步").strip()[:200]
    write_audit(
        db,
        action="order_nudge",
        actor=principal.display_name or principal.username or "",
        target_type="srm_order",
        target_id=line_key,
        detail={
            "message": message,
            "purchase_no": order.purchase_no,
            "product_goods_no": order.product_goods_no,
        },
    )
    db.commit()
    return {"ok": True, "nudges": list_nudges(db, line_key, limit=10)}


@router.post("/{line_key}/delete")
def delete_order(
    line_key: str,
    payload: OrderDeleteIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_order_delete),
):
    """删除在制订单（需操作密码）。先缓存单价再删除，与同步清理口径一致。"""
    _ = principal
    _require_order_delete_password(payload.password)
    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    purchase_no = order.purchase_no or ""
    product_goods_no = order.product_goods_no or ""
    try:
        from order_price_service import upsert_from_order

        upsert_from_order(db, order, source="manual_delete_keep_price")
        db.delete(order)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {exc}") from exc
    return {
        "ok": True,
        "line_key": line_key,
        "purchase_no": purchase_no,
        "product_goods_no": product_goods_no,
        "message": "订单已删除",
    }


@router.get("", response_model=list[SrmOrderOut])
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    keyword: str = "",
    completed: str = Query("incomplete", pattern="^(all|incomplete|completed)$"),
    srm_status: str = "",
    date_from: str = "",
    date_to: str = "",
    receive_filter: str = Query("all", pattern="^(all|unreceived|received|undelivered)$"),
    customer_id: str = "",
    controlled: str = Query("all", pattern="^(all|yes|no)$"),
    incomplete_only: bool = False,
    new_only: bool = False,
    biz_kind: str = Query("processing", pattern="^(all|processing|expense)$"),
    include_device_stats: bool = Query(
        True,
        description="是否附带 AOI/ICT/工序/工装汇总；静默刷新可关以减轻库压，不影响扫码接口",
    ),
    db: Session = Depends(get_db),
):
    if incomplete_only:
        completed = "incomplete"
    q = _apply_filters(
        db,
        db.query(SrmOrder),
        keyword,
        completed,
        srm_status,
        date_from,
        date_to,
        receive_filter,
        customer_id,
        controlled,
        new_only=new_only,
        biz_kind=biz_kind,
    )
    orders = (
        q.order_by(SrmOrder.purchase_date.desc(), SrmOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return _serialize_orders(orders, db, include_device_stats=include_device_stats)


@router.get("/count")
def count_orders(
    keyword: str = "",
    completed: str = Query("incomplete", pattern="^(all|incomplete|completed)$"),
    srm_status: str = "",
    date_from: str = "",
    date_to: str = "",
    receive_filter: str = Query("all", pattern="^(all|unreceived|received|undelivered)$"),
    customer_id: str = "",
    controlled: str = Query("all", pattern="^(all|yes|no)$"),
    incomplete_only: bool = False,
    new_only: bool = False,
    biz_kind: str = Query("processing", pattern="^(all|processing|expense)$"),
    db: Session = Depends(get_db),
):
    if incomplete_only:
        completed = "incomplete"
    q = _apply_filters(
        db,
        db.query(SrmOrder),
        keyword,
        completed,
        srm_status,
        date_from,
        date_to,
        receive_filter,
        customer_id,
        controlled,
        new_only=new_only,
        biz_kind=biz_kind,
    )
    return {"total": q.count()}


def _filter_params(
    keyword: str = "",
    completed: str = "all",
    srm_status: str = "",
    date_from: str = "",
    date_to: str = "",
    receive_filter: str = "all",
    customer_id: str = "",
    controlled: str = "all",
    incomplete_only: bool = False,
    new_only: bool = False,
    biz_kind: str = "processing",
):
    if incomplete_only:
        completed = "incomplete"
    return (
        keyword,
        completed,
        srm_status,
        date_from,
        date_to,
        receive_filter,
        customer_id,
        controlled,
        new_only,
        biz_kind,
    )


@router.get("/export")
def export_orders(
    keyword: str = "",
    completed: str = Query("incomplete", pattern="^(all|incomplete|completed)$"),
    srm_status: str = "",
    date_from: str = "",
    date_to: str = "",
    receive_filter: str = Query("all", pattern="^(all|unreceived|received|undelivered)$"),
    customer_id: str = "",
    controlled: str = Query("all", pattern="^(all|yes|no)$"),
    incomplete_only: bool = False,
    new_only: bool = False,
    biz_kind: str = Query("processing", pattern="^(all|processing|expense)$"),
    db: Session = Depends(get_db),
):
    (
        keyword,
        completed,
        srm_status,
        date_from,
        date_to,
        receive_filter,
        customer_id,
        controlled,
        new_only,
        biz_kind,
    ) = _filter_params(
        keyword,
        completed,
        srm_status,
        date_from,
        date_to,
        receive_filter,
        customer_id,
        controlled,
        incomplete_only,
        new_only,
        biz_kind,
    )
    q = _apply_filters(
        db,
        db.query(SrmOrder),
        keyword,
        completed,
        srm_status,
        date_from,
        date_to,
        receive_filter,
        customer_id,
        controlled,
        new_only=new_only,
        biz_kind=biz_kind,
    )
    orders = q.order_by(SrmOrder.purchase_date.desc(), SrmOrder.id.desc()).all()
    content = build_orders_xlsx(orders)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": export_content_disposition()},
    )
