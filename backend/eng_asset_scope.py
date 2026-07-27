"""工程资产作用域：model（机型共用）/ order（订单隔离：菲利斯、恩玖等）。"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from sqlalchemy.orm import Session

from eng_customer_rules import get_customer_rules
from models import BomLine, BomModel, PcbGerberPackage, PcbPlacementFile, PcbPlacementLine, PcbRefmapFile


def assets_scope_for(internal_code: str) -> str:
    rules = get_customer_rules(internal_code)
    scope = (rules.get("assets_scope") or "model").strip().lower()
    return "order" if scope == "order" else "model"


def compute_bom_content_hash(db: Session, bom_model_id: int) -> str:
    """规范化 BOM 明细指纹：同版本 → 同 hash。"""
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == bom_model_id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    payload = []
    for line in lines:
        payload.append(
            {
                "c": (line.material_code or "").strip().upper(),
                "n": (line.material_name or "").strip(),
                "s": (line.spec or "").strip(),
                "q": round(float(line.qty_per or 0), 6),
                "p": (line.position or "").strip().upper(),
                "u": (line.unit or "PCS").strip().upper(),
            }
        )
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_bom_content_hash(db: Session, bom: BomModel) -> str:
    digest = compute_bom_content_hash(db, bom.id)
    bom.content_hash = digest
    return digest


def _asset_purchase_no(row) -> str:
    return (getattr(row, "purchase_no", None) or "").strip()


def _pick_asset(rows: list, bom: BomModel, *, order_scope: bool):
    if not rows:
        return None
    pn = (bom.purchase_no or "").strip()
    if order_scope and pn:
        # 订单隔离：禁止挂其它采购订单的坐标/Gerber（即便 bom_model_id 曾被误回绑）
        eligible = [
            r
            for r in rows
            if (
                (r.bom_model_id == bom.id and _asset_purchase_no(r) in ("", pn))
                or _asset_purchase_no(r) == pn
            )
        ]
        by_id = [r for r in eligible if r.bom_model_id == bom.id]
        if by_id:
            return max(by_id, key=lambda r: r.id)
        by_po = [r for r in eligible if _asset_purchase_no(r) == pn]
        if by_po:
            return max(by_po, key=lambda r: r.id)
        return None
    by_id = [r for r in rows if r.bom_model_id == bom.id]
    if by_id:
        return max(by_id, key=lambda r: r.id)
    # 机型作用域：优先无订单号的历史机型级，再任意最新
    model_level = [r for r in rows if not _asset_purchase_no(r)]
    pool = model_level or rows
    return max(pool, key=lambda r: r.id)


def find_assets_for_bom(db: Session, bom: BomModel) -> tuple:
    """返回 (placement, gerber, refmap)，按客户 assets_scope 隔离。"""
    order_scope = assets_scope_for(bom.internal_code or "") == "order"
    place_rows = (
        db.query(PcbPlacementFile)
        .filter(
            PcbPlacementFile.internal_code == bom.internal_code,
            PcbPlacementFile.model_code == bom.model_code,
        )
        .all()
    )
    gerber_rows = (
        db.query(PcbGerberPackage)
        .filter(
            PcbGerberPackage.internal_code == bom.internal_code,
            PcbGerberPackage.model_code == bom.model_code,
        )
        .all()
    )
    refmap_rows = (
        db.query(PcbRefmapFile)
        .filter(
            PcbRefmapFile.internal_code == bom.internal_code,
            PcbRefmapFile.model_code == bom.model_code,
        )
        .all()
    )
    return (
        _pick_asset(place_rows, bom, order_scope=order_scope),
        _pick_asset(gerber_rows, bom, order_scope=order_scope),
        _pick_asset(refmap_rows, bom, order_scope=order_scope),
    )


def list_same_bom_peers(db: Session, bom_model_id: int) -> list[dict]:
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id, BomModel.is_active.is_(True)).first()
    if not bom or not (bom.content_hash or "").strip():
        return []
    rows = (
        db.query(BomModel)
        .filter(
            BomModel.is_active.is_(True),
            BomModel.internal_code == bom.internal_code,
            BomModel.model_code == bom.model_code,
            BomModel.content_hash == bom.content_hash,
            BomModel.id != bom.id,
            BomModel.line_count > 0,
        )
        .order_by(BomModel.purchase_no.asc(), BomModel.id.desc())
        .all()
    )
    out = []
    for r in rows:
        place, gerber, refmap = find_assets_for_bom(db, r)
        out.append(
            {
                "bom_model_id": r.id,
                "purchase_no": r.purchase_no or "",
                "model_code": r.model_code or "",
                "line_count": int(r.line_count or 0),
                "content_hash": r.content_hash or "",
                "has_placement": bool(place and (place.line_count or 0) > 0),
                "has_gerber": bool(gerber and (gerber.file_count or 0) > 0),
                "has_refmap": bool(refmap),
            }
        )
    return out


def _clone_placement(db: Session, src: PcbPlacementFile, target: BomModel) -> PcbPlacementFile:
    existing = (
        db.query(PcbPlacementFile)
        .filter(PcbPlacementFile.bom_model_id == target.id)
        .order_by(PcbPlacementFile.id.desc())
        .first()
    )
    row = existing or PcbPlacementFile(
        internal_code=target.internal_code,
        model_code=target.model_code,
        source_file=src.source_file,
    )
    if not existing:
        db.add(row)
    row.bom_model_id = target.id
    row.purchase_no = (target.purchase_no or "").strip()
    row.internal_code = target.internal_code
    row.model_code = target.model_code
    row.board_name = src.board_name
    row.folder_name = src.folder_name
    row.source_file = src.source_file
    row.source_mtime = src.source_mtime
    row.file_format = src.file_format
    row.units = src.units
    row.line_count = src.line_count
    row.source = src.source
    row.audit_status = src.audit_status
    row.audit_message = src.audit_message
    row.synced_at = src.synced_at
    from datetime import datetime

    row.updated_at = datetime.utcnow()
    db.flush()
    db.query(PcbPlacementLine).filter(PcbPlacementLine.placement_file_id == row.id).delete()
    lines = db.query(PcbPlacementLine).filter(PcbPlacementLine.placement_file_id == src.id).all()
    for line in lines:
        db.add(
            PcbPlacementLine(
                placement_file_id=row.id,
                refdes=line.refdes,
                comment=line.comment,
                footprint=line.footprint,
                layer=line.layer,
                mid_x=line.mid_x,
                mid_y=line.mid_y,
                pad_x=line.pad_x,
                pad_y=line.pad_y,
                rotation=line.rotation,
                skip=line.skip,
                material_hint=line.material_hint,
                sort_order=line.sort_order,
            )
        )
    row.line_count = len(lines)
    db.flush()
    return row


def _clone_gerber(db: Session, src: PcbGerberPackage, target: BomModel) -> PcbGerberPackage:
    from datetime import datetime

    existing = (
        db.query(PcbGerberPackage)
        .filter(PcbGerberPackage.bom_model_id == target.id)
        .order_by(PcbGerberPackage.id.desc())
        .first()
    )
    row = existing or PcbGerberPackage(
        internal_code=target.internal_code,
        model_code=target.model_code,
        package_name=src.package_name,
        source_path=src.source_path,
    )
    if not existing:
        db.add(row)
    row.bom_model_id = target.id
    row.purchase_no = (target.purchase_no or "").strip()
    row.internal_code = target.internal_code
    row.model_code = target.model_code
    row.package_name = src.package_name
    row.folder_name = src.folder_name
    row.source_path = src.source_path
    row.files_json = src.files_json
    row.file_count = src.file_count
    row.source_mtime = src.source_mtime
    row.source = src.source
    row.audit_status = src.audit_status
    row.audit_message = src.audit_message
    row.synced_at = src.synced_at
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def _clone_refmap(db: Session, src: PcbRefmapFile, target: BomModel) -> PcbRefmapFile:
    from datetime import datetime

    existing = (
        db.query(PcbRefmapFile)
        .filter(PcbRefmapFile.bom_model_id == target.id)
        .order_by(PcbRefmapFile.id.desc())
        .first()
    )
    row = existing or PcbRefmapFile(
        internal_code=target.internal_code,
        model_code=target.model_code,
        source_path=src.source_path,
    )
    if not existing:
        db.add(row)
    row.bom_model_id = target.id
    row.purchase_no = (target.purchase_no or "").strip()
    row.internal_code = target.internal_code
    row.model_code = target.model_code
    row.folder_name = src.folder_name
    row.file_name = src.file_name
    row.source_path = src.source_path
    row.file_size = src.file_size
    row.page_count = src.page_count
    row.source = src.source
    row.source_mtime = src.source_mtime
    row.audit_status = src.audit_status
    row.audit_message = src.audit_message
    row.synced_at = src.synced_at
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def sync_assets_from_peer(
    db: Session,
    *,
    target_bom_id: int,
    source_bom_id: int,
) -> dict:
    """同 BOM 版本订单之间：把源订单的坐标/Gerber/位号图同步到目标订单。"""
    target = db.query(BomModel).filter(BomModel.id == target_bom_id, BomModel.is_active.is_(True)).first()
    source = db.query(BomModel).filter(BomModel.id == source_bom_id, BomModel.is_active.is_(True)).first()
    if not target or not source:
        raise ValueError("订单 BOM 不存在")
    if target.id == source.id:
        raise ValueError("不能同步到自身")
    if (target.content_hash or "") != (source.content_hash or "") or not target.content_hash:
        raise ValueError("仅当两笔订单 BOM 版本（内容指纹）相同时才能同步资料")
    if target.internal_code != source.internal_code or target.model_code != source.model_code:
        raise ValueError("机型不一致，无法同步")

    place, gerber, refmap = find_assets_for_bom(db, source)
    synced = []
    if place and (place.line_count or 0) > 0:
        _clone_placement(db, place, target)
        synced.append("坐标")
    if gerber and (gerber.file_count or 0) > 0:
        _clone_gerber(db, gerber, target)
        synced.append("Gerber")
    if refmap:
        _clone_refmap(db, refmap, target)
        synced.append("位号图")
    if not synced:
        raise ValueError(f"源订单 {source.purchase_no or source.id} 尚无坐标/Gerber/位号图可同步")
    return {
        "message": f"已从订单 {source.purchase_no or source.id} 同步：{'、'.join(synced)}",
        "synced": synced,
        "source_bom_model_id": source.id,
        "target_bom_model_id": target.id,
        "source_purchase_no": source.purchase_no or "",
        "target_purchase_no": target.purchase_no or "",
    }


def resolve_purchase_no_for_import(
    db: Session,
    *,
    internal_code: str,
    bom_model_id: Optional[int],
    purchase_no: str = "",
) -> str:
    """导入资产时解析订单号；order 作用域必须有订单号。"""
    pn = (purchase_no or "").strip()
    if bom_model_id:
        bom = db.query(BomModel).filter(BomModel.id == int(bom_model_id)).first()
        if bom and (bom.purchase_no or "").strip():
            pn = (bom.purchase_no or "").strip()
    if assets_scope_for(internal_code) == "order" and not pn:
        raise ValueError("本客户资料按订单隔离，请先选择订单后再导入坐标/Gerber")
    return pn
