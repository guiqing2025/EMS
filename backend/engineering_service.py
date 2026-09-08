"""工程 BOM 与备料齐套"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from config import get_engineering_customers, get_engineering_customer_by_srm_id
from eng_customer_rules import is_engineering_fee_order
from models import (
    BomLine,
    BomModel,
    EngOrderHide,
    EngReviewInbox,
    PcbGerberPackage,
    PcbPlacementFile,
    PcbRefmapFile,
    SrmOrder,
    WarehouseMaterial,
)
from placement_canonical import (
    delete_gerber_package,
    delete_placement_file,
    delete_refmap_file,
    pick_canonical_gerber,
    pick_canonical_placement,
    pick_canonical_refmap,
)
from engineering_assets import delete_refmap_store_file
from mount_classification import classify_lines_mount, load_placement_index
from substitution_service import (
    build_substitute_details,
    evaluate_kitting_line,
    get_rule_qty_per,
    resolve_group_stock,
)


_DASH_CHARS = ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212", "－")


def normalize_code(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value).strip().upper().replace(" ", "")
    for ch in _DASH_CHARS:
        text = text.replace(ch, "-")
    return text


def _bom_catalog_match_score(order_code: str, bom: BomModel) -> int:
    """订单料号与 BOM 机型的匹配强度；>0 才允许跨料号挂接。"""
    needle = normalize_code(order_code)
    mc = normalize_code(bom.model_code)
    if not needle or not mc:
        return 0
    if needle == mc:
        return 100
    score = 0
    if needle in mc or mc in needle:
        score += 3
    remark = f"{bom.remark or ''}{bom.folder_name or ''}{bom.source_file or ''}"
    if needle in normalize_code(remark):
        score += 2
    if needle in normalize_code(bom.source_file or ""):
        score += 2
    return score


def suggest_bom_model(db: Session, order: SrmOrder) -> Optional[BomModel]:
    """匹配本采购订单号下的专属 BOM（同客户/内部码）；机型号不一致时可用文件名证据兜底。"""
    eng = get_engineering_customer_by_srm_id(order.customer_id)
    if not eng:
        return None
    internal_code = eng.get("internal_code")
    product = normalize_code(order.product_goods_no)
    purchase_no = (order.purchase_no or "").strip()
    if not product or not purchase_no:
        return None
    models = (
        db.query(BomModel)
        .filter(
            BomModel.internal_code == internal_code,
            BomModel.is_active.is_(True),
            BomModel.purchase_no == purchase_no,
            BomModel.line_count > 0,
        )
        .order_by(BomModel.updated_at.desc(), BomModel.id.desc())
        .all()
    )
    for row in models:
        if normalize_code(row.model_code) == product:
            return row
    # 导入时若未吃到手工单别名，机型号可能仍是 Excel 主件号；文件名常带订单料号（如 PC1459…xlsx）
    for row in models:
        blob = normalize_code(f"{row.folder_name or ''}{row.source_file or ''}{row.remark or ''}")
        if product and product in blob:
            return row
    # 本采购单在该客户下仅一份 BOM：按订单级专属挂接
    if len(models) == 1:
        return models[0]
    return None


def bind_orders_to_bom_by_purchase_no(
    db: Session,
    *,
    customer_id: str,
    purchase_no: str,
    bom_model_id: int,
    model_code: Optional[str] = None,
) -> int:
    """将同一采购订单号下、机型匹配的在制行绑定到指定 BOM。"""
    from config import expand_customer_ids_for_filter

    pn = (purchase_no or "").strip()
    if not pn or not customer_id:
        return 0
    cids = expand_customer_ids_for_filter(customer_id) or [customer_id]
    q = db.query(SrmOrder).filter(
        SrmOrder.is_completed.is_(False),
        SrmOrder.customer_id.in_(cids),
        SrmOrder.purchase_no == pn,
    )
    bound = 0
    needle = normalize_code(model_code) if model_code else ""
    for order in q.all():
        if needle and normalize_code(order.product_goods_no) != needle:
            continue
        order.bom_model_id = bom_model_id
        bound += 1
    return bound


def find_bom_models_by_code(
    db: Session,
    model_code: str,
    customer_id: Optional[str] = None,
) -> list[BomModel]:
    """按机型号查找 BOM：精确匹配优先，其次前后缀/包含。"""
    needle = normalize_code(model_code)
    if not needle:
        return []
    q = db.query(BomModel).filter(BomModel.is_active.is_(True))
    if customer_id:
        q = q.filter(BomModel.customer_id == customer_id)
    rows = q.all()
    exact = [r for r in rows if normalize_code(r.model_code) == needle]
    if exact:
        return exact
    soft = [
        r
        for r in rows
        if (code := normalize_code(r.model_code))
        and (needle.startswith(code) or code.startswith(needle) or needle in code or code in needle)
    ]
    soft.sort(key=lambda r: (-(r.line_count or 0), r.model_code or ""))
    return soft


def bind_order_bom(db: Session, line_key: str, bom_model_id: Optional[int]) -> SrmOrder:
    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise ValueError("订单不存在")
    if bom_model_id:
        bom = db.query(BomModel).filter(BomModel.id == bom_model_id, BomModel.is_active.is_(True)).first()
        if not bom:
            raise ValueError("BOM 机型不存在")
        if bom.customer_id != order.customer_id:
            raise ValueError("BOM 客户与订单客户不一致")
        order.bom_model_id = bom.id
    else:
        order.bom_model_id = None
    return order


def auto_bind_orders(db: Session, customer_id: Optional[str] = None) -> int:
    q = db.query(SrmOrder).filter(SrmOrder.is_completed.is_(False), SrmOrder.bom_model_id.is_(None))
    if customer_id:
        q = q.filter(SrmOrder.customer_id == customer_id)
    bound = 0
    for order in q.all():
        bom = suggest_bom_model(db, order)
        if bom:
            order.bom_model_id = bom.id
            bound += 1
    return bound


def _warehouse_stock_map(db: Session, customer_id: str) -> dict[str, WarehouseMaterial]:
    stock_map: dict[str, WarehouseMaterial] = {}
    cid = (customer_id or "").strip()
    if not cid:
        return stock_map
    for mat in db.query(WarehouseMaterial).filter(WarehouseMaterial.customer_id == cid).all():
        stock_map[normalize_code(mat.material_code)] = mat
    return stock_map


def compute_kitting(
    db: Session,
    bom_model_id: int,
    order_qty: float,
    *,
    stock_map: Optional[dict[str, WarehouseMaterial]] = None,
) -> dict:
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
    if not bom:
        raise ValueError("BOM 不存在")
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == bom_model_id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    if stock_map is None:
        stock_map = _warehouse_stock_map(db, bom.customer_id or "")

    from material_mount_service import load_mount_overrides

    placement_index = load_placement_index(db, bom)
    overrides = load_mount_overrides(db, internal_code=bom.internal_code or "")
    _, mounts = classify_lines_mount(
        lines,
        placement_index=placement_index,
        profile_override=bom.mount_profile_override,
        master_overrides=overrides,
        internal_code=bom.internal_code or "",
    )
    details = []
    shortage_count = 0
    partial_count = 0
    model_code = bom.model_code or ""
    customer_id = bom.customer_id or ""
    purchase_no = getattr(bom, "purchase_no", None) or ""
    for line, mount in zip(lines, mounts):
        rule_qty = get_rule_qty_per(
            line.material_code,
            customer_id,
            parent_code=model_code,
            purchase_no=purchase_no,
        )
        qty_per = float(rule_qty) if rule_qty is not None else float(line.qty_per or 0)
        required = round(qty_per * order_qty, 4)
        stock_info = resolve_group_stock(
            line.material_code,
            stock_map,
            customer_id,
            parent_code=model_code,
            purchase_no=purchase_no,
        )
        mat = stock_map.get(normalize_code(line.material_code))
        own_stock = float(stock_info.get("own_stock_qty") or 0)
        own_available = float(stock_info.get("own_available_qty") or 0)
        substitutes = build_substitute_details(
            line.material_code,
            stock_map,
            customer_id=customer_id,
            parent_code=model_code,
            purchase_no=purchase_no,
        )
        excel_in = float(mat.excel_in_qty) if mat and mat.excel_in_qty is not None else None
        excel_count = float(mat.excel_count_qty) if mat and mat.excel_count_qty is not None else None
        excel_demand = float(mat.excel_demand_qty) if mat and mat.excel_demand_qty is not None else None
        kit_eval = evaluate_kitting_line(
            required,
            own_stock,
            substitutes,
            excel_in_qty=excel_in,
            excel_demand_qty=excel_demand,
        )
        line_status = str(kit_eval.get("status") or "shortage")
        shortage = float(kit_eval.get("shortage_qty") or 0)
        supply = float(kit_eval.get("kitting_supply_qty") or 0)
        if line_status == "partial":
            partial_count += 1
        elif line_status == "shortage":
            shortage_count += 1
        details.append(
            {
                "material_code": line.material_code,
                "material_name": line.material_name,
                "spec": line.spec,
                "unit": line.unit,
                "qty_per": qty_per,
                "bom_qty_per": line.qty_per,
                "substitution_qty_per": rule_qty,
                "position": line.position,
                "mount_type": mount["mount_type"],
                "mount_side": mount["mount_side"],
                "mount_source": mount["mount_source"],
                "mount_reason": mount.get("mount_reason") or "",
                "required_qty": required,
                "stock_qty": own_stock,
                "available_qty": supply,
                "own_stock_qty": own_stock,
                "own_available_qty": own_available,
                "excel_count_qty": excel_count,
                "excel_in_qty": excel_in,
                "excel_demand_qty": excel_demand,
                "ledger_owe_qty": float(kit_eval.get("ledger_owe_qty") or 0),
                "main_gap_qty": float(kit_eval.get("main_gap_qty") or 0),
                "kitting_supply_qty": supply,
                "substitute_covered": bool(kit_eval.get("substitute_covered")),
                "stock_primary_code": stock_info.get("stock_primary_code") or line.material_code,
                "shortage_qty": shortage,
                "status": line_status,
                "substitutes": substitutes,
                "substitute_codes": [s["material_code"] for s in substitutes],
            }
        )

    if not details:
        overall = "unknown"
    elif shortage_count == 0 and partial_count == 0:
        overall = "ready"
    elif shortage_count == len(details):
        overall = "shortage"
    else:
        overall = "partial"

    return {
        "bom_model_id": bom.id,
        "model_code": bom.model_code,
        "model_name": bom.model_name,
        "customer_id": bom.customer_id,
        "customer_name": bom.customer_name,
        "order_qty": order_qty,
        "material_status": overall,
        "ready_count": sum(1 for d in details if d["status"] == "ready"),
        "partial_count": partial_count,
        "shortage_count": shortage_count,
        "total_lines": len(details),
        "lines": details,
    }


def order_kitting(db: Session, line_key: str) -> dict:
    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise ValueError("订单不存在")
    if not order.bom_model_id:
        bom = suggest_bom_model(db, order)
        if bom:
            order.bom_model_id = bom.id
    if not order.bom_model_id:
        return {
            "line_key": line_key,
            "purchase_no": order.purchase_no,
            "product_goods_no": order.product_goods_no,
            "order_qty": order.batch_pur_qty,
            "bom_model_id": None,
            "material_status": "unbound",
            "message": "未绑定 BOM，请在工程模块绑定或确认料号一致",
            "lines": [],
        }
    result = compute_kitting(db, order.bom_model_id, order.batch_pur_qty or 0)
    result["line_key"] = line_key
    result["purchase_no"] = order.purchase_no
    result["product_goods_no"] = order.product_goods_no
    return result


def compute_kitting_status_only(
    db: Session,
    bom_model_id: int,
    order_qty: float,
    *,
    stock_map: Optional[dict[str, WarehouseMaterial]] = None,
    bom: Optional[BomModel] = None,
) -> dict:
    """列表用：只算 ready/partial/shortage，不算贴装面别（更快，只读）。"""
    if bom is None:
        bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
    if not bom:
        return {"material_status": "unknown", "ready_count": 0, "partial_count": 0, "shortage_count": 0, "total_lines": 0}
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == bom_model_id, BomLine.is_active.is_(True))
        .all()
    )
    if stock_map is None:
        stock_map = _warehouse_stock_map(db, bom.customer_id or "")
    model_code = bom.model_code or ""
    customer_id = bom.customer_id or ""
    purchase_no = getattr(bom, "purchase_no", None) or ""
    shortage_count = 0
    partial_count = 0
    ready_count = 0
    for line in lines:
        rule_qty = get_rule_qty_per(
            line.material_code,
            customer_id,
            parent_code=model_code,
            purchase_no=purchase_no,
        )
        qty_per = float(rule_qty) if rule_qty is not None else float(line.qty_per or 0)
        required = round(qty_per * float(order_qty or 0), 4)
        stock_info = resolve_group_stock(
            line.material_code,
            stock_map,
            customer_id,
            parent_code=model_code,
            purchase_no=purchase_no,
        )
        mat = stock_map.get(normalize_code(line.material_code))
        own_stock = float(stock_info.get("own_stock_qty") or 0)
        substitutes = build_substitute_details(
            line.material_code,
            stock_map,
            customer_id=customer_id,
            parent_code=model_code,
            purchase_no=purchase_no,
        )
        excel_in = float(mat.excel_in_qty) if mat and mat.excel_in_qty is not None else None
        excel_demand = float(mat.excel_demand_qty) if mat and mat.excel_demand_qty is not None else None
        kit_eval = evaluate_kitting_line(
            required,
            own_stock,
            substitutes,
            excel_in_qty=excel_in,
            excel_demand_qty=excel_demand,
        )
        line_status = str(kit_eval.get("status") or "shortage")
        if line_status == "ready":
            ready_count += 1
        elif line_status == "partial":
            partial_count += 1
        else:
            shortage_count += 1
    total = len(lines)
    if not total:
        overall = "unknown"
    elif shortage_count == 0 and partial_count == 0:
        overall = "ready"
    elif shortage_count == total:
        overall = "shortage"
    else:
        overall = "partial"
    return {
        "material_status": overall,
        "ready_count": ready_count,
        "partial_count": partial_count,
        "shortage_count": shortage_count,
        "total_lines": total,
    }


def batch_live_order_kit_summaries(db: Session, orders: list) -> dict[str, dict]:
    """
    订单列表齐套：按 BOM×库存现算（只读，不写 srm_orders，不影响扫码）。
    返回 line_key -> {customer_kit_status, customer_kit_status_label, material_status, collected_sets_qty}
    """
    from customer_kitting import (
        CUSTOMER_KIT_LABELS,
        is_order_fulfillment_done,
    )

    out: dict[str, dict] = {}
    if not orders:
        return out

    bom_ids = sorted({int(o.bom_model_id) for o in orders if getattr(o, "bom_model_id", None)})
    bom_by_id: dict[int, BomModel] = {}
    if bom_ids:
        for b in db.query(BomModel).filter(BomModel.id.in_(bom_ids)).all():
            bom_by_id[int(b.id)] = b

    stock_cache: dict[str, dict[str, WarehouseMaterial]] = {}

    for order in orders:
        lk = (getattr(order, "line_key", None) or "").strip()
        if not lk:
            continue
        order_qty = float(order.batch_pur_qty or order.output_qty or 0)
        if is_order_fulfillment_done(
            order_qty=order_qty,
            delivery_qty=getattr(order, "delivery_qty", None),
            un_delivery_qty=getattr(order, "un_delivery_qty", None),
            receive_qty=getattr(order, "receive_qty", None),
            is_completed=bool(getattr(order, "is_completed", False)),
        ):
            out[lk] = {
                "customer_kit_status": "ready",
                "customer_kit_status_label": CUSTOMER_KIT_LABELS.get("ready", "已齐套"),
                "material_status": "ready",
                "collected_sets_qty": order_qty if order_qty > 0 else float(order.collected_sets_qty or 0),
            }
            continue

        bom_id = getattr(order, "bom_model_id", None)
        if not bom_id:
            out[lk] = {
                "customer_kit_status": "unbound",
                "customer_kit_status_label": CUSTOMER_KIT_LABELS.get("unbound", "未绑BOM"),
                "material_status": "unbound",
                "collected_sets_qty": 0.0,
            }
            continue

        bom = bom_by_id.get(int(bom_id))
        if not bom:
            out[lk] = {
                "customer_kit_status": "unbound",
                "customer_kit_status_label": CUSTOMER_KIT_LABELS.get("unbound", "未绑BOM"),
                "material_status": "unbound",
                "collected_sets_qty": 0.0,
            }
            continue

        cid = (bom.customer_id or "").strip()
        if cid not in stock_cache:
            stock_cache[cid] = _warehouse_stock_map(db, cid)
        try:
            kit = compute_kitting_status_only(
                db,
                int(bom_id),
                order_qty,
                stock_map=stock_cache[cid],
                bom=bom,
            )
        except Exception:
            out[lk] = {
                "customer_kit_status": "na",
                "customer_kit_status_label": "—",
                "material_status": "unknown",
                "collected_sets_qty": float(order.collected_sets_qty or 0),
            }
            continue

        ms = kit.get("material_status") or "unknown"
        if ms == "ready":
            kit_status = "ready"
        elif ms == "partial":
            kit_status = "partial"
        elif ms == "shortage":
            kit_status = "unkit"
        elif ms == "unbound":
            kit_status = "unbound"
        else:
            kit_status = "na"

        # 估算可齐套套数（列表提示用）
        collected = float(order.collected_sets_qty or 0)
        if ms == "ready" and order_qty > 0:
            collected = order_qty
        elif ms == "partial" and order_qty > 0:
            total = int(kit.get("total_lines") or 0)
            ready = int(kit.get("ready_count") or 0)
            if total > 0 and ready > 0:
                collected = round(order_qty * ready / total, 4)

        out[lk] = {
            "customer_kit_status": kit_status,
            "customer_kit_status_label": CUSTOMER_KIT_LABELS.get(kit_status, kit_status or "—"),
            "material_status": ms,
            "collected_sets_qty": collected,
        }
    return out


def refresh_customer_material_kitting(
    db: Session,
    customer_id: str,
    kitting_alerts: Optional[list] = None,
) -> int:
    """EMS 齐套客户（如恩玖）：按 BOM×库存刷新 material_status / collected_sets_qty。"""
    from customer_kitting import apply_ems_material_kitting_state, is_customer_kit_ems

    if not is_customer_kit_ems(customer_id):
        return 0

    from customer_kitting import is_order_fulfillment_done

    auto_bind_orders(db, customer_id)
    orders = (
        db.query(SrmOrder)
        .filter(SrmOrder.customer_id == customer_id, SrmOrder.is_completed.is_(False))
        .all()
    )
    updated = 0
    for order in orders:
        order_qty = float(order.batch_pur_qty or order.output_qty or 0)
        # 已出完：直接冻结已齐套，跳过 BOM×库存（库存已被领用会误报未齐套）
        if is_order_fulfillment_done(
            order_qty=order_qty,
            delivery_qty=getattr(order, "delivery_qty", None),
            un_delivery_qty=getattr(order, "un_delivery_qty", None),
            receive_qty=getattr(order, "receive_qty", None),
            is_completed=False,
        ):
            if apply_ems_material_kitting_state(order, {"material_status": "ready"}, kitting_alerts):
                updated += 1
            continue
        try:
            kit = order_kitting(db, order.line_key)
        except Exception:
            continue
        if apply_ems_material_kitting_state(order, kit, kitting_alerts):
            updated += 1
    return updated


def update_bom_line(db: Session, line_id: int, data: dict) -> BomLine:
    row = db.query(BomLine).filter(BomLine.id == line_id).first()
    if not row:
        raise ValueError("BOM 行不存在")
    for key in ("material_code", "material_name", "spec", "unit", "position", "process", "remark", "seq"):
        if key in data and data[key] is not None:
            setattr(row, key, data[key])
    if "qty_per" in data and data["qty_per"] is not None:
        row.qty_per = float(data["qty_per"])
    bom = db.query(BomModel).filter(BomModel.id == row.bom_model_id).first()
    if bom:
        bom.updated_at = datetime.utcnow()
    return row


def update_bom_mount_profile(db: Session, model_id: int, mount_profile_override: Optional[str]) -> BomModel:
    bom = db.query(BomModel).filter(BomModel.id == model_id, BomModel.is_active.is_(True)).first()
    if not bom:
        raise ValueError("机型不存在")
    value = (mount_profile_override or "").strip()
    if value and value not in ("dip_only", "smt_only", "mixed"):
        raise ValueError("贴装画像无效，可选：空(自动)、dip_only、smt_only、mixed")
    bom.mount_profile_override = value or None
    bom.updated_at = datetime.utcnow()
    return bom


def clear_bom_model(db: Session, model_id: int) -> dict:
    """清除已导入的 BOM 明细（软删记录，解绑订单），便于重新导入。"""
    bom = db.query(BomModel).filter(BomModel.id == model_id).first()
    if not bom:
        raise ValueError("BOM 不存在")
    if not bom.is_active and (bom.line_count or 0) == 0:
        raise ValueError("该订单 BOM 已清除")
    model_code = bom.model_code
    internal_code = bom.internal_code
    purchase_no = bom.purchase_no or ""
    cleared = (
        db.query(BomLine).filter(BomLine.bom_model_id == model_id).delete(synchronize_session=False)
    )
    db.query(SrmOrder).filter(SrmOrder.bom_model_id == model_id).update(
        {SrmOrder.bom_model_id: None},
        synchronize_session=False,
    )
    bom.line_count = 0
    bom.folder_name = None
    bom.source_file = None
    bom.source_mtime = None
    bom.mount_profile_override = None
    bom.synced_at = None
    bom.is_active = False
    # 清除后重置审核，避免「删了再导」被旧 approved + 自动审吞掉待办
    bom.content_hash = ""
    bom.import_snapshot_json = None
    bom.eng_review_status = "pending_import"
    bom.eng_review_message = "BOM 已清除，请重新导入后再送审"
    bom.eng_submitter = None
    bom.eng_submitted_at = None
    bom.eng_reviewed_by = None
    bom.eng_reviewed_at = None
    bom.updated_at = datetime.utcnow()
    db.query(EngReviewInbox).filter(
        EngReviewInbox.bom_model_id == model_id,
        EngReviewInbox.status != "done",
    ).update({"status": "done"}, synchronize_session=False)
    label = f"{model_code}" + (f" / {purchase_no}" if purchase_no else "")
    return {
        "message": f"已清除 BOM {label}",
        "bom_model_id": model_id,
        "model_code": model_code,
        "internal_code": internal_code,
        "purchase_no": purchase_no,
        "cleared_lines": int(cleared or 0),
    }


def _purge_order_scoped_assets(
    db: Session,
    *,
    internal_code: str,
    purchase_no: str,
    bom_model_id: Optional[int] = None,
) -> dict:
    """仅清除订单级坐标/Gerber/位号图，不动机型级共用资料。"""
    ic = (internal_code or "").strip().upper()
    pn = (purchase_no or "").strip()
    bom_id = int(bom_model_id) if bom_model_id else None
    removed = {"placement": 0, "gerber": 0, "refmap": 0}
    if not ic or not pn:
        return removed

    def _match(row) -> bool:
        if bom_id and row.bom_model_id == bom_id:
            return True
        return (row.purchase_no or "").strip() == pn

    for row in (
        db.query(PcbPlacementFile)
        .filter(PcbPlacementFile.internal_code == ic)
        .all()
    ):
        if _match(row):
            delete_placement_file(db, row.id)
            removed["placement"] += 1

    for row in (
        db.query(PcbGerberPackage)
        .filter(PcbGerberPackage.internal_code == ic)
        .all()
    ):
        if _match(row):
            delete_gerber_package(db, row.id)
            removed["gerber"] += 1

    for row in (
        db.query(PcbRefmapFile)
        .filter(PcbRefmapFile.internal_code == ic)
        .all()
    ):
        if _match(row):
            delete_refmap_store_file(row.internal_code, row.model_code, row.id, row.file_name or "")
            delete_refmap_file(db, row.id)
            removed["refmap"] += 1

    return removed


def delete_engineering_order(
    db: Session,
    *,
    internal_code: str,
    purchase_no: str,
    model_code: str = "",
    bom_model_id: Optional[int] = None,
    hidden_by: str = "",
) -> dict:
    """从工程资料删除订单：清 BOM/待审/订单级资产，并从目录隐藏。不删 SRM 在制单。"""
    ic = (internal_code or "").strip().upper()
    pn = (purchase_no or "").strip()
    mc = (model_code or "").strip()

    bom: Optional[BomModel] = None
    if bom_model_id:
        bom = db.query(BomModel).filter(BomModel.id == int(bom_model_id)).first()
        if bom and not ic:
            ic = (bom.internal_code or "").strip().upper()
        if bom and not mc:
            mc = (bom.model_code or "").strip()
        if bom and not pn:
            pn = (bom.purchase_no or "").strip()
    if not pn:
        raise ValueError("缺少采购订单号")
    if not ic:
        raise ValueError("缺少内部代码")
    if not bom:
        candidates = (
            db.query(BomModel)
            .filter(BomModel.internal_code == ic, BomModel.purchase_no == pn)
            .order_by(BomModel.id.desc())
            .all()
        )
        if mc:
            needle = normalize_code(mc)
            exact = [r for r in candidates if normalize_code(r.model_code) == needle]
            bom = exact[0] if exact else (candidates[0] if len(candidates) == 1 else None)
            if not bom and candidates:
                bom = next(
                    (
                        r
                        for r in candidates
                        if needle in normalize_code(r.model_code)
                        or normalize_code(r.model_code) in needle
                    ),
                    candidates[0],
                )
        elif len(candidates) == 1:
            bom = candidates[0]
        elif candidates:
            bom = max(candidates, key=lambda r: r.updated_at or r.synced_at or datetime.min)

    if bom and not mc:
        mc = (bom.model_code or "").strip()
    mc_norm = normalize_code(mc)

    cleared_lines = 0
    bom_id = bom.id if bom else None
    if bom and (bom.is_active or (bom.line_count or 0) > 0):
        cleared = clear_bom_model(db, bom.id)
        cleared_lines = int(cleared.get("cleared_lines") or 0)
        bom_id = bom.id
    elif bom:
        db.query(SrmOrder).filter(SrmOrder.bom_model_id == bom.id).update(
            {SrmOrder.bom_model_id: None},
            synchronize_session=False,
        )

    inbox_deleted = 0
    if bom_id:
        inbox_deleted += (
            db.query(EngReviewInbox)
            .filter(EngReviewInbox.bom_model_id == bom_id)
            .delete(synchronize_session=False)
            or 0
        )
    inbox_deleted += (
        db.query(EngReviewInbox)
        .filter(
            EngReviewInbox.internal_code == ic,
            EngReviewInbox.purchase_no == pn,
        )
        .delete(synchronize_session=False)
        or 0
    )

    assets = _purge_order_scoped_assets(
        db, internal_code=ic, purchase_no=pn, bom_model_id=bom_id
    )

    hide = (
        db.query(EngOrderHide)
        .filter(
            EngOrderHide.internal_code == ic,
            EngOrderHide.purchase_no == pn,
            EngOrderHide.model_code_norm == mc_norm,
        )
        .first()
    )
    if not hide:
        hide = EngOrderHide(
            internal_code=ic,
            purchase_no=pn,
            model_code=mc,
            model_code_norm=mc_norm,
            hidden_by=(hidden_by or "").strip() or None,
        )
        db.add(hide)
    else:
        hide.model_code = mc or hide.model_code
        hide.hidden_by = (hidden_by or "").strip() or hide.hidden_by
        hide.created_at = datetime.utcnow()

    label = f"{mc or '—'}/{pn}"
    return {
        "message": f"已从工程资料删除订单 {label}（SRM 在制单仍保留）",
        "internal_code": ic,
        "purchase_no": pn,
        "model_code": mc,
        "bom_model_id": bom_id,
        "cleared_lines": cleared_lines,
        "inbox_deleted": int(inbox_deleted or 0),
        "assets_removed": assets,
    }


def _catalog_matches_keyword(item: dict, keyword: str) -> bool:
    from model_linkage import a116_code_variants

    kw = keyword.strip()
    if not kw:
        return True
    like = kw.lower()
    fields = [
        item.get("model_code") or "",
        item.get("model_name") or "",
        item.get("folder_name") or "",
        item.get("remark") or "",
        item.get("model_spec") or "",
        item.get("purchase_no") or "",
    ]
    for value in fields:
        if like in str(value).lower():
            return True
    for variant in a116_code_variants(kw):
        v = variant.lower()
        for value in fields:
            if v in str(value).lower():
                return True
    return False


def list_bom_order_catalog(
    db: Session,
    internal_code: str = "",
    customer_id: str = "",
    keyword: str = "",
) -> list[dict]:
    """在制订单维度：一采购订单号一行，各自确认 BOM。"""
    customers = get_engineering_customers()
    if internal_code:
        ic = internal_code.strip().upper()
        customers = [c for c in customers if c.get("internal_code") == ic]
    if customer_id:
        cid = customer_id.strip()
        customers = [c for c in customers if c.get("customer_id") == cid]
    if not customers:
        return []

    srm_by_cid: dict[str, dict] = {}
    for c in customers:
        cid = (c.get("customer_id") or "").strip()
        if cid:
            srm_by_cid[cid] = c
        for alias in c.get("customer_id_aliases") or []:
            alias = str(alias).strip()
            if alias:
                srm_by_cid[alias] = c
        # 手工录单客户名哈希 ID（如 华夏恒泰 → manual_36fec023）
        try:
            from manual_order_service import manual_customer_id

            name = (c.get("name") or "").strip()
            if name:
                srm_by_cid[manual_customer_id(name)] = c
        except Exception:
            pass
    if not srm_by_cid:
        return []

    hide_ics = {(c.get("internal_code") or "").strip().upper() for c in customers if c.get("internal_code")}
    hidden_keys: set[tuple[str, str, str]] = set()
    if hide_ics:
        for row in (
            db.query(EngOrderHide)
            .filter(EngOrderHide.internal_code.in_(list(hide_ics)))
            .all()
        ):
            hidden_keys.add(
                (
                    (row.internal_code or "").strip().upper(),
                    (row.purchase_no or "").strip(),
                    (row.model_code_norm or normalize_code(row.model_code)).strip(),
                )
            )

    # 只灌胶等工序：免工程资料导入，不进目录/待导入
    from process_route_service import eng_docs_exempt_model_norms

    exempt_norms: set[str] = set()
    for ic0 in hide_ics or {""}:
        exempt_norms |= eng_docs_exempt_model_norms(db, internal_code=ic0)
    if not hide_ics:
        exempt_norms |= eng_docs_exempt_model_norms(db, internal_code="")

    orders = (
        db.query(SrmOrder)
        .filter(
            SrmOrder.is_completed.is_(False),
            SrmOrder.customer_id.in_(list(srm_by_cid.keys())),
            SrmOrder.product_goods_no.isnot(None),
            SrmOrder.product_goods_no != "",
            SrmOrder.purchase_no.isnot(None),
            SrmOrder.purchase_no != "",
        )
        .all()
    )

    # (internal_code, purchase_no, model_norm) → aggregate
    groups: dict[tuple[str, str, str], dict] = {}
    for order in orders:
        eng = srm_by_cid.get(order.customer_id)
        if not eng:
            continue
        ic = eng["internal_code"]
        if is_engineering_fee_order(
            internal_code=ic,
            customer_id=order.customer_id or "",
            order_type_name=order.order_type_name,
            product_goods_no=order.product_goods_no,
            product_goods_name=order.product_goods_name,
        ):
            continue
        pn = (order.purchase_no or "").strip()
        norm = normalize_code(order.product_goods_no)
        if not pn or not norm:
            continue
        if (ic, pn, norm) in hidden_keys:
            continue
        if norm in exempt_norms:
            continue
        key = (ic, pn, norm)
        group = groups.get(key)
        if not group:
            group = {
                "internal_code": ic,
                "customer_id": order.customer_id,
                "customer_name": eng.get("name") or order.customer_name or "",
                "model_code": str(order.product_goods_no).strip(),
                "model_name": order.product_goods_name,
                "model_spec": order.product_spec,
                "purchase_no": pn,
                "line_key": order.line_key,
                "order_count": 0,
                "order_qty": 0.0,
                "latest_purchase_date": None,
                "_bound_bom_ids": set(),
            }
            groups[key] = group
        group["order_count"] += 1
        group["order_qty"] = round(group["order_qty"] + float(order.batch_pur_qty or 0), 4)
        if order.product_goods_name:
            group["model_name"] = order.product_goods_name
        if order.product_spec:
            group["model_spec"] = order.product_spec
        # 代表性 line_key：保留第一条；若已有绑定优先带绑定的
        if order.bom_model_id:
            group["_bound_bom_ids"].add(order.bom_model_id)
            group["line_key"] = order.line_key
        purchase_date = order.purchase_date or order.doc_date
        if purchase_date and (
            not group["latest_purchase_date"] or purchase_date > group["latest_purchase_date"]
        ):
            group["latest_purchase_date"] = purchase_date

    # 采购单 → 订单料号列表（过滤误绑空 BOM 壳）
    po_order_codes: dict[tuple[str, str], list[str]] = {}
    for order in orders:
        eng = srm_by_cid.get(order.customer_id)
        if not eng:
            continue
        ic_o = eng["internal_code"]
        pn_o = (order.purchase_no or "").strip()
        code_o = str(order.product_goods_no or "").strip()
        if pn_o and code_o:
            bucket = po_order_codes.setdefault((ic_o, pn_o), [])
            if code_o not in bucket:
                bucket.append(code_o)

    bom_q = db.query(BomModel).filter(BomModel.is_active.is_(True), BomModel.line_count > 0)
    if internal_code:
        bom_q = bom_q.filter(BomModel.internal_code == internal_code.strip().upper())
    if customer_id:
        bom_q = bom_q.filter(BomModel.customer_id == customer_id.strip())
    order_boms: dict[tuple[str, str, str], BomModel] = {}
    order_boms_by_pn: dict[tuple[str, str], list[BomModel]] = {}
    for bom in bom_q.all():
        pn = (bom.purchase_no or "").strip()
        if not pn:
            continue
        order_boms[(bom.internal_code, pn, normalize_code(bom.model_code))] = bom
        order_boms_by_pn.setdefault((bom.internal_code, pn), []).append(bom)

    # 已清除 BOM（待重新导入）：保留目录行，含已结案订单
    shell_q = db.query(BomModel).filter(
        BomModel.purchase_no.isnot(None),
        BomModel.purchase_no != "",
        BomModel.line_count <= 0,
    )
    if internal_code:
        shell_q = shell_q.filter(BomModel.internal_code == internal_code.strip().upper())
    if customer_id:
        shell_q = shell_q.filter(BomModel.customer_id == customer_id.strip())
    from bom_excel import _strict_order_model_match

    for bom in shell_q.all():
        pn = (bom.purchase_no or "").strip()
        if not pn:
            continue
        if (bom.line_count or 0) <= 0:
            po_codes = po_order_codes.get((bom.internal_code, pn)) or []
            mc = (bom.model_code or "").strip()
            if po_codes and mc and not _strict_order_model_match(po_codes, mc):
                continue
        key = (bom.internal_code, pn, normalize_code(bom.model_code))
        if key not in order_boms:
            order_boms[key] = bom
            order_boms_by_pn.setdefault((bom.internal_code, pn), []).append(bom)

    # 已导入 BOM：订单结案后仍保留在工程资料目录（资料库，不因 is_completed 隐藏）
    missing_bom_keys = [k for k in order_boms if k not in groups]
    if missing_bom_keys:
        pns = list({k[1] for k in missing_bom_keys})
        hist_orders = (
            db.query(SrmOrder)
            .filter(
                SrmOrder.customer_id.in_(list(srm_by_cid.keys())),
                SrmOrder.purchase_no.in_(pns),
                SrmOrder.product_goods_no.isnot(None),
                SrmOrder.product_goods_no != "",
            )
            .all()
        )
        hist_lists: dict[tuple[str, str, str], list[SrmOrder]] = {}
        for order in hist_orders:
            eng = srm_by_cid.get(order.customer_id)
            if not eng:
                continue
            ic_h = eng["internal_code"]
            if is_engineering_fee_order(
                internal_code=ic_h,
                customer_id=order.customer_id or "",
                order_type_name=order.order_type_name,
                product_goods_no=order.product_goods_no,
                product_goods_name=order.product_goods_name,
            ):
                continue
            pn_h = (order.purchase_no or "").strip()
            norm_h = normalize_code(order.product_goods_no)
            if not pn_h or not norm_h:
                continue
            key_h = (ic_h, pn_h, norm_h)
            if key_h in order_boms and key_h not in groups:
                hist_lists.setdefault(key_h, []).append(order)

        eng_by_ic = {
            (c.get("internal_code") or "").strip().upper(): c
            for c in customers
            if c.get("internal_code")
        }
        for key in missing_bom_keys:
            ic, pn, norm = key
            if (ic, pn, norm) in hidden_keys or norm in exempt_norms:
                continue
            bom = order_boms[key]
            eng = eng_by_ic.get(ic)
            if not eng:
                continue
            matched = hist_lists.get(key) or []
            group = {
                "internal_code": ic,
                "customer_id": (bom.customer_id or eng.get("customer_id") or "").strip(),
                "customer_name": (bom.customer_name or eng.get("name") or "").strip(),
                "model_code": str(bom.model_code).strip() or norm,
                "model_name": bom.model_name,
                "model_spec": bom.model_spec,
                "purchase_no": pn,
                "line_key": None,
                "order_count": 0,
                "order_qty": 0.0,
                "latest_purchase_date": None,
                "_bound_bom_ids": {bom.id},
                "is_order_completed": True,
            }
            for order in matched:
                group["order_count"] += 1
                group["order_qty"] = round(
                    group["order_qty"] + float(order.batch_pur_qty or 0), 4
                )
                if order.product_goods_name:
                    group["model_name"] = order.product_goods_name
                if order.product_spec:
                    group["model_spec"] = order.product_spec
                if order.bom_model_id:
                    group["_bound_bom_ids"].add(order.bom_model_id)
                    group["line_key"] = order.line_key
                purchase_date = order.purchase_date or order.doc_date
                if purchase_date and (
                    not group["latest_purchase_date"]
                    or purchase_date > group["latest_purchase_date"]
                ):
                    group["latest_purchase_date"] = purchase_date
            if matched and not group["line_key"]:
                group["line_key"] = matched[0].line_key
            if matched:
                group["is_order_completed"] = all(o.is_completed for o in matched)
            groups[key] = group

    results: list[dict] = []
    # 同采购订单号下有几个机型行：>1 时禁止「单 BOM 盲挂」，必须各自导入或有料号证据
    pn_model_group_count: dict[tuple[str, str], int] = {}
    for ic, pn, _norm in groups:
        key_pn = (ic, pn)
        pn_model_group_count[key_pn] = pn_model_group_count.get(key_pn, 0) + 1

    for key, group in groups.items():
        bom = order_boms.get(key)
        order_code = normalize_code(group["model_code"])
        # 恩玖等：仅当「同单只有一个机型行」且订单料号与 BOM 主件不一致（如 99…↔03…）时，
        # 才允许按订单号回退；同单多机型必须各自导入，禁止共用一份 BOM。
        if not bom:
            candidates = order_boms_by_pn.get((group["internal_code"], group["purchase_no"])) or []
            scored: list[tuple[int, BomModel]] = []
            for c in candidates:
                score = _bom_catalog_match_score(order_code, c)
                if score > 0:
                    scored.append((score, c))
            if scored:
                scored.sort(
                    key=lambda x: (x[0], x[1].updated_at or x[1].synced_at or datetime.min),
                    reverse=True,
                )
                bom = scored[0][1]
            elif (
                len(candidates) == 1
                and pn_model_group_count.get((group["internal_code"], group["purchase_no"]), 0) == 1
            ):
                bom = candidates[0]
        # 若订单已绑定，优先用绑定的 BOM（需订单专属，且料号可对上或同单仅一机型）
        if not bom and group["_bound_bom_ids"]:
            sole_model_on_po = (
                pn_model_group_count.get((group["internal_code"], group["purchase_no"]), 0) == 1
            )
            for bid in group["_bound_bom_ids"]:
                candidate = db.query(BomModel).filter(BomModel.id == bid).first()
                if not candidate or (candidate.purchase_no or "").strip() != group["purchase_no"]:
                    continue
                if sole_model_on_po or _bom_catalog_match_score(order_code, candidate) > 0:
                    bom = candidate
                    break
        imported = bool(bom and (bom.line_count or 0) > 0)
        item = {
            "id": bom.id if bom else None,
            "internal_code": group["internal_code"],
            "customer_id": group["customer_id"],
            "customer_name": group["customer_name"],
            "model_code": group["model_code"],
            "model_name": group["model_name"] or (bom.model_name if bom else None),
            "model_spec": group["model_spec"] or (bom.model_spec if bom else None),
            "folder_name": bom.folder_name if bom else None,
            "remark": bom.remark if bom else None,
            "purchase_no": group["purchase_no"],
            "line_key": group["line_key"],
            "line_count": bom.line_count if bom else 0,
            "bom_status": "imported" if imported else "pending",
            "bom_confirmed": imported,
            "bom_model_id": bom.id if bom else None,
            "eng_review_status": (bom.eng_review_status or "") if bom else "",
            "eng_review_message": (bom.eng_review_message or None) if bom else None,
            "mount_profile_override": (bom.mount_profile_override or None) if bom else None,
            "order_count": group["order_count"],
            "order_qty": group["order_qty"],
            "latest_purchase_date": group["latest_purchase_date"],
            "is_order_completed": bool(group.get("is_order_completed")),
            "is_active": True,
            "synced_at": bom.synced_at if bom else None,
            "updated_at": bom.updated_at if bom else None,
        }
        if not _catalog_matches_keyword(item, keyword):
            continue
        results.append(item)

    # 按客户汇总替代规则数（订单号 + 机型料号，避免同机型串单）
    from collections import defaultdict
    from substitution_service import count_rules_by_order_parent, normalize_code as sub_norm

    by_cid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in results:
        cid = (row.get("customer_id") or "").strip()
        pn = (row.get("purchase_no") or "").strip()
        mc = (row.get("model_code") or "").strip()
        if cid and pn and mc:
            by_cid[cid].append((pn, mc))
    count_maps: dict[str, dict[tuple[str, str], int]] = {}
    for cid, pairs in by_cid.items():
        count_maps[cid] = count_rules_by_order_parent(db, cid, pairs)
    for row in results:
        cid = (row.get("customer_id") or "").strip()
        pn = (row.get("purchase_no") or "").strip()
        key = (pn, sub_norm(row.get("model_code")))
        n = int((count_maps.get(cid) or {}).get(key) or 0)
        row["substitution_rule_count"] = n
        row["has_substitution"] = n > 0

    results.sort(
        key=lambda row: (
            row.get("internal_code") or "",
            row.get("model_code") or "",
            row.get("purchase_no") or "",
        )
    )
    return results


def list_bom_model_catalog(
    db: Session,
    internal_code: str = "",
    customer_id: str = "",
    keyword: str = "",
) -> list[dict]:
    """机型维度目录（客户资料/工装等共用）；同机型多订单时优先展示机型级或任一带 BOM 的记录。"""
    customers = get_engineering_customers()
    if internal_code:
        ic = internal_code.strip().upper()
        customers = [c for c in customers if c.get("internal_code") == ic]
    if customer_id:
        cid = customer_id.strip()
        customers = [c for c in customers if c.get("customer_id") == cid]
    if not customers:
        return []

    srm_by_cid: dict[str, dict] = {}
    for c in customers:
        cid = (c.get("customer_id") or "").strip()
        if cid:
            srm_by_cid[cid] = c
        for alias in c.get("customer_id_aliases") or []:
            alias = str(alias).strip()
            if alias:
                srm_by_cid[alias] = c
    order_groups: dict[tuple[str, str], dict] = {}

    orders = (
        db.query(SrmOrder)
        .filter(
            SrmOrder.is_completed.is_(False),
            SrmOrder.customer_id.in_(list(srm_by_cid.keys()) or ["__none__"]),
            SrmOrder.product_goods_no.isnot(None),
            SrmOrder.product_goods_no != "",
        )
        .all()
    )
    for order in orders:
        eng = srm_by_cid.get(order.customer_id)
        if not eng:
            continue
        ic = eng["internal_code"]
        if is_engineering_fee_order(
            internal_code=ic,
            customer_id=order.customer_id or "",
            order_type_name=order.order_type_name,
            product_goods_no=order.product_goods_no,
            product_goods_name=order.product_goods_name,
        ):
            continue
        norm = normalize_code(order.product_goods_no)
        if not norm:
            continue
        key = (ic, norm)
        group = order_groups.setdefault(
            key,
            {
                "internal_code": ic,
                "customer_id": order.customer_id,
                "customer_name": eng.get("name") or order.customer_name or "",
                "model_code": str(order.product_goods_no).strip(),
                "model_name": None,
                "model_spec": None,
                "order_count": 0,
                "order_qty": 0.0,
                "latest_purchase_date": None,
            },
        )
        group["order_count"] += 1
        group["order_qty"] = round(group["order_qty"] + float(order.batch_pur_qty or 0), 4)
        if order.product_goods_name:
            group["model_name"] = order.product_goods_name
        if order.product_spec:
            group["model_spec"] = order.product_spec
        purchase_date = order.purchase_date or order.doc_date
        if purchase_date and (
            not group["latest_purchase_date"] or purchase_date > group["latest_purchase_date"]
        ):
            group["latest_purchase_date"] = purchase_date

    bom_q = db.query(BomModel).filter(BomModel.is_active.is_(True))
    if internal_code:
        bom_q = bom_q.filter(BomModel.internal_code == internal_code.strip().upper())
    if customer_id:
        bom_q = bom_q.filter(BomModel.customer_id == customer_id.strip())

    bom_by_key: dict[tuple[str, str], BomModel] = {}
    for bom in bom_q.all():
        key = (bom.internal_code, normalize_code(bom.model_code))
        prev = bom_by_key.get(key)
        if prev is None:
            bom_by_key[key] = bom
            continue
        # 优先机型级（无订单号）；否则保留行数更多的
        prev_pn = (prev.purchase_no or "").strip()
        cur_pn = (bom.purchase_no or "").strip()
        if prev_pn and not cur_pn:
            bom_by_key[key] = bom
        elif bool(prev_pn) == bool(cur_pn) and (bom.line_count or 0) > (prev.line_count or 0):
            bom_by_key[key] = bom

    results: list[dict] = []
    for key in set(order_groups.keys()) | set(bom_by_key.keys()):
        order_info = order_groups.get(key)
        bom = bom_by_key.get(key)
        if bom:
            imported = bom.line_count > 0
            item = {
                "id": bom.id,
                "internal_code": bom.internal_code,
                "customer_id": bom.customer_id,
                "customer_name": bom.customer_name or (order_info or {}).get("customer_name", ""),
                "model_code": bom.model_code,
                "model_name": bom.model_name or (order_info or {}).get("model_name"),
                "model_spec": bom.model_spec or (order_info or {}).get("model_spec"),
                "folder_name": bom.folder_name,
                "remark": bom.remark,
                "purchase_no": bom.purchase_no or "",
                "line_count": bom.line_count,
                "bom_status": "imported" if imported else "pending",
                "order_count": (order_info or {}).get("order_count", 0),
                "order_qty": (order_info or {}).get("order_qty", 0.0),
                "latest_purchase_date": (order_info or {}).get("latest_purchase_date"),
                "is_active": bom.is_active,
                "synced_at": bom.synced_at,
                "updated_at": bom.updated_at,
            }
        elif order_info:
            item = {
                "id": None,
                "internal_code": order_info["internal_code"],
                "customer_id": order_info["customer_id"],
                "customer_name": order_info["customer_name"],
                "model_code": order_info["model_code"],
                "model_name": order_info["model_name"],
                "model_spec": order_info["model_spec"],
                "folder_name": None,
                "remark": None,
                "purchase_no": "",
                "line_count": 0,
                "bom_status": "pending",
                "order_count": order_info["order_count"],
                "order_qty": order_info["order_qty"],
                "latest_purchase_date": order_info["latest_purchase_date"],
                "is_active": True,
                "synced_at": None,
                "updated_at": None,
            }
        else:
            continue

        if not _catalog_matches_keyword(item, keyword):
            continue
        results.append(item)

    def sort_key(row: dict) -> tuple:
        return (
            row.get("internal_code") or "",
            row.get("model_code") or "",
        )

    results.sort(key=sort_key)
    return results


def _index_placement_files(db: Session, internal_code: str = "") -> dict[tuple[str, str], PcbPlacementFile]:
    q = db.query(PcbPlacementFile)
    if internal_code:
        q = q.filter(PcbPlacementFile.internal_code == internal_code.strip().upper())
    grouped: dict[tuple[str, str], list[PcbPlacementFile]] = {}
    for row in q.all():
        key = (row.internal_code, normalize_code(row.model_code))
        grouped.setdefault(key, []).append(row)
    indexed: dict[tuple[str, str], PcbPlacementFile] = {}
    for key, items in grouped.items():
        picked = pick_canonical_placement(items)
        if picked:
            indexed[key] = picked
    return indexed


def _index_gerber_packages(db: Session, internal_code: str = "") -> dict[tuple[str, str], PcbGerberPackage]:
    q = db.query(PcbGerberPackage)
    if internal_code:
        q = q.filter(PcbGerberPackage.internal_code == internal_code.strip().upper())
    grouped: dict[tuple[str, str], list[PcbGerberPackage]] = {}
    for row in q.all():
        key = (row.internal_code, normalize_code(row.model_code))
        grouped.setdefault(key, []).append(row)
    indexed: dict[tuple[str, str], PcbGerberPackage] = {}
    for key, items in grouped.items():
        picked = pick_canonical_gerber(items)
        if picked:
            indexed[key] = picked
    return indexed


def _placement_asset_status(row: Optional[PcbPlacementFile]) -> str:
    if not row or (row.line_count or 0) <= 0 or row.file_format == "pending":
        return "pending"
    from placement_audit import is_placement_usable

    if row.audit_status == "failed":
        return "failed"
    if is_placement_usable(row.audit_status):
        return "imported"
    return "pending"


def _gerber_asset_status(row: Optional[PcbGerberPackage]) -> str:
    if not row or (row.file_count or 0) <= 0:
        return "pending"
    from gerber_audit import is_gerber_usable

    if row.audit_status == "failed":
        return "failed"
    if is_gerber_usable(row.audit_status):
        return "imported"
    return "pending"


def _index_refmap_files(db: Session, internal_code: str = "") -> dict[tuple[str, str], PcbRefmapFile]:
    try:
        q = db.query(PcbRefmapFile)
        if internal_code:
            q = q.filter(PcbRefmapFile.internal_code == internal_code.strip().upper())
        grouped: dict[tuple[str, str], list[PcbRefmapFile]] = {}
        for row in q.all():
            key = (row.internal_code, normalize_code(row.model_code))
            grouped.setdefault(key, []).append(row)
        indexed: dict[tuple[str, str], PcbRefmapFile] = {}
        for key, items in grouped.items():
            picked = pick_canonical_refmap(items)
            if picked:
                indexed[key] = picked
        return indexed
    except Exception:
        return {}


def _refmap_asset_status(row: Optional[PcbRefmapFile]) -> str:
    if not row or not row.file_name or (row.file_size or 0) <= 0:
        return "pending"
    from refmap_audit import is_refmap_usable

    if row.audit_status == "failed":
        return "failed"
    if is_refmap_usable(row.audit_status):
        return "imported"
    return "pending"


def build_customer_asset_row(db: Session, bom: BomModel, *, bom_row: Optional[dict] = None) -> dict:
    """单笔订单 BOM 的坐标/Gerber/位号图状态。"""
    from eng_asset_scope import find_assets_for_bom

    place, pkg, refmap = find_assets_for_bom(db, bom)
    place_status = _placement_asset_status(place)
    gerber_status = _gerber_asset_status(pkg)
    refmap_status = _refmap_asset_status(refmap)
    meta = bom_row or {}
    return {
        "internal_code": bom.internal_code,
        "model_code": bom.model_code,
        "model_name": bom.model_name or meta.get("model_name"),
        "purchase_no": (bom.purchase_no or meta.get("purchase_no") or ""),
        "bom_model_id": bom.id,
        "bom_status": meta.get("bom_status")
        or ("imported" if (bom.line_count or 0) > 0 else "pending"),
        "order_count": meta.get("order_count", 0),
        "content_hash": (bom.content_hash or ""),
        "placement_file_id": place.id if place else None,
        "placement_line_count": place.line_count if place else 0,
        "placement_format": place.file_format if place else "",
        "placement_audit_status": (place.audit_status if place else "") or "pending",
        "placement_audit_message": (place.audit_message if place else "") or "",
        "placement_asset_status": place_status,
        "gerber_package_id": pkg.id if pkg else None,
        "gerber_file_count": pkg.file_count if pkg else 0,
        "gerber_audit_status": (pkg.audit_status if pkg else "") or "pending",
        "gerber_audit_message": (pkg.audit_message if pkg else "") or "",
        "gerber_asset_status": gerber_status,
        "refmap_file_id": refmap.id if refmap else None,
        "refmap_file_name": (refmap.file_name if refmap else "") or "",
        "refmap_file_size": refmap.file_size if refmap else 0,
        "refmap_page_count": refmap.page_count if refmap else 0,
        "refmap_audit_status": (refmap.audit_status if refmap else "") or "pending",
        "refmap_audit_message": (refmap.audit_message if refmap else "") or "",
        "refmap_asset_status": refmap_status,
    }


def get_customer_asset_for_bom(db: Session, bom_model_id: int) -> dict:
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id, BomModel.is_active.is_(True)).first()
    if not bom:
        raise ValueError("订单 BOM 不存在")
    return build_customer_asset_row(db, bom)


def list_customer_assets_catalog(
    db: Session,
    internal_code: str = "",
    keyword: str = "",
) -> list[dict]:
    """按在制订单列出资料状态（菲利斯等同机型多订单时不可折叠成一行）。"""
    results: list[dict] = []
    for bom_row in list_bom_order_catalog(db, internal_code, "", keyword):
        bom_id = bom_row.get("id")
        bom = db.query(BomModel).filter(BomModel.id == bom_id).first() if bom_id else None
        if bom:
            results.append(build_customer_asset_row(db, bom, bom_row=bom_row))
            continue
        results.append(
            {
                "internal_code": bom_row["internal_code"],
                "model_code": bom_row["model_code"],
                "model_name": bom_row.get("model_name"),
                "purchase_no": bom_row.get("purchase_no") or "",
                "bom_model_id": None,
                "bom_status": bom_row.get("bom_status") or "pending",
                "order_count": bom_row.get("order_count", 0),
                "content_hash": "",
                "placement_file_id": None,
                "placement_line_count": 0,
                "placement_format": "",
                "placement_audit_status": "pending",
                "placement_audit_message": "",
                "placement_asset_status": "pending",
                "gerber_package_id": None,
                "gerber_file_count": 0,
                "gerber_audit_status": "pending",
                "gerber_audit_message": "",
                "gerber_asset_status": "pending",
                "refmap_file_id": None,
                "refmap_file_name": "",
                "refmap_file_size": 0,
                "refmap_page_count": 0,
                "refmap_audit_status": "pending",
                "refmap_audit_message": "",
                "refmap_asset_status": "pending",
            }
        )
    return results


def list_placement_catalog(
    db: Session,
    internal_code: str = "",
    keyword: str = "",
) -> list[dict]:
    from placement_sync import _file_to_dict

    placements = _index_placement_files(db, internal_code)
    results: list[dict] = []
    for bom in list_bom_model_catalog(db, internal_code, "", keyword):
        key = (bom["internal_code"], normalize_code(bom["model_code"]))
        place = placements.get(key)
        if place:
            item = _file_to_dict(place)
            item["bom_model_id"] = place.bom_model_id or bom.get("id")
            item["asset_status"] = _placement_asset_status(place)
            if item["asset_status"] == "imported":
                item["status"] = "ready"
            elif item["asset_status"] == "failed":
                item["status"] = "failed"
            else:
                item["status"] = "pending"
        else:
            item = {
                "id": None,
                "bom_model_id": bom.get("id"),
                "internal_code": bom["internal_code"],
                "model_code": bom["model_code"],
                "board_name": None,
                "folder_name": None,
                "source_file": "",
                "file_format": "pending",
                "units": "mm",
                "line_count": 0,
                "source": "pending",
                "status": "pending",
                "audit_status": "pending",
                "audit_message": "",
                "asset_status": "pending",
                "synced_at": None,
                "updated_at": None,
            }
        item["model_name"] = bom.get("model_name")
        item["bom_status"] = bom.get("bom_status")
        item["order_count"] = bom.get("order_count", 0)
        results.append(item)
    return results


def list_gerber_catalog(
    db: Session,
    internal_code: str = "",
    keyword: str = "",
) -> list[dict]:
    from gerber_sync import _pkg_to_dict

    packages = _index_gerber_packages(db, internal_code)
    results: list[dict] = []
    for bom in list_bom_model_catalog(db, internal_code, "", keyword):
        key = (bom["internal_code"], normalize_code(bom["model_code"]))
        pkg = packages.get(key)
        if pkg:
            item = _pkg_to_dict(pkg)
            item["bom_model_id"] = pkg.bom_model_id or bom.get("id")
            item["asset_status"] = _gerber_asset_status(pkg)
            if item["asset_status"] == "imported":
                item["status"] = "ready"
            elif item["asset_status"] == "failed":
                item["status"] = "failed"
            else:
                item["status"] = "pending"
        else:
            item = {
                "id": None,
                "bom_model_id": bom.get("id"),
                "internal_code": bom["internal_code"],
                "model_code": bom["model_code"],
                "package_name": "",
                "folder_name": None,
                "source_path": "",
                "file_count": 0,
                "source": "pending",
                "status": "pending",
                "audit_status": "pending",
                "audit_message": "",
                "asset_status": "pending",
                "synced_at": None,
                "updated_at": None,
            }
        item["model_name"] = bom.get("model_name")
        item["bom_status"] = bom.get("bom_status")
        item["order_count"] = bom.get("order_count", 0)
        results.append(item)
    return results


def engineering_config() -> dict:
    from config import get_process_detail_file_path, get_substitution_file_path
    from pathlib import Path

    # 工程 BOM / 坐标 / Gerber 仅人工导入，不暴露共享盘路径
    sub_path = Path(get_substitution_file_path())
    proc_path = Path(get_process_detail_file_path())
    return {
        "share_path": "",
        "share_accessible": False,
        "assets_share_sync_enabled": False,
        "assets_import_mode": "manual",
        "substitution_file_path": str(sub_path),
        "substitution_file_accessible": sub_path.is_file(),
        "process_detail_file_path": str(proc_path),
        "process_detail_file_accessible": proc_path.is_file(),
        "customers": get_engineering_customers(),
    }


def get_model_process_map(db: Session, model_id: int) -> dict:
    bom = db.query(BomModel).filter(BomModel.id == model_id, BomModel.is_active.is_(True)).first()
    if not bom:
        raise ValueError("机型不存在")
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == model_id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    groups: dict[str, list] = {}
    for line in lines:
        key = (line.process or "").strip() or "未分工序"
        groups.setdefault(key, []).append(
            {
                "seq": line.seq,
                "material_code": line.material_code,
                "material_name": line.material_name,
                "spec": line.spec,
                "qty_per": line.qty_per,
                "unit": line.unit,
                "position": line.position,
                "process": line.process,
            }
        )
    processes = [
        {"process": name, "line_count": len(items), "lines": items}
        for name, items in sorted(groups.items(), key=lambda x: (x[0] == "未分工序", x[0]))
    ]
    return {
        "bom_model_id": bom.id,
        "model_code": bom.model_code,
        "model_name": bom.model_name,
        "internal_code": bom.internal_code,
        "customer_name": bom.customer_name,
        "process_count": len(processes),
        "total_lines": len(lines),
        "processes": processes,
    }
