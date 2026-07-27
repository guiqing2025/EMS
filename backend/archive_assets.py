"""共享盘压缩包解压与工程资料扫描（坐标 / Gerber）"""
from __future__ import annotations

import logging
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z")


def list_archives(folder: Path, root: Path, should_skip) -> list[Path]:
    archives: list[Path] = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ARCHIVE_SUFFIXES:
            continue
        if should_skip(path, root):
            continue
        archives.append(path)
    archives.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return archives


def extract_archive(archive: Path, dest: Path) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                _extract_zip_gbk_safe(zf, dest)
            return True
        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning("ZIP 解压失败 %s: %s", archive, exc)
            return False
    if suffix == ".rar":
        for cmd in (
            ["unar", "-q", "-o", str(dest), str(archive)],
            ["bsdtar", "-xf", str(archive), "-C", str(dest)],
            ["7z", "x", f"-o{dest}", str(archive), "-y"],
        ):
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=180)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                continue
        logger.warning("RAR 解压失败（需 unar / bsdtar / 7z）: %s", archive)
        return False
    if suffix == ".7z":
        for cmd in (
            ["7z", "x", f"-o{dest}", str(archive), "-y"],
            ["bsdtar", "-xf", str(archive), "-C", str(dest)],
            ["unar", "-q", "-o", str(dest), str(archive)],
        ):
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=180)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                continue
        logger.warning("7z 解压失败（需 bsdtar / 7z / unar）: %s", archive)
        return False
    return False


def _decode_zip_name(name: str) -> str:
    """ZIP 内中文名常见为 GBK，用 cp437 误读后需还原。"""
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for enc in ("gbk", "gb18030", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


def _extract_zip_gbk_safe(zf: zipfile.ZipFile, dest: Path) -> None:
    """避免 macOS 对 GBK 中文路径 extractall 失败（Illegal byte sequence）。"""
    for info in zf.infolist():
        name = _decode_zip_name(info.filename)
        # 防止路径穿越
        target = (dest / name).resolve()
        if not str(target).startswith(str(dest.resolve())):
            continue
        if info.is_dir() or name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            out.write(src.read())


def extract_to_staging(archive: Path, staging_root: Path) -> Optional[Path]:
    key = f"{archive.name}_{int(archive.stat().st_mtime)}"
    dest = staging_root / key
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    if not extract_archive(archive, dest):
        return None
    return dest


def archive_source_label(archive: Path, inner: Path, extract_root: Path) -> str:
    try:
        rel = inner.relative_to(extract_root).as_posix()
    except ValueError:
        rel = inner.name
    kind = archive.suffix.lower().lstrip(".") or "archive"
    return f"{kind}:{archive.name}/{rel}"
