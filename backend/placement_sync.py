"""PCB 贴片坐标同步（共享盘 A123 / A116-NJ + 手工导入）"""
from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from archive_assets import archive_source_label, extract_to_staging, list_archives
from asset_discovery import (
    extract_model_key,
    iter_primary_model_folders,
    legacy_asset_roots,
    match_legacy_dirs,
    primary_model_root,
)
from bom_excel import (
    SKIP_FOLDER_PREFIXES,
    SKIP_TOP_FOLDERS,
    resolve_engineering_share_dir,
)
from config import get_engineering_customers
from engineering_service import normalize_code
from models import BomModel, ExcelImportLog, PcbPlacementFile, PcbPlacementLine
from model_linkage import find_bom_for_folder
from placement_canonical import (
    has_manual_placement,
    pick_canonical_placement,
    purge_superseded_placements,
)
from placement_audit import (
    audit_parsed_placement,
    audit_placement_record,
    is_placement_usable,
)
from placement_parser import ParsedPlacement, parse_placement_file

logger = logging.getLogger(__name__)

COORD_NAME_HINTS = (
  "pick place",
  "坐标文件",
  "坐标_ais",
  "coordinate",
  "_asc",
)
SKIP_COORD_NAME_PARTS = ("无坐标",)
FIDUCIAL_NAME_PARTS = ("fiducial", "_mark")
# 坐标 / Gerber 同步包含「旧资料」子目录；仅跳过压缩包、管制明细等
SKIP_ASSET_SUBFOLDERS = {"生产资料压缩包", "管制明细"}


@dataclass
class CoordCandidate:
    path: Path
    mtime: float
    source_label: str


def _coord_candidate(path: Path) -> CoordCandidate:
    return CoordCandidate(path=path, mtime=path.stat().st_mtime, source_label=str(path.resolve()))


def _should_skip_path(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts
    if any(part in SKIP_ASSET_SUBFOLDERS for part in rel_parts[:-1]):
        return True
    if any(part in SKIP_TOP_FOLDERS for part in rel_parts):
        return True
    if rel_parts and any(rel_parts[0].startswith(p) for p in SKIP_FOLDER_PREFIXES):
        return True
    if any(k in path.name for k in SKIP_COORD_NAME_PARTS):
        return True
    return False


def _is_coord_file(path: Path, *, loose: bool = False) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith("~") or path.name.startswith("."):
        return False
    lower = path.name.lower()
    if any(k in lower for k in FIDUCIAL_NAME_PARTS):
        return False
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt"):
        if loose:
            return True
        if any(h in lower for h in COORD_NAME_HINTS):
            return True
        if "坐标" in path.name:
            return True
        if "coordinate" in lower:
            return True
        return False
    if suffix == ".xlsx":
        if loose:
            return True
        if "_asc" in lower or path.parent.name.upper().endswith("_ASC"):
            return True
    return False


def _extract_model_key(folder_name: str, internal_code: str) -> str:
    return extract_model_key(folder_name, internal_code)


def _iter_model_folders(root: Path):
    yield from iter_primary_model_folders(root)


def _collect_coords_for_model(
    base: Path,
    customer: dict,
    folder_name: str,
    folder: Path,
    staging_dir: Optional[Path] = None,
) -> list[CoordCandidate]:
    """主目录 + 压缩包解压 + A123 历史库回退搜索坐标文件。"""
    ic = (customer.get("internal_code") or "").strip().upper()
    primary_root = folder
    files = _select_coord_candidates(_collect_coord_candidates(folder, primary_root, staging_dir))
    if files:
        return files

    model_key = extract_model_key(folder_name, ic)
    merged: list[CoordCandidate] = []
    for legacy_root in legacy_asset_roots(customer, base):
        for legacy_dir in match_legacy_dirs(legacy_root, model_key):
            merged.extend(
                _select_coord_candidates(_collect_coord_candidates(legacy_dir, legacy_root, staging_dir))
            )
    if not merged:
        return []

    groups: dict[str, CoordCandidate] = {}
    for item in sorted(merged, key=lambda c: c.mtime, reverse=True):
        key = _board_key(item.path)
        if key not in groups:
            groups[key] = item
    return list(groups.values())


def upsert_pending_placement(
    db: Session,
    *,
    internal_code: str,
    model_code: str,
    folder_name: str,
    bom_model_id: Optional[int] = None,
) -> PcbPlacementFile:
    ic = internal_code.strip().upper()
    row = (
        db.query(PcbPlacementFile)
        .filter(
            PcbPlacementFile.internal_code == ic,
            PcbPlacementFile.model_code == model_code.strip(),
            PcbPlacementFile.folder_name == folder_name,
            PcbPlacementFile.file_format == "pending",
        )
        .first()
    )
    now = datetime.utcnow()
    if not row:
        row = PcbPlacementFile(
            internal_code=ic,
            model_code=model_code.strip(),
            folder_name=folder_name,
            source_file=f"folder:{folder_name}",
            file_format="pending",
            source="pending",
        )
        db.add(row)
    row.bom_model_id = bom_model_id
    row.board_name = "(待导入坐标)"
    row.line_count = 0
    row.synced_at = now
    row.updated_at = now
    db.flush()
    return row


def _find_bom_model(
    db: Session,
    internal_code: str,
    folder_name: str,
    models_cache: Optional[dict[str, list[BomModel]]] = None,
    folder_path: Optional[Path] = None,
) -> Optional[BomModel]:
    return find_bom_for_folder(
        db,
        internal_code,
        folder_name,
        folder_path=folder_path,
        models_cache=models_cache,
    )


def _collect_coord_candidates(
    folder: Path,
    root: Path,
    staging_dir: Optional[Path] = None,
    *,
    loose: bool = False,
) -> list[CoordCandidate]:
    candidates: list[CoordCandidate] = []
    for path in folder.rglob("*"):
        if not _is_coord_file(path, loose=loose):
            continue
        if _should_skip_path(path, root):
            continue
        candidates.append(_coord_candidate(path))
    if staging_dir is not None:
        for archive in list_archives(folder, root, _should_skip_path):
            extract_root = extract_to_staging(archive, staging_dir)
            if not extract_root:
                continue
            for path in extract_root.rglob("*"):
                if not _is_coord_file(path, loose=True):
                    continue
                candidates.append(
                    CoordCandidate(
                        path=path,
                        mtime=archive.stat().st_mtime,
                        source_label=archive_source_label(archive, path, extract_root),
                    )
                )
    candidates.sort(key=lambda c: c.mtime, reverse=True)
    return candidates


def _collect_coord_files(folder: Path, root: Path) -> list[Path]:
    return [c.path for c in _collect_coord_candidates(folder, root, None)]


def _board_key(path: Path) -> str:
    name = path.stem.lower()
    name = re.sub(r"^pick place for\s*", "", name, flags=re.I).strip()
    name = re.sub(r"坐标文件$", "", name).strip()
    return name or path.name


def _select_coord_candidates(candidates: list[CoordCandidate]) -> list[CoordCandidate]:
    if not candidates:
        return []
    groups: dict[str, CoordCandidate] = {}
    for item in candidates:
        key = _board_key(item.path)
        prev = groups.get(key)
        if not prev:
            groups[key] = item
            continue
        path = item.path
        prev_path = prev.path
        if path.suffix.lower() == ".csv" and prev_path.suffix.lower() != ".csv":
            groups[key] = item
        elif path.suffix.lower() == ".xlsx" and prev_path.suffix.lower() not in (".csv", ".xlsx"):
            groups[key] = item
        elif path.suffix.lower() == prev_path.suffix.lower() and item.mtime > prev.mtime:
            groups[key] = item
    return list(groups.values())


def _select_coord_files(files: list[Path]) -> list[Path]:
    candidates = [_coord_candidate(p) for p in files]
    return [c.path for c in _select_coord_candidates(candidates)]


def upsert_placement(
    db: Session,
    parsed: ParsedPlacement,
    *,
    internal_code: str,
    model_code: str,
    bom_model_id: Optional[int],
    folder_name: Optional[str],
    source_mtime: Optional[float],
    source: str = "share",
    audit_status: str = "pending",
    audit_message: str = "",
    purchase_no: str = "",
) -> tuple[PcbPlacementFile, bool]:
    source_file = parsed.source_file
    ic = internal_code.strip().upper()
    board = (parsed.board_name or "").strip()
    pn = (purchase_no or "").strip()
    row = None
    if bom_model_id:
        row = (
            db.query(PcbPlacementFile)
            .filter(
                PcbPlacementFile.bom_model_id == bom_model_id,
                PcbPlacementFile.board_name == board,
            )
            .first()
        )
    if not row and pn:
        row = (
            db.query(PcbPlacementFile)
            .filter(
                PcbPlacementFile.internal_code == ic,
                PcbPlacementFile.model_code == model_code.strip(),
                PcbPlacementFile.purchase_no == pn,
                PcbPlacementFile.board_name == board,
            )
            .first()
        )
    if not row and not pn:
        row = (
            db.query(PcbPlacementFile)
            .filter(
                PcbPlacementFile.internal_code == ic,
                PcbPlacementFile.model_code == model_code.strip(),
                PcbPlacementFile.board_name == board,
            )
            .filter(
                (PcbPlacementFile.purchase_no == "") | (PcbPlacementFile.purchase_no.is_(None))
            )
            .first()
        )
    if not row:
        row = (
            db.query(PcbPlacementFile)
            .filter(PcbPlacementFile.internal_code == ic, PcbPlacementFile.source_file == source_file)
            .first()
        )
        # 订单隔离时，勿复用其它订单的同路径记录
        if row and pn and (row.purchase_no or "").strip() and (row.purchase_no or "").strip() != pn:
            row = None
        if row and bom_model_id and row.bom_model_id and row.bom_model_id != bom_model_id:
            row = None
    created = row is None
    now = datetime.utcnow()
    if not row:
        row = PcbPlacementFile(
            internal_code=internal_code.strip().upper(),
            model_code=model_code.strip(),
            source_file=source_file,
        )
        db.add(row)
    row.bom_model_id = bom_model_id
    row.purchase_no = pn
    row.model_code = model_code.strip()
    row.board_name = parsed.board_name
    row.folder_name = folder_name
    row.source_mtime = source_mtime
    row.file_format = parsed.file_format
    row.units = parsed.units
    row.line_count = len(parsed.lines)
    row.source = source
    row.audit_status = audit_status or "pending"
    row.audit_message = audit_message or ""
    row.synced_at = now
    row.updated_at = now
    db.flush()

    db.query(PcbPlacementLine).filter(PcbPlacementLine.placement_file_id == row.id).delete()
    for line in parsed.lines:
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
    if row.line_count > 0 and row.file_format != "pending" and is_placement_usable(row.audit_status):
        purge_superseded_placements(
            db,
            ic,
            model_code.strip(),
            row.id,
            purchase_no=pn,
            bom_model_id=bom_model_id,
        )
    return row, created


def import_placement_path(
    db: Session,
    path: Path,
    *,
    internal_code: str,
    model_code: str,
    bom_model_id: Optional[int] = None,
    folder_name: Optional[str] = None,
    source: str = "share",
    source_file_override: Optional[str] = None,
    source_mtime_override: Optional[float] = None,
    archive_files: Optional[list[Path]] = None,
    purchase_no: str = "",
) -> dict:
    item = {
        "internal_code": internal_code,
        "model_code": model_code,
        "file": path.name,
        "status": "success",
        "message": "",
        "lines": 0,
        "placement_file_id": 0,
        "audit_status": "pending",
        "audit_message": "",
    }
    try:
        parsed = parse_placement_file(path)
        audit = audit_parsed_placement(parsed, archive_files=archive_files)
        item["audit_status"] = audit.status
        item["audit_message"] = audit.message
        if audit.status == "failed":
            raise ValueError(audit.message)
        parsed.source_file = source_file_override or str(path.resolve())
        mtime = source_mtime_override if source_mtime_override is not None else path.stat().st_mtime
        row, created = upsert_placement(
            db,
            parsed,
            internal_code=internal_code,
            model_code=model_code,
            bom_model_id=bom_model_id,
            folder_name=folder_name,
            source_mtime=mtime,
            source=source,
            audit_status=audit.status,
            audit_message=audit.message,
            purchase_no=purchase_no,
        )
        item["lines"] = len(parsed.lines)
        item["placement_file_id"] = row.id
        audit_hint = "（审核警告）" if audit.status == "warning" else "（审核通过）"
        archive_hint = "（已从压缩包导入）" if (source_file_override or "").startswith(("zip:", "rar:")) else ""
        item["message"] = f"{'新增' if created else '更新'} {len(parsed.lines)} 个位号{archive_hint}{audit_hint}：{audit.message}"
        item["_created"] = 1 if created else 0
        item["_updated"] = 0 if created else 1
        db.add(
            ExcelImportLog(
                source_file=str(path),
                customer_name=f"{internal_code}/{model_code}/placement",
                rows_imported=len(parsed.lines),
                rows_updated=0 if created else 1,
                status="success",
                message=item["message"],
            )
        )
    except Exception as exc:
        logger.exception("坐标导入失败 %s", path)
        item["status"] = "failed"
        item["message"] = str(exc)
        item["_created"] = 0
        item["_updated"] = 0
        db.add(
            ExcelImportLog(
                source_file=str(path),
                customer_name=f"{internal_code}/{model_code}/placement",
                rows_imported=0,
                rows_updated=0,
                status="failed",
                message=str(exc),
            )
        )
    return item


def _pick_importable_coord(candidates: list[CoordCandidate]) -> Optional[CoordCandidate]:
    """手工 ZIP 导入：逐个尝试解析，取第一个有效坐标文件。"""
    ordered = _select_coord_candidates(candidates)
    errors: list[str] = []
    for item in ordered:
        try:
            parse_placement_file(item.path)
            return item
        except ValueError as exc:
            errors.append(f"{item.path.name}: {exc}")
            continue
    for item in candidates:
        if item in ordered:
            continue
        try:
            parse_placement_file(item.path)
            return item
        except ValueError as exc:
            errors.append(f"{item.path.name}: {exc}")
            continue
    if errors:
        # 挂到函数属性，供上层拼更明确的失败原因
        _pick_importable_coord.last_errors = errors[-5:]  # type: ignore[attr-defined]
    return None


def import_placement_bytes(
    db: Session,
    content: bytes,
    filename: str,
    *,
    internal_code: str,
    model_code: str,
    bom_model_id: Optional[int] = None,
    purchase_no: str = "",
) -> dict:
    safe_name = Path(filename).name or "placement.txt"
    suffix = Path(safe_name).suffix.lower()
    with tempfile.TemporaryDirectory() as td:
        staging = Path(td)
        if suffix in (".zip", ".rar"):
            zip_path = staging / safe_name
            zip_path.write_bytes(content)
            extract_root = staging / "extracted"
            extract_root.mkdir()
            if suffix == ".zip":
                from archive_assets import extract_archive

                if not extract_archive(zip_path, extract_root):
                    return {
                        "status": "failed",
                        "message": "ZIP 解压失败（可能含乱码中文路径）。请先本机解压后，只上传明文「*坐标*.txt」",
                        "lines": 0,
                        "placement_file_id": 0,
                        "internal_code": internal_code,
                        "model_code": model_code,
                        "file": safe_name,
                    }
            else:
                from archive_assets import extract_archive

                if not extract_archive(zip_path, extract_root):
                    return {
                        "status": "failed",
                        "message": "RAR 解压失败，请改为上传 .csv/.txt/.xlsx，或安装 unar 后重试",
                        "lines": 0,
                        "placement_file_id": 0,
                        "internal_code": internal_code,
                        "model_code": model_code,
                        "file": safe_name,
                    }
            # 永联 PCBA 包常为外层 ZIP，坐标在嵌套 ASC.zip 内
            candidates = _collect_coord_candidates(
                extract_root, extract_root, staging / "nested_archives", loose=True
            )
            best = _pick_importable_coord(candidates)
            if not best:
                detail = ""
                last = getattr(_pick_importable_coord, "last_errors", None)
                if last:
                    detail = " 具体原因：" + "；".join(last)
                elif not candidates:
                    detail = " 压缩包内没有 .txt/.csv/.xlsx 坐标候选（常见：中文路径解压失败，或只有 Gerber/装配图）。"
                return {
                    "status": "failed",
                    "message": (
                        "压缩包内未找到可解析的坐标文件。"
                        "请确认内含 Altium Pick&Place（.csv/.txt）、AIS 坐标（.txt）"
                        "或 ASC 坐标（*_ASC.txt / .xlsx，可在嵌套 ASC.zip 中）。"
                        "Gerber 压缩包请改到「Gerber 资料」页导入。"
                        f"{detail}"
                    ),
                    "lines": 0,
                    "placement_file_id": 0,
                    "internal_code": internal_code,
                    "model_code": model_code,
                    "file": safe_name,
                }
            archive_files = [p for p in extract_root.rglob("*") if p.is_file()]
            return import_placement_path(
                db,
                best.path,
                internal_code=internal_code,
                model_code=model_code,
                bom_model_id=bom_model_id,
                source="manual",
                source_file_override=f"upload:{safe_name}/{best.path.name}",
                archive_files=archive_files,
                purchase_no=purchase_no,
            )
        path = staging / safe_name
        path.write_bytes(content)
        result = import_placement_path(
            db,
            path,
            internal_code=internal_code,
            model_code=model_code,
            bom_model_id=bom_model_id,
            source="manual",
            purchase_no=purchase_no,
        )
        if result.get("status") == "success" and result.get("placement_file_id"):
            row = db.query(PcbPlacementFile).filter(PcbPlacementFile.id == result["placement_file_id"]).first()
            if row:
                row.source_file = f"upload:{safe_name}"
        return result


def sync_placements_from_share(
    db: Session,
    internal_codes: Optional[list[str]] = None,
) -> dict:
    """已停用：贴片坐标仅人工导入，不再扫描本地共享盘。"""
    return {
        "status": "disabled",
        "message": "贴片坐标已改为人工导入，不再从本地共享盘同步",
        "files": [],
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "pending": 0,
        "failed": 0,
        "share_path": "",
    }


def list_placement_files(
    db: Session,
    internal_code: str = "",
    keyword: str = "",
) -> list[dict]:
    q = db.query(PcbPlacementFile).order_by(
        PcbPlacementFile.internal_code.asc(),
        PcbPlacementFile.model_code.asc(),
        PcbPlacementFile.id.desc(),
    )
    if internal_code:
        q = q.filter(PcbPlacementFile.internal_code == internal_code.strip().upper())
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(
            (PcbPlacementFile.model_code.like(like))
            | (PcbPlacementFile.board_name.like(like))
            | (PcbPlacementFile.folder_name.like(like))
            | (PcbPlacementFile.source_file.like(like))
        )
    rows = q.limit(2000).all()
    by_model: dict[tuple[str, str], PcbPlacementFile] = {}
    for row in rows:
        model_key = (row.model_code or "").strip()
        key = (row.internal_code, model_key)
        existing = by_model.get(key)
        if not existing:
            by_model[key] = row
            continue
        picked = pick_canonical_placement([existing, row])
        if picked:
            by_model[key] = picked
    ordered = sorted(
        by_model.values(),
        key=lambda r: (r.internal_code, r.model_code, r.id),
    )
    return [_file_to_dict(row) for row in ordered[:500]]


def get_placement_lines(db: Session, file_id: int, keyword: str = "") -> list[dict]:
    q = (
        db.query(PcbPlacementLine)
        .filter(PcbPlacementLine.placement_file_id == file_id)
        .order_by(PcbPlacementLine.sort_order.asc(), PcbPlacementLine.id.asc())
    )
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(
            (PcbPlacementLine.refdes.like(like))
            | (PcbPlacementLine.comment.like(like))
            | (PcbPlacementLine.footprint.like(like))
            | (PcbPlacementLine.material_hint.like(like))
        )
    return [
        {
            "id": row.id,
            "refdes": row.refdes,
            "comment": row.comment,
            "footprint": row.footprint,
            "layer": row.layer,
            "mid_x": row.mid_x,
            "mid_y": row.mid_y,
            "rotation": row.rotation,
            "skip": row.skip,
            "material_hint": row.material_hint,
        }
        for row in q.limit(2000).all()
    ]


def get_placement_meta(db: Session) -> dict:
    count = db.query(PcbPlacementFile).count()
    line_count = db.query(PcbPlacementLine).count()
    latest = db.query(PcbPlacementFile.synced_at).order_by(PcbPlacementFile.id.desc()).first()
    by_code = {}
    for ic in ("A123", "A116"):
        by_code[ic] = (
            db.query(PcbPlacementFile)
            .filter(PcbPlacementFile.internal_code == ic)
            .count()
        )
    return {
        "share_path": "",
        "share_accessible": False,
        "assets_share_sync_enabled": False,
        "import_mode": "manual",
        "file_count": count,
        "line_count": line_count,
        "a123_count": by_code.get("A123", 0),
        "a116_count": by_code.get("A116", 0),
        "synced_at": latest[0] if latest else None,
    }


def _file_to_dict(row: PcbPlacementFile) -> dict:
    usable = is_placement_usable(row.audit_status)
    if (row.line_count or 0) <= 0 or row.file_format == "pending":
        status = "pending"
    elif row.audit_status == "failed":
        status = "failed"
    elif usable:
        status = "ready"
    else:
        status = "pending"
    return {
        "id": row.id,
        "bom_model_id": row.bom_model_id,
        "internal_code": row.internal_code,
        "model_code": row.model_code,
        "board_name": row.board_name,
        "folder_name": row.folder_name,
        "source_file": row.source_file,
        "file_format": row.file_format,
        "units": row.units,
        "line_count": row.line_count,
        "source": row.source,
        "status": status,
        "audit_status": row.audit_status or "pending",
        "audit_message": row.audit_message or "",
        "synced_at": row.synced_at,
        "updated_at": row.updated_at,
    }


def reaudit_placement_file(db: Session, file_id: int) -> dict:
    row = db.query(PcbPlacementFile).filter(PcbPlacementFile.id == file_id).first()
    if not row:
        raise ValueError("坐标文件不存在")
    audit = audit_placement_record(
        file_format=row.file_format,
        line_count=row.line_count,
        source_file=row.source_file,
    )
    row.audit_status = audit.status
    row.audit_message = audit.message
    row.updated_at = datetime.utcnow()
    return {
        "placement_file_id": row.id,
        "audit_status": audit.status,
        "audit_message": audit.message,
        "line_count": row.line_count,
    }


def reaudit_all_placement_files(db: Session) -> int:
    updated = 0
    for row in db.query(PcbPlacementFile).filter(PcbPlacementFile.line_count > 0).all():
        audit = audit_placement_record(
            file_format=row.file_format,
            line_count=row.line_count,
            source_file=row.source_file,
        )
        row.audit_status = audit.status
        row.audit_message = audit.message
        updated += 1
    return updated


def placement_export_content_disposition(filename: str) -> str:
    from urllib.parse import quote

    safe = Path(filename or "placement.csv").name or "placement.csv"
    ascii_name = "placement.csv"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(safe)}'


def build_placement_export(db: Session, file_id: int) -> tuple[bytes, str, str]:
    """从库内坐标明细导出 CSV（只读下载）。"""
    import csv
    import io

    row = db.query(PcbPlacementFile).filter(PcbPlacementFile.id == file_id).first()
    if not row:
        raise ValueError("坐标文件不存在")

    lines = (
        db.query(PcbPlacementLine)
        .filter(PcbPlacementLine.placement_file_id == file_id)
        .order_by(PcbPlacementLine.sort_order.asc(), PcbPlacementLine.id.asc())
        .all()
    )
    if not lines:
        raise ValueError("没有可导出的坐标明细")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["refdes", "comment", "footprint", "layer", "mid_x", "mid_y", "rotation", "skip", "material_hint"]
    )
    for line in lines:
        writer.writerow(
            [
                line.refdes or "",
                line.comment or "",
                line.footprint or "",
                line.layer or "",
                "" if line.mid_x is None else line.mid_x,
                "" if line.mid_y is None else line.mid_y,
                "" if line.rotation is None else line.rotation,
                1 if line.skip else 0,
                line.material_hint or "",
            ]
        )

    content = buf.getvalue().encode("utf-8-sig")
    base = (row.board_name or row.model_code or f"placement_{file_id}").strip()
    safe = re.sub(r'[\\/:*?"<>|]+', "_", base) or f"placement_{file_id}"
    filename = f"{safe}.csv"
    return content, filename, "text/csv; charset=utf-8"
