"""物料管制单：建档、确认改订单专属 BOM、取消回滚。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from engineering_service import normalize_code
from models import (
    BomLine,
    BomModel,
    MaterialControl,
    MaterialControlChange,
    MaterialControlGroup,
    MaterialControlOrder,
    SrmOrder,
)

CONTROL_UPLOAD_DIR = Path(__file__).parent / "static" / "uploads" / "controls"


def _now() -> datetime:
    return datetime.utcnow()


def _order_dict(o: MaterialControlOrder) -> dict:
    return {
        "id": o.id,
        "group_id": o.group_id,
        "purchase_no": o.purchase_no,
        "line_key": o.line_key,
        "order_qty": float(o.order_qty or 0),
        "control_qty": float(o.control_qty or 0),
    }


def _change_dict(c: MaterialControlChange) -> dict:
    return {
        "id": c.id,
        "group_id": c.group_id,
        "control_qty": float(getattr(c, "control_qty", 0) or 0),
        "remove_code": c.remove_code,
        "remove_qty": c.remove_qty,
        "remove_refdes": c.remove_refdes,
        "add_code": c.add_code,
        "add_qty": c.add_qty,
        "add_refdes": c.add_refdes,
        "remark": c.remark,
    }


def control_to_dict(db: Session, row: MaterialControl) -> dict:
    groups = (
        db.query(MaterialControlGroup)
        .filter(MaterialControlGroup.control_id == row.id)
        .order_by(MaterialControlGroup.sort_order.asc(), MaterialControlGroup.id.asc())
        .all()
    )
    orders = (
        db.query(MaterialControlOrder)
        .filter(MaterialControlOrder.control_id == row.id)
        .order_by(MaterialControlOrder.id.asc())
        .all()
    )
    changes = (
        db.query(MaterialControlChange)
        .filter(MaterialControlChange.control_id == row.id)
        .order_by(MaterialControlChange.id.asc())
        .all()
    )
    group_payload = []
    for g in groups:
        group_payload.append(
            {
                "id": g.id,
                "model_code": g.model_code,
                "sort_order": g.sort_order,
                "orders": [_order_dict(o) for o in orders if o.group_id == g.id],
                "changes": [_change_dict(c) for c in changes if c.group_id == g.id],
            }
        )
    # 无分组的遗留子行挂到第一组或单独展示
    orphan_orders = [o for o in orders if not o.group_id]
    orphan_changes = [c for c in changes if not c.group_id]
    if orphan_orders or orphan_changes:
        if group_payload:
            group_payload[0]["orders"].extend(_order_dict(o) for o in orphan_orders)
            group_payload[0]["changes"].extend(_change_dict(c) for c in orphan_changes)
        else:
            group_payload.append(
                {
                    "id": None,
                    "model_code": row.model_code or "",
                    "sort_order": 0,
                    "orders": [_order_dict(o) for o in orphan_orders],
                    "changes": [_change_dict(c) for c in orphan_changes],
                }
            )
    flat_orders = [_order_dict(o) for o in orders]
    flat_changes = [_change_dict(c) for c in changes]
    return {
        "id": row.id,
        "control_no": row.control_no,
        "model_code": row.model_code,
        "control_type": row.control_type,
        "reason": row.reason,
        "ecn_no": row.ecn_no,
        "attachment_path": row.attachment_path,
        "attachment_name": row.attachment_name,
        "status": row.status,
        "created_by": row.created_by,
        "confirmed_by": row.confirmed_by,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "cancelled_by": row.cancelled_by,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "groups": group_payload,
        "orders": flat_orders,
        "changes": flat_changes,
    }


def list_controls(db: Session, status: str = "", keyword: str = "") -> list[dict]:
    q = db.query(MaterialControl)
    if status:
        q = q.filter(MaterialControl.status == status)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (MaterialControl.control_no.like(like))
            | (MaterialControl.model_code.like(like))
            | (MaterialControl.ecn_no.like(like))
        )
    rows = q.order_by(MaterialControl.id.desc()).limit(200).all()
    return [control_to_dict(db, r) for r in rows]


def get_control(db: Session, control_id: int) -> MaterialControl:
    row = db.query(MaterialControl).filter(MaterialControl.id == control_id).first()
    if not row:
        raise ValueError("管制单不存在")
    return row


def get_controls_for_purchase(
    db: Session, purchase_no: str, model_code: str = ""
) -> list[dict]:
    pn = (purchase_no or "").strip()
    if not pn:
        return []

    mc_norm = normalize_code(model_code)
    q = (
        db.query(MaterialControlOrder.control_id, MaterialControlGroup.model_code, MaterialControl.model_code)
        .join(MaterialControl, MaterialControl.id == MaterialControlOrder.control_id)
        .outerjoin(
            MaterialControlGroup,
            MaterialControlGroup.id == MaterialControlOrder.group_id,
        )
        .filter(MaterialControlOrder.purchase_no == pn)
    )
    ids: list[int] = []
    seen: set[int] = set()
    for cid, g_mc, c_mc in q.all():
        if mc_norm:
            hit = normalize_code(g_mc or c_mc)
            if hit != mc_norm:
                continue
        if cid not in seen:
            seen.add(cid)
            ids.append(cid)
    if not ids:
        return []
    rows = (
        db.query(MaterialControl)
        .filter(MaterialControl.id.in_(ids))
        .order_by(MaterialControl.id.desc())
        .all()
    )
    return [control_to_dict(db, r) for r in rows]


def _normalize_groups_payload(data: dict) -> list[dict]:
    """统一 groups / 旧版 orders+changes+model_code 入参。"""
    groups = data.get("groups")
    if groups:
        out = []
        for g in groups:
            mc = str(g.get("model_code") or "").strip()
            orders = g.get("orders") or []
            changes = g.get("changes") or []
            if not mc:
                continue
            out.append({"model_code": mc, "orders": orders, "changes": changes})
        return out
    # 兼容旧单机型
    model_code = str(data.get("model_code") or "").strip()
    orders = data.get("orders") or []
    changes = data.get("changes") or []
    if model_code or orders or changes:
        return [{"model_code": model_code, "orders": orders, "changes": changes}]
    return []


def _replace_groups(db: Session, control_id: int, groups: list[dict]) -> str:
    """重写分组及子行，返回机型汇总字符串。"""
    db.query(MaterialControlOrder).filter(MaterialControlOrder.control_id == control_id).delete(
        synchronize_session=False
    )
    db.query(MaterialControlChange).filter(MaterialControlChange.control_id == control_id).delete(
        synchronize_session=False
    )
    db.query(MaterialControlGroup).filter(MaterialControlGroup.control_id == control_id).delete(
        synchronize_session=False
    )
    model_codes: list[str] = []
    for idx, g in enumerate(groups):
        mc = str(g.get("model_code") or "").strip()
        if not mc:
            raise ValueError("每个分组须填写机型")
        orders = g.get("orders") or []
        changes = g.get("changes") or []
        if not orders:
            raise ValueError(f"机型 {mc} 请至少关联一个工单")
        if not changes:
            raise ValueError(f"机型 {mc} 请至少填写一条换料")
        grp = MaterialControlGroup(control_id=control_id, model_code=mc, sort_order=idx)
        db.add(grp)
        db.flush()
        model_codes.append(mc)
        change_rows: list[dict] = []
        for c in changes:
            remove_code = str(c.get("remove_code") or "").strip()
            add_code = str(c.get("add_code") or "").strip()
            if not remove_code and not add_code:
                continue
            change_rows.append(c)
        batch_total = sum(float(c.get("control_qty") or 0) for c in change_rows)

        for o in orders:
            pn = str(o.get("purchase_no") or "").strip()
            if not pn:
                continue
            so = (
                db.query(SrmOrder)
                .filter(SrmOrder.purchase_no == pn)
                .order_by(SrmOrder.id.desc())
                .first()
            )
            order_qty = float(o.get("order_qty") or 0)
            if order_qty <= 0 and so is not None:
                order_qty = float(so.batch_pur_qty or so.output_qty or 0)
            control_qty = float(o.get("control_qty") or 0)
            if control_qty <= 0 and batch_total > 0:
                control_qty = batch_total
            db.add(
                MaterialControlOrder(
                    control_id=control_id,
                    group_id=grp.id,
                    purchase_no=pn,
                    line_key=so.line_key if so else None,
                    order_qty=order_qty,
                    control_qty=control_qty,
                )
            )
        for c in change_rows:
            remove_code = str(c.get("remove_code") or "").strip()
            add_code = str(c.get("add_code") or "").strip()
            db.add(
                MaterialControlChange(
                    control_id=control_id,
                    group_id=grp.id,
                    control_qty=float(c.get("control_qty") or 0),
                    remove_code=remove_code,
                    remove_qty=float(c.get("remove_qty") or 0),
                    remove_refdes=(c.get("remove_refdes") or None),
                    add_code=add_code,
                    add_qty=float(c.get("add_qty") or 0),
                    add_refdes=(c.get("add_refdes") or None),
                    remark=(c.get("remark") or None),
                )
            )
    if not model_codes:
        raise ValueError("请至少填写一个机型分组")
    return "、".join(model_codes)


def create_control(
    db: Session,
    data: dict,
    *,
    created_by: str = "",
) -> MaterialControl:
    control_no = str(data.get("control_no") or "").strip()
    if not control_no:
        raise ValueError("请填写管制单号")
    exists = db.query(MaterialControl).filter(MaterialControl.control_no == control_no).first()
    if exists:
        raise ValueError(f"管制单号已存在：{control_no}")
    groups = _normalize_groups_payload(data)
    if not groups:
        raise ValueError("请至少填写一个机型分组（含工单与换料）")

    row = MaterialControl(
        control_no=control_no,
        model_code="",
        control_type=str(data.get("control_type") or "PCBA管制").strip() or "PCBA管制",
        reason=(data.get("reason") or None),
        ecn_no=(str(data.get("ecn_no") or "").strip() or None),
        status="draft",
        created_by=created_by or None,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(row)
    db.flush()
    row.model_code = _replace_groups(db, row.id, groups)
    db.flush()
    return row


def update_draft(
    db: Session,
    control_id: int,
    data: dict,
) -> MaterialControl:
    row = get_control(db, control_id)
    if row.status != "draft":
        raise ValueError("仅草稿状态可编辑")
    if "control_no" in data and data["control_no"] is not None:
        new_no = str(data["control_no"]).strip()
        if not new_no:
            raise ValueError("管制单号不能为空")
        clash = (
            db.query(MaterialControl)
            .filter(MaterialControl.control_no == new_no, MaterialControl.id != control_id)
            .first()
        )
        if clash:
            raise ValueError(f"管制单号已存在：{new_no}")
        row.control_no = new_no
    if "control_type" in data and data["control_type"] is not None:
        row.control_type = str(data["control_type"]).strip() or row.control_type
    if "reason" in data:
        row.reason = data["reason"] or None
    if "ecn_no" in data:
        row.ecn_no = str(data["ecn_no"] or "").strip() or None
    if "groups" in data or "orders" in data or "changes" in data or "model_code" in data:
        groups = _normalize_groups_payload(data)
        if not groups:
            raise ValueError("请至少填写一个机型分组（含工单与换料）")
        row.model_code = _replace_groups(db, row.id, groups)
    row.updated_at = _now()
    db.flush()
    return row


def set_attachment(db: Session, control_id: int, rel_path: str, filename: str) -> MaterialControl:
    row = get_control(db, control_id)
    if row.status == "cancelled":
        raise ValueError("已取消的管制单不可上传附件")
    row.attachment_path = rel_path
    row.attachment_name = filename
    row.updated_at = _now()
    db.flush()
    return row


def _find_order_bom(db: Session, model_code: str, purchase_no: str) -> Optional[BomModel]:
    needle = normalize_code(model_code)
    pn = (purchase_no or "").strip()
    cands = (
        db.query(BomModel)
        .filter(BomModel.is_active.is_(True), BomModel.purchase_no == pn)
        .all()
    )
    for bom in cands:
        if normalize_code(bom.model_code) == needle:
            return bom
    return None


def _apply_bom_change(db: Session, bom: BomModel, control: MaterialControl, change: MaterialControlChange) -> None:
    remove_code = normalize_code(change.remove_code)
    template_line: Optional[BomLine] = None
    if remove_code:
        lines = (
            db.query(BomLine)
            .filter(BomLine.bom_model_id == bom.id, BomLine.is_active.is_(True))
            .all()
        )
        hit = False
        for line in lines:
            if normalize_code(line.material_code) != remove_code:
                continue
            if template_line is None:
                template_line = line
            line.is_active = False
            line.control_id = control.id
            line.control_prev_qty = float(line.qty_per or 0)
            if change.remove_refdes and not line.position:
                line.position = change.remove_refdes
            rem = f"管制停用 {control.control_no}"
            line.remark = f"{(line.remark or '').strip()} · {rem}".strip(" ·")
            hit = True
        if not hit:
            raise ValueError(
                f"订单 {bom.purchase_no} 的 BOM 中未找到待删除料号 {change.remove_code}"
            )

    add_code = (change.add_code or "").strip()
    if add_code:
        max_sort = (
            db.query(BomLine)
            .filter(BomLine.bom_model_id == bom.id)
            .count()
        )
        # 备注常见格式：品名 / 规格
        remark = (change.remark or "").strip()
        add_name = None
        add_spec = remark or None
        if " / " in remark:
            left, right = remark.split(" / ", 1)
            add_name = left.strip() or None
            add_spec = right.strip() or None
        elif remark and not remark.startswith("管制"):
            add_name = remark
        if template_line is not None:
            add_name = add_name or template_line.material_name
            add_spec = add_spec or template_line.spec
        db.add(
            BomLine(
                bom_model_id=bom.id,
                material_code=add_code,
                material_name=add_name,
                spec=add_spec,
                unit=(template_line.unit if template_line and template_line.unit else "PCS"),
                qty_per=float(change.add_qty or 0) or float(change.remove_qty or 0) or 1,
                position=change.add_refdes or change.remove_refdes
                or (template_line.position if template_line else None),
                process=(template_line.process if template_line else None),
                remark=f"管制新增 {control.control_no}",
                sort_order=max_sort + 1,
                is_active=True,
                source="control",
                control_id=control.id,
            )
        )


def _refresh_order_controlled_flags(db: Session, purchase_nos: set[str]) -> None:
    """按「采购单号 + 机型」刷新 is_controlled，避免同 PO 下无关机型被整单打标。"""
    db.flush()
    for pn in purchase_nos:
        if not pn:
            continue
        rows = (
            db.query(
                MaterialControlGroup.model_code,
                MaterialControl.model_code,
            )
            .select_from(MaterialControlOrder)
            .join(MaterialControl, MaterialControl.id == MaterialControlOrder.control_id)
            .outerjoin(
                MaterialControlGroup,
                MaterialControlGroup.id == MaterialControlOrder.group_id,
            )
            .filter(
                MaterialControlOrder.purchase_no == pn,
                MaterialControl.status == "active",
            )
            .all()
        )
        active_models = {
            normalize_code(g_mc or c_mc)
            for g_mc, c_mc in rows
            if normalize_code(g_mc or c_mc)
        }
        for so in db.query(SrmOrder).filter(SrmOrder.purchase_no == pn).all():
            so.is_controlled = normalize_code(so.product_goods_no) in active_models


def _is_partial_batch_control(orders: list, changes: list) -> bool:
    """
    分批管制：工单总量大于本批管制套数（如 10000 里抽 3×500），
    或存在多条带不同管制数量的换料行 → 不能整单套全部换料。
    """
    order_qty = 0.0
    for o in orders:
        oq = float(getattr(o, "order_qty", 0) or 0)
        cq = float(getattr(o, "control_qty", 0) or 0)
        order_qty = max(order_qty, oq, cq)
    batch_qtys = [float(getattr(c, "control_qty", 0) or 0) for c in changes]
    batch_qtys = [q for q in batch_qtys if q > 0]
    if not batch_qtys:
        return False
    # 多批不同换料且都标了管制数量 → 分批
    if len(changes) > 1 and len(batch_qtys) >= 2:
        return True
    max_batch = max(batch_qtys)
    if order_qty > 0 and max_batch < order_qty * 0.98:
        return True
    # 多批合计明显小于工单总量
    if order_qty > 0 and sum(batch_qtys) < order_qty * 0.98 and len(batch_qtys) >= 1:
        # 单批且等于总量时不算；单批小于总量算分批
        if len(changes) == 1 and abs(batch_qtys[0] - order_qty) < 1:
            return False
        return True
    return False


def _partial_summary(orders: list, changes: list) -> str:
    oq = 0.0
    for o in orders:
        oq = max(oq, float(getattr(o, "order_qty", 0) or 0), float(getattr(o, "control_qty", 0) or 0))
    parts = []
    for c in changes:
        bq = float(getattr(c, "control_qty", 0) or 0)
        ref = (c.remove_refdes or c.add_refdes or "").strip() or "—"
        parts.append(f"{int(bq) if bq == int(bq) else bq}套({ref})")
    total_b = sum(float(getattr(c, "control_qty", 0) or 0) for c in changes)
    oq_s = int(oq) if oq == int(oq) else oq
    tb_s = int(total_b) if total_b == int(total_b) else total_b
    return f"工单总量 {oq_s}，分批管制 {' + '.join(parts)}，合计 {tb_s}（非整单换料）"


def _find_open_order(db: Session, purchase_no: str) -> Optional[SrmOrder]:
    """订单列表中的在制单（未结案）。"""
    pn = (purchase_no or "").strip()
    if not pn:
        return None
    return (
        db.query(SrmOrder)
        .filter(SrmOrder.purchase_no == pn, SrmOrder.is_completed.is_(False))
        .order_by(SrmOrder.id.desc())
        .first()
    )


def confirm_control(db: Session, control_id: int, *, confirmed_by: str = "") -> MaterialControl:
    """确认管制：按机型分组，只处理在制工单并用该组机型改专属 BOM。"""
    row = get_control(db, control_id)
    if row.status != "draft":
        raise ValueError("仅草稿状态可确认生效")
    groups = (
        db.query(MaterialControlGroup)
        .filter(MaterialControlGroup.control_id == row.id)
        .order_by(MaterialControlGroup.sort_order.asc(), MaterialControlGroup.id.asc())
        .all()
    )
    if not groups:
        raise ValueError("管制单无机组分组，请重新编辑保存")

    skipped_inactive: list[str] = []
    skipped_no_bom: list[str] = []
    applied: list[str] = []
    record_only: list[str] = []

    for grp in groups:
        orders = (
            db.query(MaterialControlOrder)
            .filter(
                MaterialControlOrder.control_id == row.id,
                MaterialControlOrder.group_id == grp.id,
            )
            .all()
        )
        changes = (
            db.query(MaterialControlChange)
            .filter(
                MaterialControlChange.control_id == row.id,
                MaterialControlChange.group_id == grp.id,
            )
            .all()
        )
        if not orders or not changes:
            continue

        partial = _is_partial_batch_control(orders, changes)
        if partial:
            # 分批管制：从总量中抽出多批分别换料，禁止把全部换料套到整份订单 BOM
            tip = _partial_summary(orders, changes)
            for o in orders:
                pn = (o.purchase_no or "").strip()
                so = _find_open_order(db, pn)
                if not so:
                    skipped_inactive.append(pn)
                    continue
                # 工单总量优先取订单实数
                if so.batch_pur_qty and float(o.order_qty or 0) <= 0:
                    o.order_qty = float(so.batch_pur_qty)
                o.line_key = so.line_key
                record_only.append(f"{pn}←{grp.model_code}")
            if tip:
                row.reason = f"{(row.reason or '').strip()} · 【分批备案】{tip}".strip(" ·")
            continue

        for o in orders:
            pn = (o.purchase_no or "").strip()
            so = _find_open_order(db, pn)
            if not so:
                skipped_inactive.append(pn)
                continue
            if so.batch_pur_qty and float(o.order_qty or 0) <= 0:
                o.order_qty = float(so.batch_pur_qty)
            bom = _find_order_bom(db, grp.model_code, pn)
            if not bom or (bom.line_count or 0) <= 0:
                skipped_no_bom.append(f"{pn}({grp.model_code})")
                continue
            for ch in changes:
                _apply_bom_change(db, bom, row, ch)
            bom.line_count = (
                db.query(BomLine)
                .filter(BomLine.bom_model_id == bom.id, BomLine.is_active.is_(True))
                .count()
            )
            bom.updated_at = _now()
            o.line_key = so.line_key
            if not so.bom_model_id:
                so.bom_model_id = bom.id
            applied.append(f"{pn}←{grp.model_code}")

    if not applied and not record_only:
        if skipped_no_bom:
            raise ValueError(
                "在制订单尚无专属 BOM，请先到工程导入后再确认管制：" + "、".join(skipped_no_bom)
            )
        raise ValueError(
            "管制单关联工单均不在在制订单中（可能已做完），无需确认或请核对订单号"
        )

    row.status = "active"
    row.confirmed_by = confirmed_by or None
    row.confirmed_at = _now()
    row.updated_at = _now()
    notes = []
    if record_only:
        notes.append(
            "分批管制已备案（未改整单 BOM，因非整单换料）：" + "、".join(record_only)
        )
    if skipped_inactive:
        notes.append("已跳过非在制/不存在：" + "、".join(skipped_inactive))
    if skipped_no_bom:
        notes.append("在制但无专属BOM未改料表：" + "、".join(skipped_no_bom))
    if notes:
        tip = "；".join(notes)
        row.reason = f"{(row.reason or '').strip()} · {tip}".strip(" ·")
    db.flush()
    apply_pns = {x.split("←")[0] for x in applied} | {x.split("←")[0] for x in record_only}
    skip_pns = set()
    for x in skipped_no_bom:
        skip_pns.add(x.split("(")[0])
    _refresh_order_controlled_flags(db, apply_pns | skip_pns)
    db.flush()
    row._confirm_applied = applied + [f"{x}(分批备案)" for x in record_only]  # type: ignore[attr-defined]
    row._confirm_skipped_inactive = skipped_inactive  # type: ignore[attr-defined]
    row._confirm_skipped_no_bom = skipped_no_bom  # type: ignore[attr-defined]
    return row


def cancel_control(db: Session, control_id: int, *, cancelled_by: str = "") -> MaterialControl:
    row = get_control(db, control_id)
    if row.status == "cancelled":
        raise ValueError("管制单已取消")
    if row.status == "draft":
        orders = (
            db.query(MaterialControlOrder).filter(MaterialControlOrder.control_id == row.id).all()
        )
        purchase_nos = {o.purchase_no for o in orders}
        row.status = "cancelled"
        row.cancelled_by = cancelled_by or None
        row.cancelled_at = _now()
        row.updated_at = _now()
        db.flush()
        _refresh_order_controlled_flags(db, purchase_nos)
        db.flush()
        return row

    # active → 回滚 BOM
    orders = (
        db.query(MaterialControlOrder).filter(MaterialControlOrder.control_id == row.id).all()
    )
    purchase_nos = {o.purchase_no for o in orders}
    touched_boms: set[int] = set()
    # 删除本管制新增行
    added = (
        db.query(BomLine)
        .filter(BomLine.control_id == row.id, BomLine.source == "control")
        .all()
    )
    for line in added:
        touched_boms.add(line.bom_model_id)
        db.delete(line)
    # 恢复停用行
    disabled = (
        db.query(BomLine)
        .filter(
            BomLine.control_id == row.id,
            BomLine.is_active.is_(False),
        )
        .all()
    )
    for line in disabled:
        touched_boms.add(line.bom_model_id)
        line.is_active = True
        if line.control_prev_qty is not None:
            line.qty_per = float(line.control_prev_qty)
        line.control_prev_qty = None
        line.control_id = None
        # 去掉备注中的管制标记（简单处理）
        if line.remark and "管制停用" in line.remark:
            parts = [p.strip() for p in line.remark.split("·") if "管制停用" not in p]
            line.remark = " · ".join(parts) or None

    for bom_id in touched_boms:
        bom = db.query(BomModel).filter(BomModel.id == bom_id).first()
        if bom:
            bom.line_count = (
                db.query(BomLine)
                .filter(BomLine.bom_model_id == bom.id, BomLine.is_active.is_(True))
                .count()
            )
            bom.updated_at = _now()

    row.status = "cancelled"
    row.cancelled_by = cancelled_by or None
    row.cancelled_at = _now()
    row.updated_at = _now()
    db.flush()
    _refresh_order_controlled_flags(db, purchase_nos)
    db.flush()
    return row


def delete_control(db: Session, control_id: int) -> dict:
    """物理删除已取消的管制单及其子表。"""
    row = get_control(db, control_id)
    if row.status != "cancelled":
        raise ValueError("仅「已取消」的管制单可删除；请先撤销")
    orders = (
        db.query(MaterialControlOrder).filter(MaterialControlOrder.control_id == row.id).all()
    )
    purchase_nos = {o.purchase_no for o in orders}
    control_no = row.control_no
    # 子表
    db.query(BomLine).filter(BomLine.control_id == row.id, BomLine.source == "control").delete(
        synchronize_session=False
    )
    db.query(MaterialControlChange).filter(MaterialControlChange.control_id == row.id).delete(
        synchronize_session=False
    )
    db.query(MaterialControlOrder).filter(MaterialControlOrder.control_id == row.id).delete(
        synchronize_session=False
    )
    db.query(MaterialControlGroup).filter(MaterialControlGroup.control_id == row.id).delete(
        synchronize_session=False
    )
    db.delete(row)
    db.flush()
    _refresh_order_controlled_flags(db, purchase_nos)
    db.flush()
    return {"ok": True, "control_no": control_no, "purchase_nos": sorted(purchase_nos)}


def control_nos_by_purchase(db: Session, purchase_nos: list[str]) -> dict[str, list[str]]:
    """进行中(active)管制单号，按采购订单号分组（兼容旧调用；不区分机型）。"""
    summary = control_summary_by_purchase(db, purchase_nos)
    return {pn: info["active_nos"] for pn, info in summary.items() if info["active_nos"]}


def control_summary_by_purchase(db: Session, purchase_nos: list[str]) -> dict[str, dict]:
    """按采购订单号汇总关联管制：active_nos / draft_nos（不区分机型，兼容旧逻辑）。"""
    tree = control_summary_by_purchase_model(db, purchase_nos)
    out: dict[str, dict] = {}
    for pn, by_model in tree.items():
        bucket = out.setdefault(pn, {"active_nos": [], "draft_nos": []})
        for info in by_model.values():
            for key in ("active_nos", "draft_nos"):
                for cno in info.get(key) or []:
                    if cno not in bucket[key]:
                        bucket[key].append(cno)
    return out


def control_summary_by_purchase_model(
    db: Session, purchase_nos: list[str]
) -> dict[str, dict[str, dict]]:
    """
    按 采购订单号 → 机型料号(normalize) 汇总管制。
    返回 { purchase_no: { model_norm: { active_nos, draft_nos } } }
    """
    pns = [p for p in {(x or "").strip() for x in purchase_nos} if p]
    if not pns:
        return {}
    rows = (
        db.query(
            MaterialControlOrder.purchase_no,
            MaterialControl.control_no,
            MaterialControl.status,
            MaterialControlGroup.model_code,
            MaterialControl.model_code,
        )
        .join(MaterialControl, MaterialControl.id == MaterialControlOrder.control_id)
        .outerjoin(
            MaterialControlGroup,
            MaterialControlGroup.id == MaterialControlOrder.group_id,
        )
        .filter(
            MaterialControlOrder.purchase_no.in_(pns),
            MaterialControl.status.in_(("active", "draft")),
        )
        .all()
    )
    out: dict[str, dict[str, dict]] = {}
    for pn, cno, status, g_mc, c_mc in rows:
        model = normalize_code(g_mc or c_mc)
        if not model:
            continue
        by_model = out.setdefault(pn, {})
        bucket = by_model.setdefault(model, {"active_nos": [], "draft_nos": []})
        key = "active_nos" if status == "active" else "draft_nos"
        if cno not in bucket[key]:
            bucket[key].append(cno)
    return out


def purchase_nos_with_controls(db: Session, *, include_draft: bool = True) -> set[str]:
    """有关联管制单（生效/草稿）的采购订单号。"""
    statuses = ("active", "draft") if include_draft else ("active",)
    rows = (
        db.query(MaterialControlOrder.purchase_no)
        .join(MaterialControl, MaterialControl.id == MaterialControlOrder.control_id)
        .filter(MaterialControl.status.in_(statuses))
        .distinct()
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _order_has_control_exists(db: Session, *, include_draft: bool = True):
    """SQL exists：本行采购单号+机型 命中管制分组。"""
    from sqlalchemy import or_

    statuses = ("active", "draft") if include_draft else ("active",)
    return (
        db.query(MaterialControlOrder.id)
        .join(MaterialControl, MaterialControl.id == MaterialControlOrder.control_id)
        .outerjoin(
            MaterialControlGroup,
            MaterialControlGroup.id == MaterialControlOrder.group_id,
        )
        .filter(
            MaterialControlOrder.purchase_no == SrmOrder.purchase_no,
            MaterialControl.status.in_(statuses),
            or_(
                MaterialControlGroup.model_code == SrmOrder.product_goods_no,
                MaterialControl.model_code == SrmOrder.product_goods_no,
            ),
        )
        .correlate(SrmOrder)
        .exists()
    )


EXCEL_HEADERS = [
    "管制单号",
    "机型",
    "类型",
    "原因",
    "ECN",
    "采购订单号",
    "工单总量",
    "本批管制数量",
    "删料号",
    "删用量",
    "删位号",
    "加料号",
    "加用量",
    "加位号",
    "备注",
]


def build_control_template_xlsx() -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "物料管制导入"
    ws.append(EXCEL_HEADERS)
    # 整单管制示例
    ws.append(
        [
            "GZ2026033001",
            "120-200235-09",
            "PCBA管制",
            "停产物料在途工单管制",
            "ECN2026032601",
            "5105-20260224003",
            10000,
            10000,
            "110-100050-00",
            2,
            "U2,U3",
            "110-100138-00",
            2,
            "U2,U3",
            "",
        ]
    )
    # 分批管制示例：同一工单 10000，三批各 500
    ws.append(
        [
            "GZ2026070806",
            "120-300056-00",
            "PCBA管制",
            "替代料管制验证",
            "",
            "5103-20260626091",
            10000,
            500,
            "110-200047-00",
            2,
            "U7,U31",
            "110-200094-00",
            2,
            "U7,U31",
            "从10000中抽500套",
        ]
    )
    ws.append(
        [
            "GZ2026070806",
            "120-300056-00",
            "PCBA管制",
            "替代料管制验证",
            "",
            "5103-20260626091",
            10000,
            500,
            "110-200089-00",
            2,
            "U28,U29",
            "110-200236-00A",
            2,
            "U28,U29",
            "再抽500套",
        ]
    )
    ws.append(
        [
            "GZ2026070806",
            "120-300056-00",
            "PCBA管制",
            "替代料管制验证",
            "",
            "5103-20260626091",
            10000,
            500,
            "110-100073-00",
            1,
            "U33",
            "110-200151-00A",
            1,
            "U33",
            "再抽500套",
        ]
    )
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _cell_float(v) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def import_controls_from_excel(
    db: Session,
    data: bytes,
    *,
    created_by: str = "",
    source_name: str = "",
) -> dict:
    """按管制单号合并；同单不同机型拆成多分组。"""
    from io import BytesIO

    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(data), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel 为空")
    header = [_cell_str(c) for c in rows[0]]
    col = {name: i for i, name in enumerate(header)}
    missing = [h for h in ("管制单号", "机型", "采购订单号") if h not in col]
    if missing:
        raise ValueError("模板缺少列：" + "、".join(missing))

    docs: dict[str, dict] = {}
    for raw in rows[1:]:
        if not raw or all(c is None or str(c).strip() == "" for c in raw):
            continue

        def g(name: str, default=""):
            idx = col.get(name)
            if idx is None or idx >= len(raw):
                return default
            return raw[idx]

        control_no = _cell_str(g("管制单号"))
        model_code = _cell_str(g("机型"))
        purchase_no = _cell_str(g("采购订单号"))
        if not control_no or not model_code or not purchase_no:
            continue
        doc = docs.setdefault(
            control_no,
            {
                "control_no": control_no,
                "control_type": _cell_str(g("类型")) or "PCBA管制",
                "reason": _cell_str(g("原因")) or None,
                "ecn_no": _cell_str(g("ECN")) or None,
                "group_map": {},
            },
        )
        gbucket = doc["group_map"].setdefault(
            model_code,
            {"model_code": model_code, "orders": [], "changes": []},
        )
        # 兼容旧模板「管制数量」= 本批；新模板拆成工单总量 + 本批管制数量
        order_qty = _cell_float(g("工单总量"))
        batch_qty = _cell_float(g("本批管制数量"))
        legacy_qty = _cell_float(g("管制数量"))
        if batch_qty <= 0 and legacy_qty > 0:
            batch_qty = legacy_qty
        if order_qty <= 0 and legacy_qty > 0:
            order_qty = legacy_qty
        gbucket["orders"].append(
            {
                "purchase_no": purchase_no,
                "order_qty": order_qty,
                "control_qty": batch_qty,
            }
        )
        remove_code = _cell_str(g("删料号"))
        add_code = _cell_str(g("加料号"))
        if remove_code or add_code:
            change = {
                "control_qty": batch_qty,
                "remove_code": remove_code,
                "remove_qty": _cell_float(g("删用量")),
                "remove_refdes": _cell_str(g("删位号")) or None,
                "add_code": add_code,
                "add_qty": _cell_float(g("加用量")),
                "add_refdes": _cell_str(g("加位号")) or None,
                "remark": _cell_str(g("备注")) or None,
            }
            if change not in gbucket["changes"]:
                gbucket["changes"].append(change)

    if not docs:
        raise ValueError("未解析到有效行（需含管制单号、机型、采购订单号）")

    created = []
    errors = []
    for control_no, doc in docs.items():
        groups = []
        for mc, gbucket in doc["group_map"].items():
            # 同工单合并：取最大工单总量，合计本批数量
            order_map: dict[str, dict] = {}
            for o in gbucket["orders"]:
                pn = o["purchase_no"]
                if pn not in order_map:
                    order_map[pn] = {
                        "purchase_no": pn,
                        "order_qty": float(o.get("order_qty") or 0),
                        "control_qty": float(o.get("control_qty") or 0),
                    }
                else:
                    order_map[pn]["order_qty"] = max(
                        order_map[pn]["order_qty"], float(o.get("order_qty") or 0)
                    )
                    order_map[pn]["control_qty"] += float(o.get("control_qty") or 0)
            uniq_orders = list(order_map.values())
            if not uniq_orders or not gbucket["changes"]:
                errors.append(f"{control_no}/{mc}: 缺少工单或换料")
                continue
            groups.append(
                {
                    "model_code": mc,
                    "orders": uniq_orders,
                    "changes": gbucket["changes"],
                }
            )
        if not groups:
            continue
        payload = {
            "control_no": control_no,
            "control_type": doc["control_type"],
            "reason": doc["reason"],
            "ecn_no": doc["ecn_no"],
            "groups": groups,
        }
        try:
            row = create_control(db, payload, created_by=created_by)
            if source_name:
                note = f"Excel导入 {source_name}"
                row.reason = f"{(row.reason or '').strip()} · {note}".strip(" ·") if row.reason else note
            created.append(control_to_dict(db, row))
        except ValueError as exc:
            errors.append(f"{control_no}: {exc}")

    if not created and errors:
        raise ValueError("；".join(errors))
    return {
        "created_count": len(created),
        "error_count": len(errors),
        "created": created,
        "errors": errors,
    }
