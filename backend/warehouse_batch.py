"""批量来料入账 / 按订单批量发料（统一走 apply_movement，同步库存与流水）。"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import load_config
from engineering_service import normalize_code, order_kitting
from models import WarehouseMaterial, WarehouseMovement
from packing_service import get_order_or_404
from warehouse_movements import MOVEMENT_ISSUE, MOVEMENT_OVERISSUE
from warehouse_operation import apply_movement
from warehouse_service import _next_no, get_material


def _customer_display_name(db: Session, customer_id: str) -> str:
    cid = (customer_id or "").strip()
    if not cid:
        return ""
    row = (
        db.query(WarehouseMaterial.customer_name)
        .filter(WarehouseMaterial.customer_id == cid)
        .filter(WarehouseMaterial.customer_name.isnot(None))
        .filter(WarehouseMaterial.customer_name != "")
        .first()
    )
    if row and row[0]:
        return str(row[0])
    for customer in load_config().get("customers", []) or []:
        if customer.get("id") == cid:
            return str(customer.get("name") or cid)
    return cid


def _resolve_material(db: Session, customer_id: str, material_code: str) -> WarehouseMaterial:
    code = (material_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="物料编码不能为空")
    cid = (customer_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="请选择客户")
    row = (
        db.query(WarehouseMaterial)
        .filter(
            WarehouseMaterial.customer_id == cid,
            WarehouseMaterial.material_code == code,
        )
        .first()
    )
    if not row:
        norm = normalize_code(code)
        for mat in db.query(WarehouseMaterial).filter(WarehouseMaterial.customer_id == cid).all():
            if normalize_code(mat.material_code) == norm:
                return mat
        raise HTTPException(status_code=400, detail=f"物料不存在：{code}")
    return row


def _resolve_or_create_material(
    db: Session,
    customer_id: str,
    material_code: str,
    *,
    material_name: str = "",
    spec: str = "",
    unit: str = "PCS",
) -> tuple[WarehouseMaterial, bool]:
    """查找物料；不存在则自动建档（qty=0）。返回 (物料, 是否新建)。"""
    code = (material_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="物料编码不能为空")
    cid = (customer_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="请选择客户")

    name = (material_name or "").strip()
    spec_val = (spec or "").strip()
    unit_val = (unit or "").strip() or "PCS"

    try:
        mat = _resolve_material(db, cid, code)
        # 已有料号：空名称/规格时用表格补全
        if name and not (mat.material_name or "").strip():
            mat.material_name = name
        if spec_val and not (mat.spec or "").strip():
            mat.spec = spec_val
        return mat, False
    except HTTPException as exc:
        if "物料不存在" not in str(exc.detail):
            raise

    mat = WarehouseMaterial(
        customer_id=cid,
        customer_name=_customer_display_name(db, cid),
        material_code=code,
        material_name=name or None,
        spec=spec_val or None,
        unit=unit_val,
        qty=0,
        locked_qty=0,
        remark="来料自动建档",
    )
    db.add(mat)
    db.flush()
    return mat, True


def _issued_qty_map(db: Session, order_no: str, product_model: str = "") -> dict[str, float]:
    q = db.query(WarehouseMovement).filter(
        WarehouseMovement.order_no == order_no.strip(),
        WarehouseMovement.movement_type.in_([MOVEMENT_ISSUE, MOVEMENT_OVERISSUE]),
    )
    rows = q.all()
    result: dict[str, float] = defaultdict(float)
    pm = (product_model or "").strip()
    for row in rows:
        if pm and row.product_model and row.product_model.strip() != pm:
            continue
        result[normalize_code(row.material_code)] += float(row.qty or 0)
    return result


def _line_issue_status(required: float, issued: float, available: float, has_material: bool) -> str:
    if not has_material:
        return "unregistered"
    remain = max(required - issued, 0)
    if remain <= 0:
        return "done"
    if available <= 0:
        return "no_stock"
    if available < remain:
        return "shortage"
    return "ready"


def get_order_issue_preview(db: Session, line_key: str) -> dict:
    try:
        order = get_order_or_404(db, line_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    kit = order_kitting(db, line_key)
    order_no = order.purchase_no or ""
    product_model = order.product_goods_no or ""
    issued_map = _issued_qty_map(db, order_no, product_model)

    stock_map: dict[str, WarehouseMaterial] = {}
    for mat in db.query(WarehouseMaterial).filter(WarehouseMaterial.customer_id == order.customer_id).all():
        stock_map[normalize_code(mat.material_code)] = mat

    lines = []
    for item in kit.get("lines") or []:
        code = item.get("material_code") or ""
        norm = normalize_code(code)
        mat = stock_map.get(norm)
        required = float(item.get("required_qty") or 0)
        issued = float(issued_map.get(norm, 0))
        remain = max(required - issued, 0)
        available = float(item.get("own_available_qty") or item.get("available_qty") or 0)
        if mat:
            available = max(float(mat.qty) - float(mat.locked_qty), 0)
        suggested = min(remain, available) if remain > 0 else 0
        status = _line_issue_status(required, issued, available, mat is not None)
        lines.append(
            {
                "material_id": mat.id if mat else None,
                "material_code": code,
                "material_name": item.get("material_name"),
                "spec": item.get("spec"),
                "required_qty": required,
                "issued_qty": issued,
                "remain_qty": remain,
                "available_qty": available,
                "shortage_qty": max(remain - available, 0) if remain > 0 else 0,
                "suggested_qty": suggested,
                "status": status,
                "process": (item.get("mount_type") or "").lower() or None,
                "mount_type": item.get("mount_type"),
            }
        )

    return {
        "line_key": line_key,
        "purchase_no": order_no,
        "product_goods_no": product_model,
        "product_goods_name": order.product_goods_name or "",
        "order_qty": float(order.batch_pur_qty or kit.get("order_qty") or 0),
        "customer_id": order.customer_id,
        "customer_name": order.customer_name or kit.get("customer_name") or "",
        "bom_model_id": kit.get("bom_model_id"),
        "material_status": kit.get("material_status"),
        "message": kit.get("message"),
        "lines": lines,
    }


def _merge_inbound_items(items: list[dict], batch_remark: str = "") -> tuple[list[dict], list[dict]]:
    """同料号多行（套料表常见）合并为一条：数量相加。返回 (合并后行, 校验错误)。"""
    errors: list[dict] = []
    merged: dict[str, dict] = {}
    order_keys: list[str] = []
    for idx, item in enumerate(items, start=1):
        code = (item.get("material_code") or "").strip()
        qty = float(item.get("qty") or 0)
        if not code:
            errors.append({"row": idx, "material_code": code, "error": "物料编码不能为空"})
            continue
        if qty <= 0:
            errors.append({"row": idx, "material_code": code, "error": "数量须大于 0"})
            continue
        key = normalize_code(code)
        line_remark = (item.get("remark") or batch_remark or "").strip()
        name = (item.get("material_name") or "").strip()
        spec = (item.get("spec") or "").strip()
        if key not in merged:
            order_keys.append(key)
            merged[key] = {
                "row": idx,
                "material_code": code,
                "qty": qty,
                "remark": line_remark,
                "material_name": name,
                "spec": spec,
            }
        else:
            row = merged[key]
            row["qty"] = float(row["qty"]) + qty
            if name and not row["material_name"]:
                row["material_name"] = name
            if spec and not row["spec"]:
                row["spec"] = spec
            if line_remark and not row["remark"]:
                row["remark"] = line_remark
    return [merged[k] for k in order_keys], errors


def batch_inbound(
    db: Session,
    customer_id: str,
    items: list[dict],
    operator: str,
    *,
    ref_no: str = "",
    remark: str = "",
    giver: str = "",
    receiver: str = "",
) -> dict:
    if not (customer_id or "").strip():
        raise HTTPException(status_code=400, detail="请选择客户")
    if not items:
        raise HTTPException(status_code=400, detail="请至少录入一行来料")
    batch_ref = (ref_no or "").strip() or _next_no(db, WarehouseMovement, "ref_no", "BI")
    movements = []
    created_codes: list[str] = []
    # 套料 Excel 常有同料号多行；若不合并，PG 上 dedupe_key 唯一约束会整批事务失败
    work_items, errors = _merge_inbound_items(items, remark)
    for item in work_items:
        idx = int(item["row"])
        code = item["material_code"]
        qty = float(item["qty"])
        line_remark = (item.get("remark") or remark or "").strip()
        try:
            # 行级 savepoint：单行失败不污染整批事务（PG 与 SQLite 均适用）
            with db.begin_nested():
                mat, created = _resolve_or_create_material(
                    db,
                    customer_id,
                    code,
                    material_name=(item.get("material_name") or "").strip(),
                    spec=(item.get("spec") or "").strip(),
                )
                if created:
                    created_codes.append(mat.material_code)
                mv = apply_movement(
                    db,
                    mat.id,
                    "inbound",
                    qty,
                    operator,
                    ref_no=batch_ref,
                    remark=line_remark or f"批量来料 · {batch_ref}",
                    giver=giver,
                    receiver=receiver,
                )
                movements.append(mv)
        except HTTPException as exc:
            detail = exc.detail
            if not isinstance(detail, str):
                detail = str(detail)
            errors.append({"row": idx, "material_code": code, "error": detail})
        except Exception as exc:
            errors.append({"row": idx, "material_code": code, "error": str(exc)})
    if not movements:
        raise HTTPException(status_code=400, detail=errors[0]["error"] if errors else "来料失败")
    return {
        "ref_no": batch_ref,
        "success_count": len(movements),
        "movements": movements,
        "errors": errors,
        "created_count": len(created_codes),
        "created_codes": created_codes,
    }


def batch_issue_order(
    db: Session,
    line_key: str,
    lines: list[dict],
    operator: str,
    *,
    ref_no: str = "",
    remark: str = "",
    skip_shortage: bool = True,
    giver: str = "",
    receiver: str = "",
) -> dict:
    if not lines:
        raise HTTPException(status_code=400, detail="请至少选择一行发料")
    try:
        order = get_order_or_404(db, line_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    preview = get_order_issue_preview(db, line_key)
    preview_map = {row["material_id"]: row for row in preview["lines"] if row.get("material_id")}

    order_no = order.purchase_no or ""
    product_model = order.product_goods_no or ""
    order_qty = float(order.batch_pur_qty or 0)
    batch_ref = (ref_no or "").strip() or _next_no(db, WarehouseMovement, "ref_no", "IS")

    movements = []
    skipped = []
    errors = []

    for idx, item in enumerate(lines, start=1):
        material_id = int(item.get("material_id") or 0)
        qty = float(item.get("qty") or 0)
        if qty <= 0:
            continue
        process = (item.get("process") or "").strip().lower() or None
        department = (item.get("department") or "").strip().lower() or None
        line_remark = (item.get("remark") or remark or "").strip()

        try:
            with db.begin_nested():
                mat = get_material(db, material_id)
                if mat.customer_id != order.customer_id:
                    raise HTTPException(status_code=400, detail=f"物料 {mat.material_code} 不属于该订单客户")

                available = max(float(mat.qty) - float(mat.locked_qty), 0)
                if skip_shortage and qty > available + 1e-6:
                    skipped.append(
                        {
                            "row": idx,
                            "material_code": mat.material_code,
                            "qty": qty,
                            "available_qty": available,
                            "reason": "库存不足",
                        }
                    )
                    continue

                prev = preview_map.get(material_id) or {}
                remain = float(prev.get("remain_qty") or 0)
                movement_type = MOVEMENT_OVERISSUE if remain > 0 and qty > remain + 1e-6 else MOVEMENT_ISSUE

                mv = apply_movement(
                    db,
                    material_id,
                    movement_type,
                    qty,
                    operator,
                    order_no=order_no,
                    product_model=product_model,
                    order_qty=order_qty,
                    process=process,
                    department=department or process,
                    ref_no=batch_ref,
                    remark=line_remark or f"批量发料 · {batch_ref}",
                    allow_negative=not skip_shortage,
                    giver=giver,
                    receiver=receiver,
                )
                movements.append(mv)
        except HTTPException as exc:
            detail = exc.detail
            if not isinstance(detail, str):
                detail = str(detail)
            errors.append({"row": idx, "material_id": material_id, "error": detail})
        except Exception as exc:
            errors.append({"row": idx, "material_id": material_id, "error": str(exc)})

    if not movements:
        detail = errors[0]["error"] if errors else (skipped[0]["reason"] if skipped else "发料失败")
        raise HTTPException(status_code=400, detail=detail)

    return {
        "ref_no": batch_ref,
        "success_count": len(movements),
        "movements": movements,
        "skipped": skipped,
        "errors": errors,
    }
