"""位号图（装配图 PDF）导入与维护"""
from __future__ import annotations

import logging
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from engineering_assets import (
    REFMAP_STORE_ROOT,
    delete_refmap_store_file,
    resolve_refmap_pdf,
    save_refmap_pdf,
)
from models import BomModel, ExcelImportLog, PcbRefmapFile
from placement_canonical import pick_canonical_refmap, purge_superseded_refmaps
from refmap_audit import audit_refmap_bytes, audit_refmap_path, audit_refmap_record, is_refmap_usable

logger = logging.getLogger(__name__)

REFMAP_SUFFIXES = {".pdf"}


def _find_bom_model(
    db: Session,
    internal_code: str,
    model_code: str,
    bom_model_id: Optional[int] = None,
) -> Optional[BomModel]:
    if bom_model_id:
        row = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
        if row:
            return row
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    return (
        db.query(BomModel)
        .filter(BomModel.internal_code == ic, BomModel.model_code == mc)
        .order_by(BomModel.id.desc())
        .first()
    )


def _collect_pdf_candidates(root: Path) -> list[Path]:
    items: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".pdf" and not path.name.startswith("."):
            items.append(path)
    items.sort(key=lambda p: (_name_score(p.name), p.stat().st_mtime), reverse=True)
    return items


def _name_score(name: str) -> int:
    lower = name.lower()
    from refmap_audit import REFMAP_NAME_HINTS

    return sum(1 for hint in REFMAP_NAME_HINTS if hint in lower)


def upsert_refmap(
    db: Session,
    *,
    internal_code: str,
    model_code: str,
    file_name: str,
    source_path: str,
    file_size: int,
    page_count: int,
    bom_model_id: Optional[int] = None,
    folder_name: Optional[str] = None,
    source: str = "manual",
    source_mtime: Optional[float] = None,
    audit_status: str = "pending",
    audit_message: str = "",
    purchase_no: str = "",
) -> tuple[PcbRefmapFile, bool]:
    ic = internal_code.strip().upper()
    mc = model_code.strip()
    pn = (purchase_no or "").strip()
    row = None
    if bom_model_id:
        row = (
            db.query(PcbRefmapFile)
            .filter(PcbRefmapFile.bom_model_id == bom_model_id)
            .order_by(PcbRefmapFile.id.desc())
            .first()
        )
    if not row and pn:
        row = (
            db.query(PcbRefmapFile)
            .filter(
                PcbRefmapFile.internal_code == ic,
                PcbRefmapFile.model_code == mc,
                PcbRefmapFile.purchase_no == pn,
            )
            .order_by(PcbRefmapFile.id.desc())
            .first()
        )
    if not row and not pn:
        row = (
            db.query(PcbRefmapFile)
            .filter(
                PcbRefmapFile.internal_code == ic,
                PcbRefmapFile.model_code == mc,
            )
            .filter((PcbRefmapFile.purchase_no == "") | (PcbRefmapFile.purchase_no.is_(None)))
            .order_by(PcbRefmapFile.id.desc())
            .first()
        )
    created = row is None
    now = datetime.utcnow()
    if not row:
        row = PcbRefmapFile(
            internal_code=ic,
            model_code=mc,
            file_name=file_name,
            source_path=source_path,
        )
        db.add(row)
    row.bom_model_id = bom_model_id
    row.purchase_no = pn
    row.folder_name = folder_name
    row.file_name = file_name
    row.source_path = source_path
    row.file_size = file_size
    row.page_count = page_count
    row.audit_status = audit_status or "pending"
    row.audit_message = audit_message or ""
    row.source = source
    row.source_mtime = source_mtime
    row.synced_at = now
    row.updated_at = now
    db.flush()
    if is_refmap_usable(row.audit_status):
        purge_superseded_refmaps(
            db,
            ic,
            mc,
            row.id,
            purchase_no=pn,
            bom_model_id=bom_model_id,
        )
    return row, created


def import_refmap_path(
    db: Session,
    path: Path,
    *,
    internal_code: str,
    model_code: str,
    bom_model_id: Optional[int] = None,
    folder_name: Optional[str] = None,
    source: str = "manual",
    source_path_override: Optional[str] = None,
    source_mtime_override: Optional[float] = None,
    purchase_no: str = "",
) -> dict:
    item = {
        "internal_code": internal_code,
        "model_code": model_code,
        "file": path.name,
        "status": "success",
        "message": "",
        "refmap_file_id": 0,
        "audit_status": "pending",
        "audit_message": "",
        "page_count": 0,
        "file_size": 0,
    }
    try:
        audit = audit_refmap_path(path)
        item["audit_status"] = audit.status
        item["audit_message"] = audit.message
        item["page_count"] = audit.page_count
        item["file_size"] = audit.file_size
        if audit.status == "failed":
            raise ValueError(audit.message)
        bom = _find_bom_model(db, internal_code, model_code, bom_model_id)
        mtime = source_mtime_override if source_mtime_override is not None else path.stat().st_mtime
        pn = purchase_no or ((bom.purchase_no or "").strip() if bom else "")
        row, created = upsert_refmap(
            db,
            internal_code=internal_code,
            model_code=model_code,
            file_name=path.name,
            source_path=source_path_override or str(path.resolve()),
            file_size=audit.file_size,
            page_count=audit.page_count,
            bom_model_id=bom.id if bom else bom_model_id,
            folder_name=folder_name,
            source=source,
            source_mtime=mtime,
            audit_status=audit.status,
            audit_message=audit.message,
            purchase_no=pn,
        )
        try:
            store_path = save_refmap_pdf(
                internal_code=row.internal_code,
                model_code=row.model_code,
                file_id=row.id,
                file_name=row.file_name,
                content=path.read_bytes(),
            )
            row.source_path = f"store:{store_path.relative_to(REFMAP_STORE_ROOT).as_posix()}"
        except OSError as exc:
            logger.warning("位号图归档失败 %s: %s", path, exc)
        item["refmap_file_id"] = row.id
        hint = "（审核警告）" if audit.status == "warning" else "（审核通过）"
        item["message"] = f"{'新增' if created else '更新'}位号图 {path.name}{hint}：{audit.message}"
        db.add(
            ExcelImportLog(
                source_file=str(path),
                customer_name=f"{internal_code}/{model_code}/refmap",
                rows_imported=1,
                rows_updated=0 if created else 1,
                status="success",
                message=item["message"],
            )
        )
    except Exception as exc:
        logger.exception("位号图导入失败 %s", path)
        item["status"] = "failed"
        item["message"] = str(exc)
    return item


def import_refmap_bytes(
    db: Session,
    content: bytes,
    filename: str,
    *,
    internal_code: str,
    model_code: str,
    bom_model_id: Optional[int] = None,
    purchase_no: str = "",
) -> dict:
    safe_name = Path(filename).name or "refmap.pdf"
    suffix = Path(safe_name).suffix.lower()
    with tempfile.TemporaryDirectory() as td:
        staging = Path(td)
        if suffix in (".zip", ".rar", ".7z"):
            archive_path = staging / safe_name
            archive_path.write_bytes(content)
            extract_dir = staging / "extracted"
            extract_dir.mkdir()
            if suffix == ".zip":
                try:
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        zf.extractall(extract_dir)
                except zipfile.BadZipFile:
                    return {
                        "status": "failed",
                        "message": "不是有效的 ZIP 文件",
                        "refmap_file_id": 0,
                        "internal_code": internal_code,
                        "model_code": model_code,
                        "file": safe_name,
                    }
            else:
                from archive_assets import extract_archive

                if not extract_archive(archive_path, extract_dir):
                    return {
                        "status": "failed",
                        "message": f"{suffix.upper()} 解压失败，请直接上传 PDF 或改用 ZIP",
                        "refmap_file_id": 0,
                        "internal_code": internal_code,
                        "model_code": model_code,
                        "file": safe_name,
                    }
            candidates = _collect_pdf_candidates(extract_dir)
            if not candidates:
                return {
                    "status": "failed",
                    "message": "压缩包内未找到 PDF 位号图",
                    "audit_status": "failed",
                    "audit_message": "压缩包内未找到 PDF",
                    "refmap_file_id": 0,
                    "internal_code": internal_code,
                    "model_code": model_code,
                    "file": safe_name,
                }
            pdf_path = candidates[0]
            result = import_refmap_path(
                db,
                pdf_path,
                internal_code=internal_code,
                model_code=model_code,
                bom_model_id=bom_model_id,
                source="manual",
                source_path_override=f"upload:{safe_name}/{pdf_path.name}",
                purchase_no=purchase_no,
            )
            return result

        if suffix != ".pdf":
            audit = audit_refmap_bytes(content, safe_name)
            if audit.status == "failed":
                return {
                    "status": "failed",
                    "message": audit.message,
                    "audit_status": audit.status,
                    "audit_message": audit.message,
                    "refmap_file_id": 0,
                    "internal_code": internal_code,
                    "model_code": model_code,
                    "file": safe_name,
                }
        path = staging / safe_name
        path.write_bytes(content)
        return import_refmap_path(
            db,
            path,
            internal_code=internal_code,
            model_code=model_code,
            bom_model_id=bom_model_id,
            source="manual",
            purchase_no=purchase_no,
        )


def get_refmap_pdf_path(db: Session, file_id: int) -> Path:
    row = db.query(PcbRefmapFile).filter(PcbRefmapFile.id == file_id).first()
    if not row:
        raise ValueError("位号图不存在")
    path = resolve_refmap_pdf(row)
    if not path:
        raise ValueError("位号图文件未归档，请重新导入")
    return path


def _refmap_to_dict(row: PcbRefmapFile) -> dict:
    usable = is_refmap_usable(row.audit_status)
    if not row.file_name or row.file_size <= 0:
        asset_status = "pending"
    elif row.audit_status == "failed":
        asset_status = "failed"
    elif usable:
        asset_status = "imported"
    else:
        asset_status = "pending"
    return {
        "id": row.id,
        "bom_model_id": row.bom_model_id,
        "internal_code": row.internal_code,
        "model_code": row.model_code,
        "file_name": row.file_name or "",
        "source_path": row.source_path or "",
        "file_size": row.file_size or 0,
        "page_count": row.page_count or 0,
        "source": row.source or "manual",
        "audit_status": row.audit_status or "pending",
        "audit_message": row.audit_message or "",
        "asset_status": asset_status,
        "synced_at": row.synced_at,
        "updated_at": row.updated_at,
    }


def reaudit_refmap_file(db: Session, file_id: int) -> dict:
    row = db.query(PcbRefmapFile).filter(PcbRefmapFile.id == file_id).first()
    if not row:
        raise ValueError("位号图记录不存在")
    audit = audit_refmap_record(
        file_name=row.file_name or "",
        file_size=row.file_size or 0,
        page_count=row.page_count or 0,
        source_path=row.source_path or "",
    )
    row.audit_status = audit.status
    row.audit_message = audit.message
    row.updated_at = datetime.utcnow()
    return {
        "refmap_file_id": row.id,
        "audit_status": audit.status,
        "audit_message": audit.message,
    }


def reaudit_all_refmap_files(db: Session) -> int:
    count = 0
    for row in db.query(PcbRefmapFile).all():
        if not row.file_name or (row.file_size or 0) <= 0:
            continue
        audit = audit_refmap_record(
            file_name=row.file_name,
            file_size=row.file_size or 0,
            page_count=row.page_count or 0,
            source_path=row.source_path or "",
        )
        row.audit_status = audit.status
        row.audit_message = audit.message
        count += 1
    return count
