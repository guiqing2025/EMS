"""销售订单流程链：按流程图聚合进度 + 一键下推下一步。"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from models import (
    ArReceivableStub,
    DeliveryNote,
    ErpSalesOrder,
    OutsourceOrder,
    OutsourcePlan,
    OutsourcePlanLine,
    PresalesInquiry,
    ProductionOrder,
    ProductionPlan,
    ProductionPlanLine,
    PurchaseOrder,
    PurchasePlan,
    PurchasePlanLine,
    QuoteOrder,
    SalesIssue,
)
from outsource_service import create_ww_from_plan
from planning_service import (
    generate_mrp,
    set_outsource_plan_status,
    set_production_plan_status,
    set_purchase_plan_status,
)
from production_service import create_mo_from_plan
from purchase_service import create_po_from_plan
from sales_service import get_sales_order, set_sales_order_status
from shipping_service import (
    confirm_delivery,
    create_delivery_from_issue,
    create_issue_from_so,
    post_issue,
)


def _step(
    key: str,
    title: str,
    *,
    status: str,
    docs: list[dict] | None = None,
    hint: str = "",
) -> dict:
    return {
        "key": key,
        "title": title,
        "status": status,
        "docs": docs or [],
        "hint": hint,
    }


def _action(code: str, label: str, **extra: Any) -> dict:
    out = {"code": code, "label": label}
    out.update(extra)
    return out


def _plans_for_so(db: Session, so_id: int) -> dict[str, list[Any]]:
    pur_ids = {
        r[0]
        for r in db.query(PurchasePlanLine.plan_id).filter(PurchasePlanLine.source_so_id == so_id).distinct().all()
    }
    prod_ids = {
        r[0]
        for r in db.query(ProductionPlanLine.plan_id)
        .filter(ProductionPlanLine.source_so_id == so_id)
        .distinct()
        .all()
    }
    outs_ids = {
        r[0]
        for r in db.query(OutsourcePlanLine.plan_id).filter(OutsourcePlanLine.source_so_id == so_id).distinct().all()
    }
    return {
        "purchase": list(db.query(PurchasePlan).filter(PurchasePlan.id.in_(list(pur_ids))).all()) if pur_ids else [],
        "production": list(db.query(ProductionPlan).filter(ProductionPlan.id.in_(list(prod_ids))).all())
        if prod_ids
        else [],
        "outsource": list(db.query(OutsourcePlan).filter(OutsourcePlan.id.in_(list(outs_ids))).all())
        if outs_ids
        else [],
    }


def _ar_for_deliveries(db: Session, deliveries: list[DeliveryNote]) -> list:
    if not deliveries:
        return []
    deli_ids = [d.id for d in deliveries]
    rows = (
        db.query(ArReceivableStub)
        .filter(ArReceivableStub.source_type.in_(("delivery_note", "delivery")), ArReceivableStub.source_id.in_(deli_ids))
        .all()
    )
    if rows:
        return rows
    nos = [d.delivery_no for d in deliveries if d.delivery_no]
    if nos:
        return db.query(ArReceivableStub).filter(ArReceivableStub.source_no.in_(nos)).all()
    return []


def get_flow_chain(db: Session, so_id: int) -> dict:
    so, lines = get_sales_order(db, so_id)
    qty = sum(float(ln.qty or 0) for ln in lines)
    shipped = sum(float(ln.shipped_qty or 0) for ln in lines)
    bom_bound = all(bool(ln.bom_model_id) for ln in lines) if lines else False
    any_bom = any(bool(ln.bom_model_id) for ln in lines)

    presales_docs: list[dict] = []
    if so.inquiry_id:
        inq = db.query(PresalesInquiry).filter(PresalesInquiry.id == so.inquiry_id).first()
        if inq:
            presales_docs.append(
                {
                    "kind": "inquiry",
                    "id": inq.id,
                    "no": getattr(inq, "inquiry_no", None) or str(inq.id),
                    "status": inq.status,
                }
            )
    if so.quote_id:
        qrow = db.query(QuoteOrder).filter(QuoteOrder.id == so.quote_id).first()
        if qrow:
            quote_no = getattr(qrow, "quote_no", None) or str(qrow.id)
            presales_docs.append({"kind": "quote", "id": qrow.id, "no": quote_no, "status": qrow.status})
    ps_status = "done" if (so.inquiry_id or so.quote_id) else "skipped"

    so_docs = [{"kind": "sales_order", "id": so.id, "no": so.so_no, "status": so.status}]
    if so.status == "draft":
        so_status = "active"
    elif so.status == "confirmed" and so.require_bom and not bom_bound:
        so_status = "active"
    elif so.status in ("confirmed", "planning", "executing", "partial_shipped", "done", "closed"):
        so_status = "done"
    else:
        so_status = "active"

    plans = _plans_for_so(db, so.id)
    has_any_plan = bool(plans["purchase"] or plans["production"] or plans["outsource"])
    plan_docs: list[dict] = []
    for kind, rows in plans.items():
        for p in rows:
            plan_docs.append({"kind": f"{kind}_plan", "id": p.id, "no": p.plan_no, "status": p.status})
    if not has_any_plan:
        mrp_status = "active" if so.status in ("confirmed", "planning", "executing") else "pending"
    else:
        draftish = [p for rows in plans.values() for p in rows if p.status == "draft"]
        mrp_status = "active" if draftish else "done"

    po_rows: list[PurchaseOrder] = []
    if plans["purchase"]:
        pids = [p.id for p in plans["purchase"]]
        po_rows = (
            db.query(PurchaseOrder)
            .filter(PurchaseOrder.source_plan_id.in_(pids), PurchaseOrder.status != "void")
            .all()
        )
    mo_rows = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.source_so_id == so.id, ProductionOrder.status != "void")
        .all()
    )
    ww_rows: list[OutsourceOrder] = []
    if plans["outsource"]:
        opids = [p.id for p in plans["outsource"]]
        ww_rows = (
            db.query(OutsourceOrder)
            .filter(OutsourceOrder.source_plan_id.in_(opids), OutsourceOrder.status != "void")
            .all()
        )
    exec_docs = (
        [{"kind": "purchase_order", "id": r.id, "no": r.po_no, "status": r.status} for r in po_rows]
        + [{"kind": "production_order", "id": r.id, "no": r.mo_no, "status": r.status} for r in mo_rows]
        + [{"kind": "outsource_order", "id": r.id, "no": r.ww_no, "status": r.status} for r in ww_rows]
    )
    need_exec = bool(plans["purchase"] or plans["production"] or plans["outsource"])
    plans_ready = has_any_plan and all(
        p.status in ("confirmed", "released") for rows in plans.values() for p in rows
    )
    if not need_exec:
        exec_status = "skipped" if mrp_status == "done" else "pending"
    elif not exec_docs:
        exec_status = "active" if plans_ready or mrp_status == "done" else "pending"
    else:
        exec_status = "done"

    issues = db.query(SalesIssue).filter(SalesIssue.so_id == so.id, SalesIssue.status != "void").all()
    deliveries = db.query(DeliveryNote).filter(DeliveryNote.so_id == so.id, DeliveryNote.status != "void").all()
    ship_docs = (
        [{"kind": "sales_issue", "id": r.id, "no": r.issue_no, "status": r.status} for r in issues]
        + [{"kind": "delivery", "id": r.id, "no": r.delivery_no, "status": r.status} for r in deliveries]
    )
    if float(shipped) + 1e-6 >= float(qty) > 0 and any(d.status == "confirmed" for d in deliveries):
        ship_status = "done"
    elif not issues:
        if so.status in ("planning", "executing", "partial_shipped") or (mrp_status == "done" and so.status != "draft"):
            ship_status = "active"
        else:
            ship_status = "pending"
    elif any(i.status == "draft" for i in issues):
        ship_status = "active"
    elif any(i.status == "posted" for i in issues) and not deliveries:
        ship_status = "active"
    elif deliveries and not any(d.status == "confirmed" for d in deliveries):
        ship_status = "active"
    elif float(shipped) + 1e-6 < float(qty):
        ship_status = "active"
    else:
        ship_status = "done"

    ar_rows = _ar_for_deliveries(db, deliveries)
    ar_docs = [
        {
            "kind": "ar",
            "id": r.id,
            "no": getattr(r, "stub_no", None) or getattr(r, "ar_no", None) or str(r.id),
            "status": getattr(r, "status", "open") or "open",
        }
        for r in ar_rows
    ]
    ar_status = "done" if ar_docs else ("active" if any(d.status == "confirmed" for d in deliveries) else "pending")

    steps = [
        _step("presales", "售前询价/报价", status=ps_status, docs=presales_docs, hint="无来源则可跳过"),
        _step(
            "sales_order",
            "销售订单确认+BOM",
            status=so_status,
            docs=so_docs,
            hint=f"BOM={'齐全' if bom_bound else ('部分' if any_bom else '未绑')}",
        ),
        _step("mrp", "MPS/MRP→三类计划", status=mrp_status, docs=plan_docs),
        _step("execute", "采购/生产/委外执行", status=exec_status, docs=exec_docs),
        _step("shipping", "销售出库→发货", status=ship_status, docs=ship_docs, hint=f"出货 {shipped:g}/{qty:g}"),
        _step("finance_ar", "应收账款", status=ar_status, docs=ar_docs),
    ]

    next_actions = _compute_next_actions(
        so=so,
        bom_bound=bom_bound,
        plans=plans,
        po_rows=po_rows,
        mo_rows=mo_rows,
        ww_rows=ww_rows,
        issues=issues,
        deliveries=deliveries,
        ar_docs=ar_docs,
    )

    return {
        "so_id": so.id,
        "so_no": so.so_no,
        "customer_name": so.customer_name,
        "status": so.status,
        "qty": qty,
        "shipped_qty": shipped,
        "steps": steps,
        "next_actions": next_actions,
        "pmc_hint": "；".join(a["label"] for a in next_actions) if next_actions else "流程已完成或待人工处理",
    }


def _compute_next_actions(
    *,
    so: ErpSalesOrder,
    bom_bound: bool,
    plans: dict,
    po_rows: list,
    mo_rows: list,
    ww_rows: list,
    issues: list,
    deliveries: list,
    ar_docs: list,
) -> list[dict]:
    actions: list[dict] = []
    if so.status == "draft":
        return [_action("confirm_so", "确认销售订单")]
    if so.status == "void":
        return []

    if so.require_bom and not bom_bound:
        return [_action("hint_bind_bom", "请先在销售订单行绑定工程 BOM", navigate="/sales/orders")]

    has_plan = bool(plans["purchase"] or plans["production"] or plans["outsource"])
    if so.status == "confirmed" and not has_plan:
        return [_action("mrp", "跑 MRP 生成三类计划")]

    draft_plans = [p for rows in plans.values() for p in rows if p.status == "draft"]
    if draft_plans:
        return [_action("confirm_plans", "确认三类计划")]

    if plans["purchase"] and not po_rows:
        ready = [p for p in plans["purchase"] if p.status in ("confirmed", "released")]
        if ready:
            actions.append(_action("push_purchase", "下推采购单", plan_id=ready[0].id))
    if plans["production"] and not mo_rows:
        ready = [p for p in plans["production"] if p.status in ("confirmed", "released")]
        if ready:
            actions.append(_action("push_production", "下推生产单", plan_id=ready[0].id))
    if plans["outsource"] and not ww_rows:
        ready = [p for p in plans["outsource"] if p.status in ("confirmed", "released")]
        if ready:
            actions.append(_action("push_outsource", "下推委外单", plan_id=ready[0].id))
    if len(actions) > 1:
        actions.insert(0, _action("push_execute", "一键下推三线执行单"))
    if actions:
        return actions

    if not issues:
        if so.status in ("confirmed", "planning", "executing", "partial_shipped"):
            return [_action("issue_from_so", "下推销售出库单")]
        return []

    draft_issues = [i for i in issues if i.status == "draft"]
    if draft_issues:
        return [_action("post_issue", "过账销售出库", issue_id=draft_issues[0].id)]

    posted = [i for i in issues if i.status == "posted"]
    if posted and not deliveries:
        return [_action("delivery_from_issue", "生成发货单", issue_id=posted[0].id)]

    open_deli = [d for d in deliveries if d.status != "confirmed"]
    if open_deli:
        return [_action("confirm_delivery", "确认发货→应收", delivery_id=open_deli[0].id)]

    return []


def push_flow_step(
    db: Session,
    so_id: int,
    step: str,
    *,
    user: str,
    plan_id: Optional[int] = None,
    issue_id: Optional[int] = None,
    delivery_id: Optional[int] = None,
    supplier_name: str = "",
) -> dict:
    step = (step or "").strip()
    so, _lines = get_sales_order(db, so_id)
    result: dict[str, Any] = {"step": step, "ok": True}

    if step == "confirm_so":
        set_sales_order_status(db, so_id, "confirmed", user=user)
        result["message"] = "销售订单已确认"

    elif step == "mrp":
        if so.status == "draft":
            set_sales_order_status(db, so_id, "confirmed", user=user)
        gen = generate_mrp(db, so_ids=[so_id], advance_status=True, user=user)
        result["message"] = "已生成三类计划"
        result["mrp"] = {
            "run": gen.get("run"),
            "purchase_plan": gen.get("purchase_plan"),
            "production_plan": gen.get("production_plan"),
            "outsource_plan": gen.get("outsource_plan"),
        }

    elif step == "confirm_plans":
        plans = _plans_for_so(db, so_id)
        n = 0
        for p in plans["purchase"]:
            if p.status == "draft":
                set_purchase_plan_status(db, p.id, "confirmed")
                n += 1
        for p in plans["production"]:
            if p.status == "draft":
                set_production_plan_status(db, p.id, "confirmed")
                n += 1
        for p in plans["outsource"]:
            if p.status == "draft":
                set_outsource_plan_status(db, p.id, "confirmed")
                n += 1
        if n == 0:
            raise ValueError("没有可确认的草案计划")
        result["message"] = f"已确认 {n} 张计划"

    elif step == "push_purchase":
        plans = _plans_for_so(db, so_id)
        pid = plan_id or (plans["purchase"][0].id if plans["purchase"] else 0)
        if not pid:
            raise ValueError("无采购计划可下推")
        po = create_po_from_plan(db, pid, supplier_name=supplier_name or "流程链供应商", user=user)
        result["message"] = f"已下推采购单 {po.po_no}"
        result["doc"] = {"kind": "purchase_order", "id": po.id, "no": po.po_no}

    elif step == "push_production":
        plans = _plans_for_so(db, so_id)
        pid = plan_id or (plans["production"][0].id if plans["production"] else 0)
        if not pid:
            raise ValueError("无生产计划可下推")
        mos = create_mo_from_plan(db, pid, user=user)
        result["message"] = f"已下推生产单 {len(mos)} 张"
        result["docs"] = [{"kind": "production_order", "id": m.id, "no": m.mo_no} for m in mos]

    elif step == "push_outsource":
        plans = _plans_for_so(db, so_id)
        pid = plan_id or (plans["outsource"][0].id if plans["outsource"] else 0)
        if not pid:
            raise ValueError("无委外计划可下推")
        ww = create_ww_from_plan(db, pid, supplier_name=supplier_name or "流程链委外厂", user=user)
        result["message"] = f"已下推委外单 {ww.ww_no}"
        result["doc"] = {"kind": "outsource_order", "id": ww.id, "no": ww.ww_no}

    elif step == "push_execute":
        msgs: list[str] = []
        plans = _plans_for_so(db, so_id)
        if plans["purchase"]:
            po_exist = (
                db.query(PurchaseOrder)
                .filter(
                    PurchaseOrder.source_plan_id.in_([p.id for p in plans["purchase"]]),
                    PurchaseOrder.status != "void",
                )
                .count()
            )
            if not po_exist:
                po = create_po_from_plan(
                    db, plans["purchase"][0].id, supplier_name=supplier_name or "流程链供应商", user=user
                )
                msgs.append(po.po_no)
        mo_exist = (
            db.query(ProductionOrder)
            .filter(ProductionOrder.source_so_id == so_id, ProductionOrder.status != "void")
            .count()
        )
        if plans["production"] and not mo_exist:
            mos = create_mo_from_plan(db, plans["production"][0].id, user=user)
            msgs.extend(m.mo_no for m in mos)
        if plans["outsource"]:
            ww_exist = (
                db.query(OutsourceOrder)
                .filter(
                    OutsourceOrder.source_plan_id.in_([p.id for p in plans["outsource"]]),
                    OutsourceOrder.status != "void",
                )
                .count()
            )
            if not ww_exist:
                ww = create_ww_from_plan(
                    db, plans["outsource"][0].id, supplier_name=supplier_name or "流程链委外厂", user=user
                )
                msgs.append(ww.ww_no)
        if not msgs:
            raise ValueError("三线已下推或无计划")
        result["message"] = "已下推：" + "、".join(msgs)

    elif step == "issue_from_so":
        cur = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_id).first()
        if cur and cur.status == "confirmed":
            try:
                set_sales_order_status(db, so_id, "planning", user=user)
            except ValueError:
                pass
            try:
                set_sales_order_status(db, so_id, "executing", user=user)
            except ValueError:
                try:
                    set_sales_order_status(db, so_id, "executing", user=user)
                except ValueError:
                    pass
        elif cur and cur.status == "planning":
            try:
                set_sales_order_status(db, so_id, "executing", user=user)
            except ValueError:
                pass
        issue = create_issue_from_so(db, so_id, user=user)
        result["message"] = f"已建销售出库 {issue.issue_no}"
        result["doc"] = {"kind": "sales_issue", "id": issue.id, "no": issue.issue_no}

    elif step == "post_issue":
        iid = issue_id
        if not iid:
            row = (
                db.query(SalesIssue)
                .filter(SalesIssue.so_id == so_id, SalesIssue.status == "draft")
                .order_by(SalesIssue.id.desc())
                .first()
            )
            iid = row.id if row else 0
        if not iid:
            raise ValueError("无待过账出库单")
        issue = post_issue(db, int(iid), user=user)
        result["message"] = f"出库已过账 {issue.issue_no}"
        result["doc"] = {"kind": "sales_issue", "id": issue.id, "no": issue.issue_no}

    elif step == "delivery_from_issue":
        iid = issue_id
        if not iid:
            row = (
                db.query(SalesIssue)
                .filter(SalesIssue.so_id == so_id, SalesIssue.status == "posted")
                .order_by(SalesIssue.id.desc())
                .first()
            )
            iid = row.id if row else 0
        if not iid:
            raise ValueError("无已过账出库单")
        deli = create_delivery_from_issue(db, int(iid), user=user, carrier="流程链")
        result["message"] = f"已生成发货单 {deli.delivery_no}"
        result["doc"] = {"kind": "delivery", "id": deli.id, "no": deli.delivery_no}

    elif step == "confirm_delivery":
        did = delivery_id
        if not did:
            row = (
                db.query(DeliveryNote)
                .filter(DeliveryNote.so_id == so_id, DeliveryNote.status != "confirmed")
                .order_by(DeliveryNote.id.desc())
                .first()
            )
            did = row.id if row else 0
        if not did:
            raise ValueError("无待确认发货单")
        deli = confirm_delivery(db, int(did), user=user)
        result["message"] = f"发货已确认 {deli.delivery_no}"
        result["doc"] = {"kind": "delivery", "id": deli.id, "no": deli.delivery_no}

    else:
        raise ValueError(f"未知下推步骤：{step}")

    db.flush()
    result["chain"] = get_flow_chain(db, so_id)
    return result
