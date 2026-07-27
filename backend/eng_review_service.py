"""工程资料审核：导入后自动待审，审核员通过/退回。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import BomModel, EngReviewInbox, PcbGerberPackage, PcbPlacementFile, PcbRefmapFile

REVIEW_PENDING = "pending_review"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_IMPORT = "pending_import"


def _find_assets(db: Session, bom: BomModel) -> tuple:
    from eng_asset_scope import find_assets_for_bom

    return find_assets_for_bom(db, bom)


def _asset_summary(db: Session, bom: BomModel) -> str:
    place, gerber, refmap = _find_assets(db, bom)
    parts = [f"BOM {bom.line_count} 行"]
    if place and (place.line_count or 0) > 0:
        parts.append(f"坐标 {place.line_count}")
    else:
        parts.append("坐标未导")
    if gerber and (gerber.file_count or 0) > 0:
        parts.append(f"Gerber {gerber.file_count}")
    else:
        parts.append("Gerber未导")
    if refmap:
        parts.append("位号图已导")
    else:
        parts.append("位号图未导")
    return " · ".join(parts)


def build_review_dossier(db: Session, bom_model_id: int) -> dict:
    """审核工作台：订单/机型档案 + 资料齐套检查清单。"""
    from material_mount_service import load_mount_overrides
    from models import BomLine
    from mount_classification import classify_lines_mount, load_placement_index

    bom = db.query(BomModel).filter(BomModel.id == bom_model_id, BomModel.is_active.is_(True)).first()
    if not bom:
        raise ValueError("机型不存在或已停用")

    place, gerber, refmap = _find_assets(db, bom)
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == bom.id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    total = len(lines)
    mounts = []
    if lines:
        placement_index = load_placement_index(db, bom)
        _, mounts = classify_lines_mount(
            lines,
            placement_index=placement_index,
            profile_override=bom.mount_profile_override,
            master_overrides=load_mount_overrides(db, internal_code=bom.internal_code or ""),
            internal_code=bom.internal_code or "",
        )
    unresolved = sum(1 for m in mounts if not (m.get("mount_type") or "").strip())
    smt = sum(1 for m in mounts if (m.get("mount_type") or "").upper() in ("SMT", "贴片"))
    dip = sum(1 for m in mounts if (m.get("mount_type") or "").upper() in ("DIP", "插件"))
    assy = sum(1 for m in mounts if (m.get("mount_type") or "").upper() in ("ASSY", "装配", "N/A"))

    from config import get_engineering_customer_by_code
    from eng_customer_rules import checklist_for, get_customer_rules, workflow_for

    req = checklist_for(bom.internal_code or "")
    wf = workflow_for(bom.internal_code or "")
    rules = get_customer_rules(bom.internal_code or "")
    eng_cust = get_engineering_customer_by_code(bom.internal_code or "") or {}

    def _check(ready: bool, label: str, detail: str, optional: bool = False) -> dict:
        return {
            "key": label,
            "label": label,
            "ready": ready,
            "optional": optional,
            "status": "ready" if ready else ("optional" if optional else "missing"),
            "detail": detail,
        }

    place_ready = bool(place and (place.line_count or 0) > 0)
    gerber_ready = bool(gerber and (gerber.file_count or 0) > 0)
    refmap_ready = bool(refmap)
    mount_ready = unresolved == 0 and total > 0

    # 纯插件：无贴片料，不强制贴片坐标（手工画像 dip_only，或已全部识别为 DIP 且 SMT=0）
    profile_override = (bom.mount_profile_override or "").strip()
    placement_waived = profile_override == "dip_only" or (
        total > 0 and smt == 0 and dip > 0 and unresolved == 0
    )
    place_check_ready = place_ready or placement_waived
    if place_ready:
        place_detail = f"{place.line_count} 点 · {(place.audit_status or 'pending')}"
    elif profile_override == "dip_only":
        place_detail = "纯插件画像，免贴片坐标"
    elif placement_waived:
        place_detail = "无 SMT 料且贴装已齐，免贴片坐标"
    elif req["placement"]:
        place_detail = "未导入（贴装判定依赖坐标；纯插件请先选贴装画像「纯插件」）"
    else:
        place_detail = "未导入（本客户可选）"

    checklist = [
        _check(total > 0, "BOM 料单", f"{total} 行" if total else "未导入", optional=not req["bom"]),
        _check(
            place_check_ready,
            "贴片坐标",
            place_detail,
            optional=not req["placement"],
        ),
        _check(
            gerber_ready,
            "Gerber 制板",
            f"{gerber.file_count} 文件" if gerber and gerber.file_count else (
                "未导入（本客户必交）" if req["gerber"] else "未导入（可选归档）"
            ),
            optional=not req["gerber"],
        ),
        _check(
            refmap_ready,
            "位号图",
            (refmap.file_name if refmap else "") or (
                "未导入（本客户必交）" if req["refmap"] else "未导入（可选）"
            ),
            optional=not req["refmap"],
        ),
        _check(
            mount_ready or wf["allow_approve_without_mount"],
            "贴装类型",
            (
                f"已识别 {total - unresolved}/{total} · SMT {smt} · DIP {dip} · 装配 {assy}"
                if total
                else "无明细"
            )
            if not wf["allow_approve_without_mount"]
            else (
                f"已识别 {total - unresolved}/{total}（本客户允许未全识别通过）"
                if total
                else "无明细"
            ),
            optional=not req["mount_resolved"],
        ),
    ]

    status = (bom.eng_review_status or "").strip() or REVIEW_PENDING
    required_checks = [c for c in checklist if not c["optional"]]
    assets_ok = all(c["ready"] for c in required_checks if c["label"] != "贴装类型")
    mount_step_ok = mount_ready or wf["allow_approve_without_mount"] or not req["mount_resolved"]
    return {
        "bom_model_id": bom.id,
        "internal_code": bom.internal_code or "",
        "customer_id": bom.customer_id or "",
        "customer_name": bom.customer_name or "",
        "model_code": bom.model_code or "",
        "model_name": bom.model_name or "",
        "purchase_no": bom.purchase_no or "",
        "line_count": total,
        "eng_review_status": status,
        "eng_review_message": bom.eng_review_message or _asset_summary(db, bom),
        "eng_submitter": bom.eng_submitter or "",
        "eng_submitted_at": bom.eng_submitted_at.isoformat() if bom.eng_submitted_at else None,
        "eng_reviewed_by": bom.eng_reviewed_by or "",
        "eng_reviewed_at": bom.eng_reviewed_at.isoformat() if bom.eng_reviewed_at else None,
        "checklist": checklist,
        "checklist_policy": {
            **req,
            "placement_waived": placement_waived,
            "mount_profile_override": profile_override,
        },
        "customer_rules": {
            "bom_parse_profile": rules.get("bom_parse_profile"),
            "bom_folder": eng_cust.get("bom_folder"),
            "assets_scope": (rules.get("assets_scope") or "model"),
            "workflow": wf,
        },
        "mount_stats": {
            "total": total,
            "unresolved": unresolved,
            "smt": smt,
            "dip": dip,
            "assy": assy,
        },
        "mount_profile_override": profile_override,
        "workflow": [
            {"step": 1, "title": "核对订单与机型", "done": True},
            {
                "step": 2,
                "title": "确认资料齐套",
                "done": assets_ok,
            },
            {"step": 3, "title": "核对贴装/面别", "done": mount_step_ok and total > 0},
            {"step": 4, "title": "审核通过或退回", "done": status == REVIEW_APPROVED},
        ],
    }


def submit_bom_for_review(
    db: Session,
    bom_model_id: int,
    *,
    submitter: str,
    event_type: str = "submit",
    note: str = "",
) -> Optional[BomModel]:
    """导入成功后调用：标记待审并写入审核员收件箱。"""
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
    if not bom or not bom.is_active:
        return None
    if (bom.line_count or 0) <= 0:
        bom.eng_review_status = REVIEW_IMPORT
        return bom

    summary = _asset_summary(db, bom)
    if note:
        summary = f"{note}；{summary}"

    prev = (bom.eng_review_status or "").strip()
    bom.eng_review_status = REVIEW_PENDING
    bom.eng_review_message = summary[:512]
    bom.eng_submitter = (submitter or "")[:64] or None
    bom.eng_submitted_at = datetime.utcnow()
    bom.eng_reviewed_by = None
    bom.eng_reviewed_at = None
    bom.updated_at = datetime.utcnow()

    evt = "resubmit" if prev in (REVIEW_APPROVED, REVIEW_REJECTED, REVIEW_PENDING) else event_type
    # 重新送审后，关闭该机型未处理的退回通知
    mark_rejected_inbox_done(db, bom_model_id=bom.id)
    inbox = EngReviewInbox(
        bom_model_id=bom.id,
        internal_code=bom.internal_code or "",
        model_code=bom.model_code or "",
        purchase_no=bom.purchase_no or "",
        event_type=evt,
        summary=summary[:512],
        submitter=bom.eng_submitter,
        status="unread",
    )
    db.add(inbox)
    db.flush()
    return bom


def submit_by_model_code(
    db: Session,
    *,
    internal_code: str,
    model_code: str,
    submitter: str,
    note: str = "",
) -> Optional[BomModel]:
    """坐标/Gerber 按机型料号关联 BOM 后送审。"""
    q = (
        db.query(BomModel)
        .filter(
            BomModel.internal_code == internal_code,
            BomModel.model_code == model_code,
            BomModel.is_active.is_(True),
        )
        .order_by(BomModel.id.desc())
    )
    bom = q.first()
    if not bom:
        return None
    return submit_bom_for_review(db, bom.id, submitter=submitter, note=note or "资料已更新")


def reopen_bom_review_after_edit(
    db: Session,
    bom_model_id: int,
    *,
    editor: str,
    note: str = "贴装/面别已修正，请重新审核通过",
) -> Optional[BomModel]:
    """审核中修正贴装后：已通过/已退回的改回待审；待审保持不变并更新提示。"""
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
    if not bom or not bom.is_active:
        return None
    prev = (bom.eng_review_status or "").strip()
    if prev == REVIEW_PENDING:
        bom.eng_review_message = (note or "贴装信息已修改，请审核通过")[:512]
        bom.updated_at = datetime.utcnow()
        db.flush()
        return bom
    if prev in (REVIEW_APPROVED, REVIEW_REJECTED, REVIEW_IMPORT, ""):
        return submit_bom_for_review(
            db,
            bom_model_id,
            submitter=editor,
            note=note or "贴装/面别已修正，请重新审核通过",
        )
    return bom


def approve_bom_review(
    db: Session,
    bom_model_id: int,
    *,
    reviewer: str,
    message: str = "",
) -> BomModel:
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
    if not bom:
        raise ValueError("机型不存在")
    dossier = build_review_dossier(db, bom_model_id)
    missing = [
        c["label"]
        for c in (dossier.get("checklist") or [])
        if not c.get("optional") and not c.get("ready")
    ]
    if missing:
        raise ValueError(f"本客户齐套未完成，缺少：{'、'.join(missing)}")
    bom.eng_review_status = REVIEW_APPROVED
    bom.eng_review_message = (message or "审核通过")[:512]
    bom.eng_reviewed_by = (reviewer or "")[:64] or None
    bom.eng_reviewed_at = datetime.utcnow()
    bom.updated_at = datetime.utcnow()
    (
        db.query(EngReviewInbox)
        .filter(EngReviewInbox.bom_model_id == bom_model_id, EngReviewInbox.status != "done")
        .update({"status": "done"}, synchronize_session=False)
    )
    db.flush()
    return bom


def reject_bom_review(
    db: Session,
    bom_model_id: int,
    *,
    reviewer: str,
    message: str,
) -> BomModel:
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
    if not bom:
        raise ValueError("机型不存在")
    if not (message or "").strip():
        raise ValueError("退回请填写原因")
    reason = message.strip()[:400]
    bom.eng_review_status = REVIEW_REJECTED
    bom.eng_review_message = reason[:512]
    bom.eng_reviewed_by = (reviewer or "")[:64] or None
    bom.eng_reviewed_at = datetime.utcnow()
    bom.updated_at = datetime.utcnow()
    (
        db.query(EngReviewInbox)
        .filter(EngReviewInbox.bom_model_id == bom_model_id, EngReviewInbox.status != "done")
        .update({"status": "done"}, synchronize_session=False)
    )
    # 推送给资料员（邱梦林 dxgc）：submitter 字段存放待办接收帐号
    from eng_push_config import display_name_for, primary_importer_username

    target_user = primary_importer_username()
    original = (bom.eng_submitter or "").strip()
    summary = f"审核退回：{reason}"
    if reviewer:
        summary += f"（审核人：{reviewer}"
        if original:
            summary += f"；原提交：{original}"
        summary += "）"
    elif original:
        summary += f"（原提交：{original}）"
    summary = f"【请 {display_name_for(target_user)} 处理】{summary}"
    db.add(
        EngReviewInbox(
            bom_model_id=bom.id,
            internal_code=bom.internal_code or "",
            model_code=bom.model_code or "",
            purchase_no=bom.purchase_no or "",
            event_type="rejected",
            summary=summary[:512],
            submitter=target_user,
            status="unread",
        )
    )
    db.flush()
    return bom


def list_rejected_notices_for_user(db: Session, username: str, *, limit: int = 50) -> list[dict]:
    """资料员待办：审核退回通知（按接收帐号 submitter 匹配）。"""
    from eng_push_config import normalize_username, primary_importer_username

    user = normalize_username(username)
    if not user:
        return []
    rows = (
        db.query(EngReviewInbox)
        .filter(
            EngReviewInbox.event_type == "rejected",
            EngReviewInbox.status == "unread",
        )
        .order_by(EngReviewInbox.id.desc())
        .limit(limit * 3)
        .all()
    )
    out: list[dict] = []
    for r in rows:
        target = (r.submitter or "").strip().lower()
        if target and target != user:
            continue
        if not target and user != primary_importer_username():
            continue
        bom = (
            db.query(BomModel).filter(BomModel.id == r.bom_model_id).first()
            if r.bom_model_id
            else None
        )
        out.append(
            {
                "todo_type": "rejected",
                "inbox_id": r.id,
                "bom_model_id": r.bom_model_id,
                "internal_code": r.internal_code or (bom.internal_code if bom else "") or "",
                "customer_id": (bom.customer_id if bom else "") or "",
                "model_code": r.model_code or (bom.model_code if bom else "") or "",
                "model_name": (bom.model_name if bom else "") or "",
                "purchase_no": r.purchase_no or (bom.purchase_no if bom else "") or "",
                "line_count": int(bom.line_count or 0) if bom else 0,
                "submitter": r.submitter or "",
                "summary": r.summary or "资料已退回，请按原因修正后重新提交",
                "submitted_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": None,
            }
        )
        if len(out) >= limit:
            break
    return out


def mark_rejected_inbox_done(db: Session, *, bom_model_id: Optional[int] = None, inbox_id: Optional[int] = None) -> int:
    q = db.query(EngReviewInbox).filter(
        EngReviewInbox.event_type == "rejected",
        EngReviewInbox.status != "done",
    )
    if inbox_id:
        q = q.filter(EngReviewInbox.id == inbox_id)
    elif bom_model_id:
        q = q.filter(EngReviewInbox.bom_model_id == bom_model_id)
    else:
        return 0
    return int(q.update({"status": "done"}, synchronize_session=False) or 0)


def list_review_inbox(db: Session, *, unread_only: bool = False, limit: int = 50) -> list[dict]:
    q = db.query(EngReviewInbox).order_by(EngReviewInbox.id.desc())
    if unread_only:
        q = q.filter(EngReviewInbox.status == "unread")
    rows = q.limit(limit).all()
    return [
        {
            "id": r.id,
            "bom_model_id": r.bom_model_id,
            "internal_code": r.internal_code,
            "model_code": r.model_code,
            "purchase_no": r.purchase_no,
            "event_type": r.event_type,
            "summary": r.summary,
            "submitter": r.submitter,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def list_pending_review_boms(db: Session, *, limit: int = 100) -> list[dict]:
    """待审核 BOM 清单（以机型审核状态为准，供审核员一键跳转）。"""
    rows = (
        db.query(BomModel)
        .filter(
            BomModel.is_active.is_(True),
            BomModel.eng_review_status == REVIEW_PENDING,
        )
        .order_by(BomModel.eng_submitted_at.desc().nullslast(), BomModel.updated_at.desc(), BomModel.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "todo_type": "review",
            "bom_model_id": r.id,
            "internal_code": r.internal_code or "",
            "customer_id": r.customer_id or "",
            "model_code": r.model_code or "",
            "model_name": r.model_name or "",
            "purchase_no": r.purchase_no or "",
            "line_count": int(r.line_count or 0),
            "submitter": r.eng_submitter or "",
            "summary": r.eng_review_message or _asset_summary(db, r) or "BOM 已导入，待核对贴装与资料",
            "submitted_at": r.eng_submitted_at.isoformat() if r.eng_submitted_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def pending_review_count(db: Session) -> int:
    return (
        db.query(BomModel)
        .filter(
            BomModel.is_active.is_(True),
            BomModel.eng_review_status == REVIEW_PENDING,
        )
        .count()
    )


def list_pending_import_orders(db: Session, *, limit: int = 100) -> list[dict]:
    """资料员待办：在制订单尚未确认/导入 BOM 的清单。"""
    from engineering_service import list_bom_order_catalog

    rows = list_bom_order_catalog(db, "", "", "")
    out = []
    for r in rows:
        if (r.get("bom_status") or "") == "imported" or int(r.get("line_count") or 0) > 0:
            continue
        out.append(
            {
                "todo_type": "import",
                "bom_model_id": r.get("id") or r.get("bom_model_id"),
                "internal_code": r.get("internal_code") or "",
                "customer_id": r.get("customer_id") or "",
                "model_code": r.get("model_code") or "",
                "model_name": r.get("model_name") or "",
                "purchase_no": r.get("purchase_no") or "",
                "line_key": r.get("line_key") or "",
                "line_count": int(r.get("line_count") or 0),
                "submitter": "",
                "summary": "BOM 未导入，请导入本订单资料",
                "submitted_at": r.get("latest_purchase_date"),
                "updated_at": None,
            }
        )
        if len(out) >= limit:
            break
    return out


def my_todos_for_principal(
    db: Session,
    *,
    role: str,
    username: str = "",
    internal_code: str = "",
) -> dict:
    """
    按帐号返回待办：
    - 黄星 dxsmt001 / 王总 dx003 / eng_auditor / WGQ / 其它管理员：待审核资料
    - 邱梦林 dxgc / engineering：待导入 BOM + 审核退回通知
    - internal_code：可选，仅返回该工程客户
    """
    from eng_push_config import (
        display_name_for,
        is_eng_auditor_user,
        is_eng_importer_user,
        normalize_username,
        primary_importer_username,
    )

    role = (role or "").strip()
    user = normalize_username(username)
    ic_filter = (internal_code or "").strip().upper()
    items: list[dict] = []

    # 审核员黄星等：收待审（资料员 dxgc 本人不收）
    if is_eng_auditor_user(user, role):
        items.extend(
            {
                **row,
                "todo_type": "review",
                "summary": row.get("summary") or "资料待审核",
                "push_to": display_name_for(user) or user,
            }
            for row in list_pending_review_boms(db)
        )

    # 资料员邱梦林：待导入 + 退回
    if is_eng_importer_user(user, role):
        items.extend(list_pending_import_orders(db))
        items.extend(list_rejected_notices_for_user(db, user or primary_importer_username()))

    if ic_filter:
        items = [
            it
            for it in items
            if (it.get("internal_code") or "").strip().upper() == ic_filter
        ]

    # 去重：同 bom + todo_type 只留一条
    seen: set[str] = set()
    deduped: list[dict] = []
    for it in items:
        key = f"{it.get('todo_type')}:{it.get('bom_model_id')}:{it.get('inbox_id') or it.get('purchase_no') or ''}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    items = deduped

    has_review = any(i.get("todo_type") == "review" for i in items)
    has_rejected = any(i.get("todo_type") == "rejected" for i in items)
    has_import = any(i.get("todo_type") == "import" for i in items)

    who = display_name_for(user)
    if has_rejected and (has_review or has_import):
        kind, title, hint = (
            "mixed",
            "待处理事项",
            f"{who}：含待审核 / 退回修正等，点「去处理」定位订单" if who else "含待审核 / 退回修正等，点「去处理」定位订单",
        )
    elif has_rejected:
        kind, title, hint = (
            "rejected",
            "审核退回",
            f"{who}：审核员退回的资料会推到这里，请按原因修正后重新导入/送审" if who else "审核员退回的资料会推到这里，请按原因修正后重新导入/送审",
        )
    elif has_review:
        kind, title, hint = (
            "review",
            "待审核资料",
            f"{who}：邱梦林导入或修正后会推送到这里，点「去处理」进入审核" if who else "资料员导入或修正后会推送到这里，点「去处理」进入审核",
        )
    elif has_import:
        kind, title, hint = (
            "import",
            "待导入资料",
            f"{who}：在制订单尚未导入 BOM 的会推送到这里，点「去导入」定位后上传" if who else "在制订单尚未导入 BOM 的会推送到这里，点「去处理」定位订单后导入",
        )
    else:
        kind, title, hint = "", "待处理事项", ""

    return {
        "role": role,
        "todo_kind": kind,
        "title": title,
        "hint": hint,
        "count": len(items),
        "internal_code": ic_filter,
        "items": items,
    }


def mark_inbox_read(db: Session, inbox_id: int) -> None:
    row = db.query(EngReviewInbox).filter(EngReviewInbox.id == inbox_id).first()
    if row and row.status == "unread":
        row.status = "read"
        db.flush()


def unread_inbox_count(db: Session) -> int:
    return db.query(EngReviewInbox).filter(EngReviewInbox.status == "unread").count()
