"""阶段3：MPS/MRP 计划中枢 — 需求收集、单层 BOM 展开、三类计划草案"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from doc_number import next_doc_number
from engineering_service import find_bom_models_by_code
from models import (
    BomLine,
    BomModel,
    CustomerForecast,
    CustomerForecastLine,
    ErpSalesOrder,
    ErpSalesOrderLine,
    ErpStockOrder,
    ErpStockOrderLine,
    ErpStockProduct,
    MrpRun,
    OutsourcePlan,
    OutsourcePlanLine,
    ProductionPlan,
    ProductionPlanLine,
    PurchaseForecast,
    PurchaseForecastLine,
    PurchasePlan,
    PurchasePlanLine,
    WarehouseMaterial,
)

PLAN_TRANSITIONS = {
    "draft": frozenset({"confirmed", "void"}),
    "confirmed": frozenset({"released", "void"}),
    "released": frozenset(),
    "void": frozenset(),
}

OUTSOURCE_HINTS = ("委外", "外协", "outsource", "OS")


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _is_outsource_process(process: str | None) -> bool:
    p = (process or "").strip()
    if not p:
        return False
    low = p.lower()
    return any(h.lower() in low or h in p for h in OUTSOURCE_HINTS)


def _resolve_bom_id(db: Session, *, bom_model_id: Optional[int], material_code: str) -> Optional[int]:
    if bom_model_id:
        bom = db.query(BomModel).filter(BomModel.id == bom_model_id, BomModel.is_active.is_(True)).first()
        return bom.id if bom else None
    code = (material_code or "").strip()
    if not code:
        return None
    found = find_bom_models_by_code(db, code)
    return found[0].id if found else None


def _available_qty(db: Session, material_code: str) -> float:
    code = (material_code or "").strip()
    if not code:
        return 0.0
    rows = db.query(WarehouseMaterial).filter(WarehouseMaterial.material_code == code).all()
    if not rows:
        # 宽松：忽略大小写/空白差异时仍可能 miss；按归一化再扫一遍成本高，MVP 精确匹配
        return 0.0
    total = 0.0
    for r in rows:
        total += max(0.0, float(r.qty or 0) - float(r.locked_qty or 0))
    return round(total, 4)


# —— 需求收集 ——


def collect_demands(
    db: Session,
    *,
    so_ids: list[int] | None = None,
    stock_ids: list[int] | None = None,
    include_forecasts: bool = True,
) -> list[dict]:
    """收集可进计划的需求行。

    - so_ids/stock_ids 均为 None：全量 confirmed/planning 销售+备货（+可选预告）
    - 任一指定：只取指定集合（未指定的单据类型不纳入）
    """
    demands: list[dict] = []
    scoped = so_ids is not None or stock_ids is not None

    if so_ids is not None or not scoped:
        so_q = db.query(ErpSalesOrder).filter(ErpSalesOrder.status.in_(("confirmed", "planning")))
        if so_ids is not None:
            so_q = so_q.filter(ErpSalesOrder.id.in_(so_ids or [-1]))
        for so in so_q.order_by(ErpSalesOrder.id).all():
            lines = (
                db.query(ErpSalesOrderLine)
                .filter(ErpSalesOrderLine.so_id == so.id)
                .order_by(ErpSalesOrderLine.sort_order, ErpSalesOrderLine.id)
                .all()
            )
            for ln in lines:
                demands.append(
                    {
                        "source_type": "sales",
                        "source_id": so.id,
                        "source_no": so.so_no,
                        "source_line_id": ln.id,
                        "customer_name": so.customer_name or "",
                        "material_code": ln.material_code or "",
                        "material_name": ln.material_name or "",
                        "qty": float(ln.qty or 0),
                        "unit": ln.unit or "PCS",
                        "due_date": ln.due_date or "",
                        "bom_model_id": ln.bom_model_id,
                    }
                )

    if stock_ids is not None or not scoped:
        st_q = db.query(ErpStockOrder).filter(ErpStockOrder.status.in_(("confirmed", "planning")))
        if stock_ids is not None:
            st_q = st_q.filter(ErpStockOrder.id.in_(stock_ids or [-1]))
        for st in st_q.order_by(ErpStockOrder.id).all():
            lines = (
                db.query(ErpStockOrderLine)
                .filter(ErpStockOrderLine.stock_id == st.id)
                .order_by(ErpStockOrderLine.sort_order, ErpStockOrderLine.id)
                .all()
            )
            for ln in lines:
                demands.append(
                    {
                        "source_type": "stock",
                        "source_id": st.id,
                        "source_no": st.stock_no,
                        "source_line_id": ln.id,
                        "customer_name": st.customer_name or "",
                        "material_code": ln.material_code or "",
                        "material_name": ln.material_name or "",
                        "qty": float(ln.qty or 0),
                        "unit": ln.unit or "PCS",
                        "due_date": ln.due_date or "",
                        "bom_model_id": ln.bom_model_id,
                    }
                )

    if include_forecasts and not scoped:
        for fc in db.query(CustomerForecast).filter(CustomerForecast.status == "confirmed").all():
            lines = (
                db.query(CustomerForecastLine)
                .filter(CustomerForecastLine.forecast_id == fc.id)
                .order_by(CustomerForecastLine.sort_order, CustomerForecastLine.id)
                .all()
            )
            for ln in lines:
                demands.append(
                    {
                        "source_type": "customer_forecast",
                        "source_id": fc.id,
                        "source_no": fc.forecast_no,
                        "source_line_id": ln.id,
                        "customer_name": fc.customer_name or "",
                        "material_code": ln.material_code or "",
                        "material_name": ln.material_name or "",
                        "qty": float(ln.qty or 0),
                        "unit": ln.unit or "PCS",
                        "due_date": ln.due_date or "",
                        "bom_model_id": ln.bom_model_id,
                    }
                )

    return [d for d in demands if d["qty"] > 0 and (d["material_code"] or d["material_name"])]


def explode_demand(db: Session, demand: dict) -> dict:
    """单层 BOM：成品进生产计划；元件缺口进采购/委外（不依赖齐套引擎参数签名）。"""
    qty = float(demand["qty"] or 0)
    bom_id = _resolve_bom_id(db, bom_model_id=demand.get("bom_model_id"), material_code=demand["material_code"])
    production = {
        "material_code": demand["material_code"],
        "material_name": demand["material_name"],
        "qty": qty,
        "unit": demand.get("unit") or "PCS",
        "due_date": demand.get("due_date") or "",
        "bom_model_id": bom_id,
        "source_type": demand["source_type"],
        "source_no": demand["source_no"],
        "source_so_id": demand["source_id"] if demand["source_type"] == "sales" else None,
        "remark": f"成品自制 {demand['source_no']}",
    }
    purchase: list[dict] = []
    outsource: list[dict] = []
    kit_status = "no_bom"
    kit_details: list[dict] = []

    if bom_id:
        lines = (
            db.query(BomLine)
            .filter(BomLine.bom_model_id == bom_id, BomLine.is_active.is_(True))
            .order_by(BomLine.sort_order, BomLine.id)
            .all()
        )
        kit_status = "ready" if lines else "empty_bom"
        shortage_n = 0
        for line in lines:
            qty_per = float(line.qty_per or 0)
            required = round(qty_per * qty, 4)
            avail = _available_qty(db, line.material_code or "")
            shortage = round(max(0.0, required - avail), 4)
            detail = {
                "material_code": line.material_code or "",
                "material_name": line.material_name or "",
                "qty_per": qty_per,
                "required_qty": required,
                "available_qty": avail,
                "shortage_qty": shortage,
                "unit": line.unit or "PCS",
                "process": line.process or "",
            }
            kit_details.append(detail)
            if shortage <= 0:
                continue
            shortage_n += 1
            row = {
                "material_code": detail["material_code"],
                "material_name": detail["material_name"],
                "qty": shortage,
                "unit": detail["unit"],
                "due_date": demand.get("due_date") or "",
                "source_type": demand["source_type"],
                "source_no": demand["source_no"],
                "source_so_id": demand["source_id"] if demand["source_type"] == "sales" else None,
                "process": detail["process"],
                "remark": f"缺口来自 {demand['source_no']} / {demand['material_code']}",
            }
            if _is_outsource_process(detail["process"]):
                outsource.append(row)
            else:
                purchase.append(row)
        if shortage_n == 0 and lines:
            kit_status = "ready"
        elif shortage_n == len(lines):
            kit_status = "shortage"
        elif shortage_n > 0:
            kit_status = "partial"

    return {
        "demand": demand,
        "bom_model_id": bom_id,
        "kitting_status": kit_status,
        "production": production,
        "purchase": purchase,
        "outsource": outsource,
        "component_count": len(kit_details),
        "components": kit_details,
    }


def preview_mrp(
    db: Session,
    *,
    so_ids: list[int] | None = None,
    stock_ids: list[int] | None = None,
    include_forecasts: bool = False,
) -> dict:
    demands = collect_demands(db, so_ids=so_ids, stock_ids=stock_ids, include_forecasts=include_forecasts)
    if not demands:
        raise ValueError("没有可进计划的需求（请先确认销售订单/备货单）")
    exploded = [explode_demand(db, d) for d in demands]
    purchase_agg: dict[str, dict] = {}
    outsource_agg: dict[str, dict] = {}
    production_rows = []
    for ex in exploded:
        production_rows.append(ex["production"])
        for p in ex["purchase"]:
            key = p["material_code"]
            if key not in purchase_agg:
                purchase_agg[key] = {**p}
            else:
                purchase_agg[key]["qty"] = round(purchase_agg[key]["qty"] + p["qty"], 4)
        for o in ex["outsource"]:
            key = o["material_code"]
            if key not in outsource_agg:
                outsource_agg[key] = {**o}
            else:
                outsource_agg[key]["qty"] = round(outsource_agg[key]["qty"] + o["qty"], 4)
    return {
        "demand_count": len(demands),
        "demands": demands,
        "exploded": exploded,
        "production_lines": production_rows,
        "purchase_lines": list(purchase_agg.values()),
        "outsource_lines": list(outsource_agg.values()),
        "aps_note": "APS 一期：生产计划生成后，请到 SMT/DIP 排产挂单（产能日历二期加深）",
    }


def generate_mrp(
    db: Session,
    *,
    so_ids: list[int] | None = None,
    stock_ids: list[int] | None = None,
    include_forecasts: bool = False,
    advance_status: bool = True,
    user: str = "",
) -> dict:
    preview = preview_mrp(db, so_ids=so_ids, stock_ids=stock_ids, include_forecasts=include_forecasts)

    pur = PurchasePlan(
        plan_no=next_doc_number(db, "purchase_plan"),
        status="draft",
        remark="MRP 生成",
        created_by=user,
    )
    db.add(pur)
    db.flush()
    for i, ln in enumerate(preview["purchase_lines"]):
        db.add(
            PurchasePlanLine(
                plan_id=pur.id,
                sort_order=i,
                material_code=ln["material_code"],
                material_name=ln.get("material_name") or "",
                qty=ln["qty"],
                unit=ln.get("unit") or "PCS",
                due_date=ln.get("due_date") or "",
                source_type=ln.get("source_type") or "",
                source_no=ln.get("source_no") or "",
                source_so_id=ln.get("source_so_id"),
                remark=ln.get("remark") or "",
            )
        )

    prod = ProductionPlan(
        plan_no=next_doc_number(db, "production_plan"),
        status="draft",
        remark="MRP 生成",
        created_by=user,
    )
    db.add(prod)
    db.flush()
    for i, ln in enumerate(preview["production_lines"]):
        db.add(
            ProductionPlanLine(
                plan_id=prod.id,
                sort_order=i,
                material_code=ln["material_code"],
                material_name=ln.get("material_name") or "",
                qty=ln["qty"],
                unit=ln.get("unit") or "PCS",
                due_date=ln.get("due_date") or "",
                bom_model_id=ln.get("bom_model_id"),
                source_type=ln.get("source_type") or "",
                source_no=ln.get("source_no") or "",
                source_so_id=ln.get("source_so_id"),
                remark=ln.get("remark") or "",
            )
        )

    outs = OutsourcePlan(
        plan_no=next_doc_number(db, "outsource_plan"),
        status="draft",
        remark="MRP 生成",
        created_by=user,
    )
    db.add(outs)
    db.flush()
    for i, ln in enumerate(preview["outsource_lines"]):
        db.add(
            OutsourcePlanLine(
                plan_id=outs.id,
                sort_order=i,
                material_code=ln["material_code"],
                material_name=ln.get("material_name") or "",
                qty=ln["qty"],
                unit=ln.get("unit") or "PCS",
                due_date=ln.get("due_date") or "",
                process=ln.get("process") or "",
                source_type=ln.get("source_type") or "",
                source_no=ln.get("source_no") or "",
                source_so_id=ln.get("source_so_id"),
                remark=ln.get("remark") or "",
            )
        )

    so_id_set = sorted(
        {
            d["source_id"]
            for d in preview["demands"]
            if d["source_type"] == "sales"
        }
    )
    stock_id_set = sorted(
        {
            d["source_id"]
            for d in preview["demands"]
            if d["source_type"] == "stock"
        }
    )

    run = MrpRun(
        run_no=next_doc_number(db, "mrp_run"),
        status="generated",
        source_so_ids=",".join(str(i) for i in so_id_set),
        source_stock_ids=",".join(str(i) for i in stock_id_set),
        demand_count=preview["demand_count"],
        purchase_plan_id=pur.id,
        production_plan_id=prod.id,
        outsource_plan_id=outs.id,
        summary=json.dumps(
            {
                "purchase": len(preview["purchase_lines"]),
                "production": len(preview["production_lines"]),
                "outsource": len(preview["outsource_lines"]),
            },
            ensure_ascii=False,
        ),
        created_by=user,
    )
    db.add(run)
    db.flush()
    pur.mrp_run_id = run.id
    prod.mrp_run_id = run.id
    outs.mrp_run_id = run.id

    if advance_status:
        for sid in so_id_set:
            so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == sid).first()
            if so and so.status == "confirmed":
                so.status = "planning"
                _touch(so)
        for sid in stock_id_set:
            st = db.query(ErpStockOrder).filter(ErpStockOrder.id == sid).first()
            if st and st.status == "confirmed":
                st.status = "planning"
                _touch(st)

    db.flush()
    return {
        "run": mrp_run_to_dict(run),
        "purchase_plan": plan_header_dict(pur, "purchase"),
        "production_plan": plan_header_dict(prod, "production"),
        "outsource_plan": plan_header_dict(outs, "outsource"),
        "preview": {
            "demand_count": preview["demand_count"],
            "purchase_lines": preview["purchase_lines"],
            "production_lines": preview["production_lines"],
            "outsource_lines": preview["outsource_lines"],
            "aps_note": preview["aps_note"],
        },
    }


def mrp_run_to_dict(row: MrpRun) -> dict:
    return {
        "id": row.id,
        "run_no": row.run_no,
        "status": row.status,
        "source_so_ids": row.source_so_ids or "",
        "source_stock_ids": row.source_stock_ids or "",
        "demand_count": row.demand_count,
        "purchase_plan_id": row.purchase_plan_id,
        "production_plan_id": row.production_plan_id,
        "outsource_plan_id": row.outsource_plan_id,
        "summary": row.summary or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
    }


def plan_header_dict(row: Any, kind: str) -> dict:
    return {
        "id": row.id,
        "plan_no": row.plan_no,
        "kind": kind,
        "mrp_run_id": row.mrp_run_id,
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _set_plan_status(row: Any, status: str) -> None:
    target = (status or "").strip()
    allowed = PLAN_TRANSITIONS.get(row.status, frozenset())
    if target not in allowed:
        raise ValueError(f"计划状态不可从 {row.status} → {target}")
    row.status = target
    _touch(row)


# —— 三类计划查询 ——


def list_purchase_plans(db: Session, *, limit: int = 100) -> list[PurchasePlan]:
    return db.query(PurchasePlan).order_by(PurchasePlan.id.desc()).limit(limit).all()


def get_purchase_plan(db: Session, pid: int) -> tuple[PurchasePlan, list[PurchasePlanLine]]:
    row = db.query(PurchasePlan).filter(PurchasePlan.id == pid).first()
    if not row:
        raise ValueError("采购计划不存在")
    lines = (
        db.query(PurchasePlanLine)
        .filter(PurchasePlanLine.plan_id == pid)
        .order_by(PurchasePlanLine.sort_order, PurchasePlanLine.id)
        .all()
    )
    return row, lines


def purchase_plan_to_dict(row: PurchasePlan, lines: list[PurchasePlanLine] | None = None) -> dict:
    d = plan_header_dict(row, "purchase")
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "unit": ln.unit,
                "due_date": ln.due_date,
                "source_type": ln.source_type,
                "source_no": ln.source_no,
                "source_so_id": ln.source_so_id,
                "remark": ln.remark,
            }
            for ln in lines
        ]
    return d


def set_purchase_plan_status(db: Session, pid: int, status: str) -> PurchasePlan:
    row, _ = get_purchase_plan(db, pid)
    _set_plan_status(row, status)
    db.flush()
    return row


def list_production_plans(db: Session, *, limit: int = 100) -> list[ProductionPlan]:
    return db.query(ProductionPlan).order_by(ProductionPlan.id.desc()).limit(limit).all()


def get_production_plan(db: Session, pid: int) -> tuple[ProductionPlan, list[ProductionPlanLine]]:
    row = db.query(ProductionPlan).filter(ProductionPlan.id == pid).first()
    if not row:
        raise ValueError("生产计划不存在")
    lines = (
        db.query(ProductionPlanLine)
        .filter(ProductionPlanLine.plan_id == pid)
        .order_by(ProductionPlanLine.sort_order, ProductionPlanLine.id)
        .all()
    )
    return row, lines


def production_plan_to_dict(row: ProductionPlan, lines: list[ProductionPlanLine] | None = None) -> dict:
    d = plan_header_dict(row, "production")
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "unit": ln.unit,
                "due_date": ln.due_date,
                "bom_model_id": ln.bom_model_id,
                "source_type": ln.source_type,
                "source_no": ln.source_no,
                "source_so_id": ln.source_so_id,
                "remark": ln.remark,
            }
            for ln in lines
        ]
    return d


def set_production_plan_status(db: Session, pid: int, status: str) -> ProductionPlan:
    row, _ = get_production_plan(db, pid)
    _set_plan_status(row, status)
    db.flush()
    return row


def list_outsource_plans(db: Session, *, limit: int = 100) -> list[OutsourcePlan]:
    return db.query(OutsourcePlan).order_by(OutsourcePlan.id.desc()).limit(limit).all()


def get_outsource_plan(db: Session, pid: int) -> tuple[OutsourcePlan, list[OutsourcePlanLine]]:
    row = db.query(OutsourcePlan).filter(OutsourcePlan.id == pid).first()
    if not row:
        raise ValueError("委外计划不存在")
    lines = (
        db.query(OutsourcePlanLine)
        .filter(OutsourcePlanLine.plan_id == pid)
        .order_by(OutsourcePlanLine.sort_order, OutsourcePlanLine.id)
        .all()
    )
    return row, lines


def outsource_plan_to_dict(row: OutsourcePlan, lines: list[OutsourcePlanLine] | None = None) -> dict:
    d = plan_header_dict(row, "outsource")
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "unit": ln.unit,
                "due_date": ln.due_date,
                "process": ln.process,
                "source_type": ln.source_type,
                "source_no": ln.source_no,
                "source_so_id": ln.source_so_id,
                "remark": ln.remark,
            }
            for ln in lines
        ]
    return d


def set_outsource_plan_status(db: Session, pid: int, status: str) -> OutsourcePlan:
    row, _ = get_outsource_plan(db, pid)
    _set_plan_status(row, status)
    db.flush()
    return row


def list_mrp_runs(db: Session, *, limit: int = 50) -> list[MrpRun]:
    return db.query(MrpRun).order_by(MrpRun.id.desc()).limit(limit).all()


# —— 库存预警 ——


def stock_warnings(db: Session, *, limit: int = 200) -> list[dict]:
    products = (
        db.query(ErpStockProduct)
        .filter(ErpStockProduct.is_active.is_(True), ErpStockProduct.safety_qty > 0)
        .order_by(ErpStockProduct.material_code)
        .limit(limit)
        .all()
    )
    out = []
    for p in products:
        avail = _available_qty(db, p.material_code)
        safety = float(p.safety_qty or 0)
        gap = round(safety - avail, 4)
        if gap > 0:
            out.append(
                {
                    "material_code": p.material_code,
                    "material_name": p.material_name,
                    "safety_qty": safety,
                    "available_qty": avail,
                    "gap_qty": gap,
                    "unit": p.unit or "PCS",
                }
            )
    return out


# —— 客户/采购预告 ——


def create_customer_forecast(db: Session, data: dict, *, user: str) -> CustomerForecast:
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("客户预告至少一行")
    row = CustomerForecast(
        forecast_no=next_doc_number(db, "customer_forecast"),
        customer_id=data.get("customer_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    for i, raw in enumerate(lines):
        db.add(
            CustomerForecastLine(
                forecast_id=row.id,
                sort_order=i,
                material_code=(raw.get("material_code") or "").strip(),
                material_name=(raw.get("material_name") or "").strip(),
                qty=float(raw.get("qty") or 0),
                unit=(raw.get("unit") or "PCS").strip() or "PCS",
                due_date=(raw.get("due_date") or "").strip(),
                bom_model_id=raw.get("bom_model_id"),
                remark=(raw.get("remark") or "").strip(),
            )
        )
    db.flush()
    return row


def set_customer_forecast_status(db: Session, fid: int, status: str) -> CustomerForecast:
    row = db.query(CustomerForecast).filter(CustomerForecast.id == fid).first()
    if not row:
        raise ValueError("客户预告不存在")
    target = (status or "").strip()
    allowed = {"draft": frozenset({"confirmed", "void"}), "confirmed": frozenset({"void"}), "void": frozenset()}
    if target not in allowed.get(row.status, frozenset()):
        raise ValueError(f"预告状态不可从 {row.status} → {target}")
    row.status = target
    _touch(row)
    db.flush()
    return row


def customer_forecast_to_dict(row: CustomerForecast, lines: list[CustomerForecastLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "forecast_no": row.forecast_no,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name,
        "status": row.status,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "unit": ln.unit,
                "due_date": ln.due_date,
                "bom_model_id": ln.bom_model_id,
            }
            for ln in lines
        ]
    return d


def list_customer_forecasts(db: Session, *, limit: int = 100) -> list[CustomerForecast]:
    return db.query(CustomerForecast).order_by(CustomerForecast.id.desc()).limit(limit).all()


def create_purchase_forecast(db: Session, data: dict, *, user: str) -> PurchaseForecast:
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("采购预告至少一行")
    row = PurchaseForecast(
        forecast_no=next_doc_number(db, "purchase_forecast"),
        supplier_name=(data.get("supplier_name") or "").strip(),
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    for i, raw in enumerate(lines):
        db.add(
            PurchaseForecastLine(
                forecast_id=row.id,
                sort_order=i,
                material_code=(raw.get("material_code") or "").strip(),
                material_name=(raw.get("material_name") or "").strip(),
                qty=float(raw.get("qty") or 0),
                unit=(raw.get("unit") or "PCS").strip() or "PCS",
                due_date=(raw.get("due_date") or "").strip(),
                remark=(raw.get("remark") or "").strip(),
            )
        )
    db.flush()
    return row


def set_purchase_forecast_status(db: Session, fid: int, status: str) -> PurchaseForecast:
    row = db.query(PurchaseForecast).filter(PurchaseForecast.id == fid).first()
    if not row:
        raise ValueError("采购预告不存在")
    target = (status or "").strip()
    allowed = {"draft": frozenset({"confirmed", "void"}), "confirmed": frozenset({"void"}), "void": frozenset()}
    if target not in allowed.get(row.status, frozenset()):
        raise ValueError(f"预告状态不可从 {row.status} → {target}")
    row.status = target
    _touch(row)
    db.flush()
    return row


def purchase_forecast_to_dict(row: PurchaseForecast, lines: list[PurchaseForecastLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "forecast_no": row.forecast_no,
        "supplier_name": row.supplier_name,
        "status": row.status,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "unit": ln.unit,
                "due_date": ln.due_date,
            }
            for ln in lines
        ]
    return d


def list_purchase_forecasts(db: Session, *, limit: int = 100) -> list[PurchaseForecast]:
    return db.query(PurchaseForecast).order_by(PurchaseForecast.id.desc()).limit(limit).all()


# —— PMC 看板 ——


def pmc_board(db: Session, *, limit: int = 50) -> list[dict]:
    """销售订单全程催办：计划三线 + 执行单据 + 出货进度。"""
    from models import DeliveryNote, ProductionOrder, SalesIssue

    sos = (
        db.query(ErpSalesOrder)
        .filter(ErpSalesOrder.status.notin_(("void", "draft")))
        .order_by(ErpSalesOrder.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for so in sos:
        lines = (
            db.query(ErpSalesOrderLine)
            .filter(ErpSalesOrderLine.so_id == so.id)
            .order_by(ErpSalesOrderLine.sort_order, ErpSalesOrderLine.id)
            .all()
        )
        qty = sum(float(ln.qty or 0) for ln in lines)
        shipped = sum(float(ln.shipped_qty or 0) for ln in lines)
        pur_n = (
            db.query(func.count(PurchasePlanLine.id)).filter(PurchasePlanLine.source_so_id == so.id).scalar() or 0
        )
        prod_n = (
            db.query(func.count(ProductionPlanLine.id)).filter(ProductionPlanLine.source_so_id == so.id).scalar()
            or 0
        )
        outs_n = (
            db.query(func.count(OutsourcePlanLine.id)).filter(OutsourcePlanLine.source_so_id == so.id).scalar() or 0
        )
        mo_rows = (
            db.query(ProductionOrder)
            .filter(ProductionOrder.source_so_id == so.id, ProductionOrder.status != "void")
            .all()
        )
        issue_n = db.query(func.count(SalesIssue.id)).filter(SalesIssue.so_id == so.id).scalar() or 0
        deli_n = db.query(func.count(DeliveryNote.id)).filter(DeliveryNote.so_id == so.id).scalar() or 0

        alerts: list[str] = []
        if so.status in ("confirmed",) and pur_n + prod_n + outs_n == 0:
            alerts.append("待跑 MRP/下推计划")
        if so.status in ("planning", "executing") and not mo_rows and prod_n > 0:
            alerts.append("生产计划未下推生产单")
        if float(shipped) + 1e-6 < float(qty) and so.status not in ("done", "closed"):
            if issue_n == 0 and so.status in ("executing", "partial_shipped", "planning"):
                alerts.append("待销售出库")
            elif float(shipped) > 0:
                alerts.append("部分出货未完成")
        if so.status == "done" and deli_n == 0:
            alerts.append("已出库待发货确认")

        urgency = "high" if alerts else ("medium" if so.status in ("confirmed", "planning", "executing") else "low")
        out.append(
            {
                "so_id": so.id,
                "so_no": so.so_no,
                "customer_name": so.customer_name,
                "status": so.status,
                "qty": qty,
                "shipped_qty": shipped,
                "ship_progress": f"{shipped:g}/{qty:g}",
                "purchase_plan_lines": int(pur_n),
                "production_plan_lines": int(prod_n),
                "outsource_plan_lines": int(outs_n),
                "purchase_lines": int(pur_n),
                "production_lines": int(prod_n),
                "outsource_lines": int(outs_n),
                "mo_count": len(mo_rows),
                "mo_status": ",".join(sorted({m.status for m in mo_rows})) if mo_rows else "",
                "sales_issue_count": int(issue_n),
                "delivery_count": int(deli_n),
                "alerts": alerts,
                "urgency": urgency,
                "urge_hint": "；".join(alerts) if alerts else "进度正常",
            }
        )
    out.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["urgency"], 9))
    return out


def pmc_urge(db: Session, so_id: int, *, user: str, note: str = "") -> dict:
    """催办记录（写销售单备注尾注，供审计）。"""
    so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_id).first()
    if not so:
        raise ValueError("销售订单不存在")
    stamp = _now().strftime("%Y-%m-%d %H:%M")
    tip = (note or "请跟进三线/出货").strip()
    so.remark = ((so.remark or "") + f"\n[催办 {stamp} by {user}] {tip}").strip()
    _touch(so)
    db.flush()
    return {"so_id": so.id, "so_no": so.so_no, "urged_at": stamp, "note": tip, "remark": so.remark}


KIT_STATUS_LABELS = {
    "ready": "齐套",
    "partial": "部分齐",
    "shortage": "欠料",
    "no_bom": "无BOM",
    "empty_bom": "BOM空",
}


def run_mc_kitting(
    db: Session,
    *,
    so_ids: list[int] | None = None,
    q: str = "",
    statuses: list[str] | None = None,
) -> dict:
    """MC 齐套运算：按销售订单行展开 BOM，对照库存算缺料。"""
    allow = statuses or ["confirmed", "planning", "executing", "partial_shipped"]
    so_q = db.query(ErpSalesOrder).filter(ErpSalesOrder.status.in_(tuple(allow)))
    if so_ids:
        so_q = so_q.filter(ErpSalesOrder.id.in_(so_ids))
    qq = (q or "").strip()
    if qq:
        like = f"%{qq}%"
        so_q = so_q.filter(
            or_(
                ErpSalesOrder.so_no.ilike(like),
                ErpSalesOrder.customer_name.ilike(like),
                ErpSalesOrder.external_po_no.ilike(like),
            )
        )
    orders = so_q.order_by(ErpSalesOrder.id.desc()).limit(200).all()
    if not orders:
        return {
            "run_at": _now().isoformat(),
            "order_count": 0,
            "line_count": 0,
            "ready_count": 0,
            "shortage_count": 0,
            "items": [],
        }

    items: list[dict] = []
    ready_n = 0
    shortage_n = 0
    for so in orders:
        lines = (
            db.query(ErpSalesOrderLine)
            .filter(ErpSalesOrderLine.so_id == so.id)
            .order_by(ErpSalesOrderLine.sort_order, ErpSalesOrderLine.id)
            .all()
        )
        for ln in lines:
            demand = {
                "source_type": "sales",
                "source_id": so.id,
                "source_no": so.so_no,
                "source_line_id": ln.id,
                "customer_name": so.customer_name or "",
                "material_code": ln.material_code or "",
                "material_name": ln.material_name or "",
                "qty": float(ln.qty or 0),
                "unit": ln.unit or "PCS",
                "due_date": ln.due_date or "",
                "bom_model_id": ln.bom_model_id,
            }
            if demand["qty"] <= 0:
                continue
            ex = explode_demand(db, demand)
            st = ex.get("kitting_status") or "no_bom"
            if st == "ready":
                ready_n += 1
            elif st in ("shortage", "partial", "no_bom", "empty_bom"):
                shortage_n += 1
            items.append(
                {
                    "so_id": so.id,
                    "so_no": so.so_no,
                    "so_status": so.status,
                    "customer_name": so.customer_name or "",
                    "external_po_no": so.external_po_no or "",
                    "line_id": ln.id,
                    "material_code": demand["material_code"],
                    "material_name": demand["material_name"],
                    "qty": demand["qty"],
                    "unit": demand["unit"],
                    "due_date": demand["due_date"],
                    "bom_model_id": ex.get("bom_model_id"),
                    "kitting_status": st,
                    "kitting_status_label": KIT_STATUS_LABELS.get(st, st),
                    "component_count": ex.get("component_count") or 0,
                    "shortage_count": sum(1 for c in (ex.get("components") or []) if float(c.get("shortage_qty") or 0) > 0),
                    "purchase_shortage_qty": round(sum(float(p.get("qty") or 0) for p in ex.get("purchase") or []), 4),
                    "outsource_shortage_qty": round(sum(float(o.get("qty") or 0) for o in ex.get("outsource") or []), 4),
                    "components": ex.get("components") or [],
                }
            )

    return {
        "run_at": _now().isoformat(),
        "order_count": len(orders),
        "line_count": len(items),
        "ready_count": ready_n,
        "shortage_count": shortage_n,
        "items": items,
        "status_labels": KIT_STATUS_LABELS,
    }
