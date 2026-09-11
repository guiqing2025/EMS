"""Gerber 资料包同步（共享盘 A123 / A116-NJ + 手工 ZIP 导入）"""
from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import zipfile
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
from bom_excel import resolve_engineering_share_dir
from config import get_engineering_customers
from models import BomModel, ExcelImportLog, PcbGerberPackage
from gerber_audit import (
    audit_files_metadata,
    audit_gerber_package,
    is_gerber_usable,
)
from placement_canonical import has_ready_gerber, pick_canonical_gerber, purge_superseded_gerbers
from placement_sync import _find_bom_model, _should_skip_path

logger = logging.getLogger(__name__)

GERBER_EXTENSIONS = {
    ".gtl", ".gbl", ".gto", ".gbo", ".gtp", ".gbp", ".gts", ".gbs",
    ".gbr", ".gko", ".gm1", ".apr", ".drl", ".xln", ".rou",
    ".gdo", ".ncd", ".fab",
    # 以下扩展名允许进入审核流程，但内容不合规会被拒绝
    ".dxf", ".pdf", ".txt",
}


def _is_candidate_file(path: Path) -> bool:
    if not path.is_file() or path.name.startswith("."):
        return False
    ext = path.suffix.lower()
    if ext in GERBER_EXTENSIONS:
        return True
    # 无后缀但文件名像 gerber 层
    lower = path.name.lower()
    return any(token in lower for token in ("gerber", "copper", "soldermask", "paste", "drill"))


def _scan_gerber_dir(package_dir: Path) -> tuple[list[dict], object]:
    audit = audit_gerber_package(package_dir)
    return [f.to_dict() for f in audit.files], audit


def _package_name(path: Path) -> str:
    name = path.name
    if "gerber" in name.lower() or name.upper().endswith("_GB"):
        return name
    return name


def _find_gerber_packages(folder: Path, root: Path) -> list[Path]:
    packages: list[Path] = []
    seen: set[str] = set()
    candidates: list[Path] = [folder]
    candidates.extend(p for p in folder.rglob("*") if p.is_dir())
    for path in candidates:
        if _should_skip_path(path, root):
            continue
        has_candidate = any(_is_candidate_file(item) for item in path.iterdir() if item.is_file())
        if not has_candidate:
            has_candidate = any(_is_candidate_file(item) for item in path.rglob("*") if item.is_file())
        if not has_candidate:
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        packages.append(path)
    packages.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return packages


def _package_gerber_score(pkg_dir: Path) -> tuple[int, object]:
    """按有效层数打分；永联 FAB/SMD 命名加分。无有效层返回 -1。"""
    audit = audit_gerber_package(pkg_dir)
    if audit.gerber_count <= 0:
        return -1, audit
    score = audit.gerber_count * 10 + audit.drill_count
    name = pkg_dir.name.lower()
    if any(k in name for k in ("fab", "gerber", "_gb", "smd")):
        score += 100
    if audit.status == "passed":
        score += 50
    elif audit.status == "warning":
        score += 20
    return score, audit


def _collect_valid_gerber_dirs(search_roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for root in search_roots:
        if not root.is_dir():
            continue
        for pkg in _find_gerber_packages(root, root):
            score, _ = _package_gerber_score(pkg)
            if score < 0:
                continue
            key = str(pkg.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(pkg)
    return found


def _merge_gerber_dirs(dirs: list[Path], dest: Path) -> Path:
    """合并多个有效制板目录（如永联 FAB.zip + SMD.zip）。"""
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    for d in dirs:
        for f in d.rglob("*"):
            if not f.is_file() or not _is_candidate_file(f):
                continue
            name = f.name
            if name.lower() in used:
                name = f"{d.name}_{f.name}"
            used.add(name.lower())
            shutil.copy2(f, dest / name)
    return dest


def _expand_nested_archives(extract_dir: Path, staging: Path) -> list[Path]:
    """解压外层包内的嵌套 zip（永联 PCBA：ASC/FAB/SMD）。"""
    roots: list[Path] = []
    for archive in list_archives(extract_dir, extract_dir, lambda _p, _r: False):
        dest = extract_to_staging(archive, staging)
        if dest:
            roots.append(dest)
            # 再解一层（偶发 zip 套 zip）
            for inner in list_archives(dest, dest, lambda _p, _r: False):
                inner_dest = extract_to_staging(inner, staging / "inner")
                if inner_dest:
                    roots.append(inner_dest)
    return roots


def _resolve_gerber_package_dir(extract_dir: Path, staging: Path) -> Optional[Path]:
    """
    从已解压目录定位可用 Gerber 包。
    菲利斯：层文件直接在包内；永联：常在嵌套 *_FAB.zip / *_SMD.zip。
    """
    nested_roots = _expand_nested_archives(extract_dir, staging / "nested_archives")
    valid = _collect_valid_gerber_dirs([extract_dir, *nested_roots])
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    # 多包时合并（FAB 阻焊丝印 + SMD 钢网）
    combined = staging / "_combined_gerber"
    _merge_gerber_dirs(valid, combined)
    score, _ = _package_gerber_score(combined)
    if score >= 0:
        return combined
    # 回退：取最高分目录
    ranked = sorted(valid, key=lambda p: _package_gerber_score(p)[0], reverse=True)
    return ranked[0]


def _collect_gerber_for_model(
    base: Path,
    customer: dict,
    folder_name: str,
    folder: Path,
    staging_dir: Optional[Path] = None,
) -> list[tuple[Path, str, float]]:
    """返回 (目录, 来源标签, mtime)。"""
    # 仅采纳真正含有效层的目录，避免 PDF/坐标包抢先命中导致跳过压缩包
    packages = _collect_valid_gerber_dirs([folder])
    if packages:
        return [(p, str(p.resolve()), p.stat().st_mtime) for p in packages]
    if staging_dir is not None:
        archive_packages: list[tuple[Path, str, float]] = []
        for archive in list_archives(folder, folder, _should_skip_path):
            extract_root = extract_to_staging(archive, staging_dir)
            if not extract_root:
                continue
            resolved = _resolve_gerber_package_dir(extract_root, staging_dir / f"resolve_{archive.stem}")
            if resolved:
                archive_packages.append(
                    (
                        resolved,
                        archive_source_label(archive, resolved, extract_root),
                        archive.stat().st_mtime,
                    )
                )
                continue
            for pkg_dir in _collect_valid_gerber_dirs([extract_root]):
                archive_packages.append(
                    (pkg_dir, archive_source_label(archive, pkg_dir, extract_root), archive.stat().st_mtime)
                )
        if archive_packages:
            return archive_packages
    ic = (customer.get("internal_code") or "").strip().upper()
    model_key = extract_model_key(folder_name, ic)
    merged: list[tuple[Path, str, float]] = []
    for legacy_root in legacy_asset_roots(customer, base):
        for legacy_dir in match_legacy_dirs(legacy_root, model_key):
            for pkg_dir in _collect_valid_gerber_dirs([legacy_dir]):
                merged.append((pkg_dir, str(pkg_dir.resolve()), pkg_dir.stat().st_mtime))
            if staging_dir is not None:
                for archive in list_archives(legacy_dir, legacy_root, _should_skip_path):
                    extract_root = extract_to_staging(archive, staging_dir)
                    if not extract_root:
                        continue
                    resolved = _resolve_gerber_package_dir(
                        extract_root, staging_dir / f"legacy_{archive.stem}"
                    )
                    if resolved:
                        merged.append(
                            (
                                resolved,
                                archive_source_label(archive, resolved, extract_root),
                                archive.stat().st_mtime,
                            )
                        )
                        continue
                    for pkg_dir in _collect_valid_gerber_dirs([extract_root]):
                        merged.append(
                            (pkg_dir, archive_source_label(archive, pkg_dir, extract_root), archive.stat().st_mtime)
                        )
    if not merged:
        return []
    seen: set[str] = set()
    unique: list[tuple[Path, str, float]] = []
    for pkg_dir, label, mtime in sorted(merged, key=lambda item: item[2], reverse=True):
        key = label
        if key in seen:
            continue
        seen.add(key)
        unique.append((pkg_dir, label, mtime))
    return unique


def upsert_pending_gerber(
    db: Session,
    *,
    internal_code: str,
    model_code: str,
    folder_name: str,
    bom_model_id: Optional[int] = None,
) -> PcbGerberPackage:
    if has_ready_gerber(db, internal_code, model_code):
        row = (
            db.query(PcbGerberPackage)
            .filter(
                PcbGerberPackage.internal_code == internal_code.strip().upper(),
                PcbGerberPackage.model_code == model_code.strip(),
                PcbGerberPackage.file_count > 0,
            )
            .order_by(PcbGerberPackage.id.desc())
            .first()
        )
        if row:
            return row
    ic = internal_code.strip().upper()
    row = (
        db.query(PcbGerberPackage)
        .filter(
            PcbGerberPackage.internal_code == ic,
            PcbGerberPackage.model_code == model_code.strip(),
            PcbGerberPackage.folder_name == folder_name,
            PcbGerberPackage.source == "pending",
        )
        .first()
    )
    now = datetime.utcnow()
    if not row:
        row = PcbGerberPackage(
            internal_code=ic,
            model_code=model_code.strip(),
            folder_name=folder_name,
            package_name="(待导入 Gerber)",
            source_path=f"folder:{folder_name}",
            source="pending",
        )
        db.add(row)
    row.bom_model_id = bom_model_id
    row.files_json = "[]"
    row.file_count = 0
    row.synced_at = now
    row.updated_at = now
    db.flush()
    return row


def upsert_gerber_package(
    db: Session,
    *,
    internal_code: str,
    model_code: str,
    package_dir: Path,
    files: list[dict],
    bom_model_id: Optional[int],
    folder_name: Optional[str],
    source: str = "share",
    source_path_override: Optional[str] = None,
    source_mtime_override: Optional[float] = None,
    audit_status: str = "pending",
    audit_message: str = "",
    purchase_no: str = "",
) -> tuple[PcbGerberPackage, bool]:
    ic = internal_code.strip().upper()
    pkg_name = _package_name(package_dir)
    source_path = source_path_override or str(package_dir.resolve())
    pn = (purchase_no or "").strip()
    row = None
    if bom_model_id:
        row = (
            db.query(PcbGerberPackage)
            .filter(
                PcbGerberPackage.bom_model_id == bom_model_id,
                PcbGerberPackage.package_name == pkg_name,
            )
            .first()
        )
    if not row and pn:
        row = (
            db.query(PcbGerberPackage)
            .filter(
                PcbGerberPackage.internal_code == ic,
                PcbGerberPackage.model_code == model_code.strip(),
                PcbGerberPackage.purchase_no == pn,
                PcbGerberPackage.package_name == pkg_name,
            )
            .first()
        )
    if not row and not pn:
        row = (
            db.query(PcbGerberPackage)
            .filter(
                PcbGerberPackage.internal_code == ic,
                PcbGerberPackage.model_code == model_code.strip(),
                PcbGerberPackage.package_name == pkg_name,
            )
            .filter(
                (PcbGerberPackage.purchase_no == "") | (PcbGerberPackage.purchase_no.is_(None))
            )
            .first()
        )
    created = row is None
    now = datetime.utcnow()
    if not row:
        row = PcbGerberPackage(
            internal_code=ic,
            model_code=model_code.strip(),
            package_name=pkg_name,
            source_path=source_path,
        )
        db.add(row)
    row.bom_model_id = bom_model_id
    row.purchase_no = pn
    row.folder_name = folder_name
    row.source_path = source_path
    row.files_json = json.dumps(files, ensure_ascii=False)
    row.file_count = len(files)
    row.audit_status = audit_status or "pending"
    row.audit_message = audit_message or ""
    row.source_mtime = source_mtime_override if source_mtime_override is not None else package_dir.stat().st_mtime
    row.source = source
    row.synced_at = now
    row.updated_at = now
    db.flush()
    if row.file_count > 0 and is_gerber_usable(row.audit_status):
        purge_superseded_gerbers(
            db,
            ic,
            model_code.strip(),
            row.id,
            purchase_no=pn,
            bom_model_id=bom_model_id,
        )
    return row, created


def import_gerber_directory(
    db: Session,
    package_dir: Path,
    *,
    internal_code: str,
    model_code: str,
    bom_model_id: Optional[int] = None,
    folder_name: Optional[str] = None,
    source: str = "share",
    source_path_override: Optional[str] = None,
    source_mtime_override: Optional[float] = None,
    purchase_no: str = "",
) -> dict:
    item = {
        "internal_code": internal_code,
        "model_code": model_code,
        "package": package_dir.name,
        "status": "success",
        "message": "",
        "file_count": 0,
        "gerber_package_id": 0,
        "audit_status": "pending",
        "audit_message": "",
    }
    try:
        files, audit = _scan_gerber_dir(package_dir)
        item["audit_status"] = audit.status
        item["audit_message"] = audit.message
        if audit.status == "failed":
            raise ValueError(audit.message)
        if not files:
            raise ValueError("目录内无 Gerber 文件")
        row, created = upsert_gerber_package(
            db,
            internal_code=internal_code,
            model_code=model_code,
            package_dir=package_dir,
            files=files,
            bom_model_id=bom_model_id,
            folder_name=folder_name,
            source=source,
            source_path_override=source_path_override,
            source_mtime_override=source_mtime_override,
            audit_status=audit.status,
            audit_message=audit.message,
            purchase_no=purchase_no,
        )
        item["file_count"] = len(files)
        item["gerber_package_id"] = row.id
        audit_hint = "（审核警告）" if audit.status == "warning" else "（审核通过）"
        archive_hint = "（已从压缩包导入）" if (source_path_override or "").startswith(("zip:", "rar:")) else ""
        item["message"] = f"{'新增' if created else '更新'} {len(files)} 个文件{archive_hint}{audit_hint}：{audit.message}"
        item["_created"] = 1 if created else 0
        item["_updated"] = 0 if created else 1
        db.add(
            ExcelImportLog(
                source_file=str(package_dir),
                customer_name=f"{internal_code}/{model_code}/gerber",
                rows_imported=len(files),
                rows_updated=0 if created else 1,
                status="success",
                message=item["message"],
            )
        )
    except Exception as exc:
        logger.exception("Gerber 导入失败 %s", package_dir)
        item["status"] = "failed"
        item["message"] = str(exc)
        item["_created"] = 0
        item["_updated"] = 0
    return item


def import_gerber_zip(
    db: Session,
    content: bytes,
    filename: str,
    *,
    internal_code: str,
    model_code: str,
    bom_model_id: Optional[int] = None,
    purchase_no: str = "",
) -> dict:
    from archive_assets import extract_archive

    safe_name = Path(filename).name or "gerber.zip"
    suffix = Path(safe_name).suffix.lower()
    with tempfile.TemporaryDirectory() as td:
        archive_path = Path(td) / safe_name
        archive_path.write_bytes(content)
        extract_dir = Path(td) / "extracted"
        extract_dir.mkdir()
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(extract_dir)
            except zipfile.BadZipFile:
                return {
                    "status": "failed",
                    "message": "不是有效的 ZIP 文件",
                    "file_count": 0,
                    "gerber_package_id": 0,
                    "internal_code": internal_code,
                    "model_code": model_code,
                    "package": safe_name,
                }
        elif suffix in (".7z", ".rar"):
            if not extract_archive(archive_path, extract_dir):
                return {
                    "status": "failed",
                    "message": f"{suffix.upper()} 解压失败，请确认文件完整或改用 ZIP",
                    "file_count": 0,
                    "gerber_package_id": 0,
                    "internal_code": internal_code,
                    "model_code": model_code,
                    "package": safe_name,
                }
        else:
            return {
                "status": "failed",
                "message": "请上传 ZIP / 7z / RAR 压缩包",
                "file_count": 0,
                "gerber_package_id": 0,
                "internal_code": internal_code,
                "model_code": model_code,
                "package": safe_name,
            }
        # 永联 PCBA 包：层在嵌套 FAB.zip（.gdo）；菲利斯：层直接在包内（.gtl/.gbl）
        pkg_dir = _resolve_gerber_package_dir(extract_dir, Path(td))
        if not pkg_dir:
            names = sorted(
                p.name for p in extract_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
            )[:8]
            hint = f"（外层见：{'、'.join(names)}）" if names else ""
            return {
                "status": "failed",
                "message": (
                    f"未找到有效 Gerber 层文件{hint}。"
                    "请上传含 .gtl/.gbl/.gbr 或 Mentor .gdo 等层的制板包；"
                    "若是含嵌套 FAB/SMD 的 PCBA 总包，系统会自动解开其中的 *_FAB.zip / *_SMD.zip。"
                    "DXF/PDF/装配图不能代替 Gerber。"
                ),
                "file_count": 0,
                "gerber_package_id": 0,
                "audit_status": "failed",
                "audit_message": "压缩包内未找到有效 Gerber 层",
                "internal_code": internal_code,
                "model_code": model_code,
                "package": safe_name,
            }
        result = import_gerber_directory(
            db,
            pkg_dir,
            internal_code=internal_code,
            model_code=model_code,
            bom_model_id=bom_model_id,
            source="manual",
            purchase_no=purchase_no,
        )
        if result.get("status") == "success":
            row = db.query(PcbGerberPackage).filter(PcbGerberPackage.id == result["gerber_package_id"]).first()
            if row:
                row.source_path = f"upload:{safe_name}"
        result["package"] = safe_name
        return result


def sync_gerbers_from_share(
    db: Session,
    internal_codes: Optional[list[str]] = None,
) -> dict:
    """已停用：Gerber 仅人工导入，不再扫描本地共享盘。"""
    return {
        "status": "disabled",
        "message": "Gerber 已改为人工导入，不再从本地共享盘同步",
        "packages": [],
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "pending": 0,
        "failed": 0,
        "share_path": "",
    }


def list_gerber_packages(db: Session, internal_code: str = "", keyword: str = "") -> list[dict]:
    q = db.query(PcbGerberPackage).order_by(
        PcbGerberPackage.internal_code.asc(),
        PcbGerberPackage.model_code.asc(),
        PcbGerberPackage.id.desc(),
    )
    if internal_code:
        q = q.filter(PcbGerberPackage.internal_code == internal_code.strip().upper())
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(
            (PcbGerberPackage.model_code.like(like))
            | (PcbGerberPackage.package_name.like(like))
            | (PcbGerberPackage.folder_name.like(like))
            | (PcbGerberPackage.source_path.like(like))
        )
    rows = q.limit(2000).all()
    by_model: dict[tuple[str, str], PcbGerberPackage] = {}
    for row in rows:
        model_key = (row.model_code or "").strip()
        key = (row.internal_code, model_key)
        existing = by_model.get(key)
        if not existing:
            by_model[key] = row
            continue
        picked = pick_canonical_gerber([existing, row])
        if picked:
            by_model[key] = picked
    ordered = sorted(
        by_model.values(),
        key=lambda r: (r.internal_code, r.model_code, r.id),
    )
    return [_pkg_to_dict(row) for row in ordered[:500]]


def get_gerber_meta(db: Session) -> dict:
    count = db.query(PcbGerberPackage).count()
    latest = db.query(PcbGerberPackage.synced_at).order_by(PcbGerberPackage.id.desc()).first()
    by_code = {}
    for ic in ("A123", "A116"):
        by_code[ic] = (
            db.query(PcbGerberPackage)
            .filter(PcbGerberPackage.internal_code == ic)
            .count()
        )
    return {
        "share_path": "",
        "share_accessible": False,
        "assets_share_sync_enabled": False,
        "import_mode": "manual",
        "package_count": count,
        "a123_count": by_code.get("A123", 0),
        "a116_count": by_code.get("A116", 0),
        "synced_at": latest[0] if latest else None,
    }


def get_gerber_files(db: Session, package_id: int) -> list[dict]:
    row = db.query(PcbGerberPackage).filter(PcbGerberPackage.id == package_id).first()
    if not row or not row.files_json:
        return []
    try:
        return json.loads(row.files_json)
    except json.JSONDecodeError:
        return []


def remove_gerber_file(db: Session, package_id: int, file_name: str) -> dict:
    from placement_canonical import delete_gerber_package

    row = db.query(PcbGerberPackage).filter(PcbGerberPackage.id == package_id).first()
    if not row:
        raise ValueError("资料包不存在")
    target = file_name.strip()
    if not target:
        raise ValueError("请指定文件名")

    files = get_gerber_files(db, package_id)
    removed = next((f for f in files if str(f.get("name") or "") == target), None)
    if not removed:
        raise ValueError("文件不在资料包中")
    if removed.get("valid") is not False:
        raise ValueError("仅允许删除不合规文件")

    remaining = [f for f in files if str(f.get("name") or "") != target]
    if not remaining:
        delete_gerber_package(db, package_id)
        return {
            "gerber_package_id": package_id,
            "removed_name": target,
            "deleted_package": True,
            "audit_status": "pending",
            "audit_message": "",
            "file_count": 0,
            "files": [],
        }

    audit = audit_files_metadata(remaining)
    row.files_json = json.dumps([f.to_dict() for f in audit.files], ensure_ascii=False)
    row.file_count = len(audit.files)
    row.audit_status = audit.status
    row.audit_message = audit.message
    row.updated_at = datetime.utcnow()
    return {
        "gerber_package_id": row.id,
        "removed_name": target,
        "deleted_package": False,
        "audit_status": audit.status,
        "audit_message": audit.message,
        "file_count": row.file_count,
        "files": [f.to_dict() for f in audit.files],
    }


def reaudit_gerber_package(db: Session, package_id: int) -> dict:
    row = db.query(PcbGerberPackage).filter(PcbGerberPackage.id == package_id).first()
    if not row:
        raise ValueError("资料包不存在")
    files = get_gerber_files(db, package_id)
    audit = audit_files_metadata(files)
    row.audit_status = audit.status
    row.audit_message = audit.message
    row.files_json = json.dumps([f.to_dict() for f in audit.files], ensure_ascii=False)
    row.file_count = len(audit.files)
    row.updated_at = datetime.utcnow()
    return {
        "gerber_package_id": row.id,
        "audit_status": audit.status,
        "audit_message": audit.message,
        "file_count": row.file_count,
        "files": [f.to_dict() for f in audit.files],
    }


def reaudit_all_gerber_packages(db: Session) -> int:
    updated = 0
    for row in db.query(PcbGerberPackage).filter(PcbGerberPackage.file_count > 0).all():
        files = get_gerber_files(db, row.id)
        if not files:
            row.audit_status = "failed"
            row.audit_message = "无文件记录"
            updated += 1
            continue
        audit = audit_files_metadata(files)
        row.audit_status = audit.status
        row.audit_message = audit.message
        row.files_json = json.dumps([f.to_dict() for f in audit.files], ensure_ascii=False)
        updated += 1
    return updated


def _pkg_to_dict(row: PcbGerberPackage) -> dict:
    usable = is_gerber_usable(row.audit_status)
    if (row.file_count or 0) <= 0:
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
        "package_name": row.package_name,
        "folder_name": row.folder_name,
        "source_path": row.source_path,
        "file_count": row.file_count,
        "source": row.source,
        "status": status,
        "audit_status": row.audit_status or "pending",
        "audit_message": row.audit_message or "",
        "synced_at": row.synced_at,
        "updated_at": row.updated_at,
    }


def gerber_export_content_disposition(filename: str) -> str:
    from urllib.parse import quote

    safe = Path(filename or "gerber.zip").name or "gerber.zip"
    ascii_name = "gerber.zip"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(safe)}'


def build_gerber_export_zip(db: Session, package_id: int) -> tuple[bytes, str]:
    """从源目录打包 Gerber（只读下载）。源路径不可用时抛出 ValueError。"""
    row = db.query(PcbGerberPackage).filter(PcbGerberPackage.id == package_id).first()
    if not row:
        raise ValueError("Gerber 资料包不存在")

    src = (row.source_path or "").strip()
    if not src or src.startswith("upload:"):
        raise ValueError("该 Gerber 为上传导入且未保留源目录，无法再导出；请重新上传")

    pkg_dir = Path(src)
    if not pkg_dir.is_dir():
        raise ValueError(f"源目录不存在或不可访问：{src}")

    files = [
        p
        for p in sorted(pkg_dir.rglob("*"))
        if p.is_file() and not p.name.startswith(".")
    ]
    if not files:
        raise ValueError("源目录内没有可导出的文件")

    buf = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = path.relative_to(pkg_dir).as_posix()
            zf.write(path, arcname)
    buf.seek(0)
    content = buf.read()
    buf.close()

    base = (row.package_name or row.model_code or f"gerber_{package_id}").strip()
    safe = re.sub(r"[\\/:*?\"<>|]+", "_", base) or f"gerber_{package_id}"
    filename = f"{safe}.zip" if not safe.lower().endswith(".zip") else safe
    return content, filename
