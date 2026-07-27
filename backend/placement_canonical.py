"""贴片坐标记录去重与优先级（避免 placement_sync ↔ mount_classification 循环导入）"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import PcbGerberPackage, PcbPlacementFile, PcbPlacementLine, PcbRefmapFile
from gerber_audit import is_gerber_usable
from placement_audit import is_placement_usable
from refmap_audit import is_refmap_usable


def placement_rank(row: PcbPlacementFile) -> tuple:
    source = (row.source or "").strip().lower()
    if (row.source_file or "").startswith("upload:"):
        source = "manual"
    rank = {"manual": 3, "share": 2, "pending": 1}.get(source, 0)
    audit_rank = {"passed": 3, "warning": 2, "failed": 0, "pending": 1}.get((row.audit_status or "pending").strip(), 1)
    ts = row.updated_at or row.synced_at or row.created_at or datetime.min
    return (audit_rank, rank, ts, row.line_count or 0, row.id or 0)


def pick_canonical_placement(files: list[PcbPlacementFile]) -> Optional[PcbPlacementFile]:
    usable = [f for f in files if (f.line_count or 0) > 0 and is_placement_usable(f.audit_status)]
    ready = usable or [f for f in files if f.line_count > 0 and f.file_format != "pending"]
    pool = ready or files
    if not pool:
        return None
    return max(pool, key=placement_rank)


def has_manual_placement(db: Session, internal_code: str, model_code: str) -> bool:
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    rows = (
        db.query(PcbPlacementFile)
        .filter(
            PcbPlacementFile.internal_code == ic,
            PcbPlacementFile.model_code == mc,
            PcbPlacementFile.line_count > 0,
            PcbPlacementFile.file_format != "pending",
        )
        .all()
    )
    return any(placement_rank(r)[1] >= 3 and is_placement_usable(r.audit_status) for r in rows)


def delete_placement_file(db: Session, file_id: int) -> None:
    db.query(PcbPlacementLine).filter(PcbPlacementLine.placement_file_id == file_id).delete()
    db.query(PcbPlacementFile).filter(PcbPlacementFile.id == file_id).delete()


def delete_gerber_package(db: Session, package_id: int) -> None:
    db.query(PcbGerberPackage).filter(PcbGerberPackage.id == package_id).delete()


def delete_refmap_file(db: Session, file_id: int) -> None:
    db.query(PcbRefmapFile).filter(PcbRefmapFile.id == file_id).delete()


def purge_superseded_placements(
    db: Session,
    internal_code: str,
    model_code: str,
    keep_id: int,
    *,
    purchase_no: str = "",
    bom_model_id: Optional[int] = None,
) -> int:
    """同作用域只保留一条坐标：订单级按 purchase_no/bom_model_id，机型级按机型。"""
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    pn = (purchase_no or "").strip()
    siblings = (
        db.query(PcbPlacementFile)
        .filter(
            PcbPlacementFile.internal_code == ic,
            PcbPlacementFile.model_code == mc,
            PcbPlacementFile.id != keep_id,
        )
        .all()
    )
    removed = 0
    for row in siblings:
        if bom_model_id:
            # 仅清同订单 BOM 下的旧记录
            if row.bom_model_id == bom_model_id or (
                pn and (row.purchase_no or "").strip() == pn
            ):
                delete_placement_file(db, row.id)
                removed += 1
            continue
        if pn:
            if (row.purchase_no or "").strip() == pn:
                delete_placement_file(db, row.id)
                removed += 1
            continue
        # 机型级：只删无订单号（或同为空）的历史机型级记录，不动订单级
        if not (row.purchase_no or "").strip() and not row.bom_model_id:
            delete_placement_file(db, row.id)
            removed += 1
    return removed


def gerber_rank(row: PcbGerberPackage) -> tuple:
    source = (row.source or "").strip().lower()
    if (row.source_path or "").startswith("upload:"):
        source = "manual"
    rank = {"manual": 3, "share": 2, "pending": 1}.get(source, 0)
    audit_rank = {"passed": 3, "warning": 2, "failed": 0, "pending": 1}.get((row.audit_status or "pending").strip(), 1)
    ts = row.updated_at or row.synced_at or row.created_at or datetime.min
    return (audit_rank, rank, ts, row.file_count or 0, row.id or 0)


def pick_canonical_gerber(packages: list[PcbGerberPackage]) -> Optional[PcbGerberPackage]:
    usable = [p for p in packages if (p.file_count or 0) > 0 and is_gerber_usable(p.audit_status)]
    ready = usable or [p for p in packages if (p.file_count or 0) > 0]
    pool = ready or packages
    if not pool:
        return None
    return max(pool, key=gerber_rank)


def has_ready_gerber(db: Session, internal_code: str, model_code: str) -> bool:
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    rows = (
        db.query(PcbGerberPackage)
        .filter(
            PcbGerberPackage.internal_code == ic,
            PcbGerberPackage.model_code == mc,
            PcbGerberPackage.file_count > 0,
        )
        .all()
    )
    return any(is_gerber_usable(row.audit_status) for row in rows)


def purge_superseded_gerbers(
    db: Session,
    internal_code: str,
    model_code: str,
    keep_id: int,
    *,
    purchase_no: str = "",
    bom_model_id: Optional[int] = None,
) -> int:
    """同作用域只保留一条 Gerber。"""
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    pn = (purchase_no or "").strip()
    siblings = (
        db.query(PcbGerberPackage)
        .filter(
            PcbGerberPackage.internal_code == ic,
            PcbGerberPackage.model_code == mc,
            PcbGerberPackage.id != keep_id,
        )
        .all()
    )
    removed = 0
    for row in siblings:
        if bom_model_id:
            if row.bom_model_id == bom_model_id or (
                pn and (row.purchase_no or "").strip() == pn
            ):
                db.query(PcbGerberPackage).filter(PcbGerberPackage.id == row.id).delete()
                removed += 1
            continue
        if pn:
            if (row.purchase_no or "").strip() == pn:
                db.query(PcbGerberPackage).filter(PcbGerberPackage.id == row.id).delete()
                removed += 1
            continue
        if not (row.purchase_no or "").strip() and not row.bom_model_id:
            db.query(PcbGerberPackage).filter(PcbGerberPackage.id == row.id).delete()
            removed += 1
    return removed


def refmap_rank(row: PcbRefmapFile) -> tuple:
    source = (row.source or "").strip().lower()
    if (row.source_path or "").startswith("upload:"):
        source = "manual"
    rank = {"manual": 3, "share": 2, "pending": 1}.get(source, 0)
    audit_rank = {"passed": 3, "warning": 2, "failed": 0, "pending": 1}.get((row.audit_status or "pending").strip(), 1)
    ts = row.updated_at or row.synced_at or row.created_at or datetime.min
    return (audit_rank, rank, ts, row.file_size or 0, row.id or 0)


def pick_canonical_refmap(files: list[PcbRefmapFile]) -> Optional[PcbRefmapFile]:
    usable = [f for f in files if (f.file_size or 0) > 0 and is_refmap_usable(f.audit_status)]
    ready = usable or [f for f in files if (f.file_size or 0) > 0]
    pool = ready or files
    if not pool:
        return None
    return max(pool, key=refmap_rank)


def purge_superseded_refmaps(
    db: Session,
    internal_code: str,
    model_code: str,
    keep_id: int,
    *,
    purchase_no: str = "",
    bom_model_id: Optional[int] = None,
) -> int:
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    pn = (purchase_no or "").strip()
    siblings = (
        db.query(PcbRefmapFile)
        .filter(
            PcbRefmapFile.internal_code == ic,
            PcbRefmapFile.model_code == mc,
            PcbRefmapFile.id != keep_id,
        )
        .all()
    )
    removed = 0
    for row in siblings:
        if bom_model_id:
            if row.bom_model_id == bom_model_id or (
                pn and (row.purchase_no or "").strip() == pn
            ):
                db.query(PcbRefmapFile).filter(PcbRefmapFile.id == row.id).delete()
                removed += 1
            continue
        if pn:
            if (row.purchase_no or "").strip() == pn:
                db.query(PcbRefmapFile).filter(PcbRefmapFile.id == row.id).delete()
                removed += 1
            continue
        if not (row.purchase_no or "").strip() and not row.bom_model_id:
            db.query(PcbRefmapFile).filter(PcbRefmapFile.id == row.id).delete()
            removed += 1
    return removed
