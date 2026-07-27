"""工程资料发现：主目录机型文件夹 + A123 历史库回退匹配"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from bom_excel import SKIP_FOLDER_PREFIXES, SKIP_TOP_FOLDERS

logger = logging.getLogger(__name__)


def primary_model_root(customer: dict, base: Path) -> Optional[Path]:
    bom_folder = (customer.get("bom_folder") or "").strip()
    if not bom_folder:
        return None
    path = base / bom_folder
    return path if path.is_dir() else None


def legacy_asset_roots(customer: dict, base: Path) -> list[Path]:
    roots: list[Path] = []
    for name in customer.get("asset_folders") or []:
        text = str(name).strip()
        if not text:
            continue
        path = base / text
        if path.is_dir():
            roots.append(path)
    return roots


def extract_model_key(folder_name: str, internal_code: str) -> str:
    text = folder_name.strip()
    from eng_customer_rules import get_customer_rules

    rules = get_customer_rules(internal_code)
    pattern = (rules.get("model_key_regex") or "").strip()
    if pattern:
        try:
            m = re.search(pattern, text)
            if m:
                return m.group(1) if m.lastindex else m.group(0)
        except re.error:
            logger.warning("客户 %s model_key_regex 无效: %s", internal_code, pattern)
    # 兼容旧默认：无配置时沿用历史逻辑
    if (internal_code or "").strip().upper() == "A123":
        m = re.search(r"(1\d{2}-\d{6}-\d{2})", text)
        if m:
            return m.group(1)
        return text.split("/")[0].split()[0]
    m = re.match(r"(0\d{7,8})", text)
    if m:
        return m.group(1)
    m = re.match(r"(99\d{6,8})", text)
    if m:
        return m.group(1)
    return text.split("_")[0].split()[0]


def match_legacy_dirs(legacy_root: Path, model_key: str) -> list[Path]:
    """在 A123 等历史目录中按机型料号匹配 Gerber/坐标文件夹。"""
    if not legacy_root.is_dir() or not model_key:
        return []
    key = model_key.strip()
    patterns = (
        key,
        f"({key})",
        f"（{key}）",
        f"({key}）",
        f"（{key})",
        f"新{key}",
    )
    found: list[Path] = []
    for sub in legacy_root.iterdir():
        if not sub.is_dir():
            continue
        name = sub.name
        if any(p in name for p in patterns):
            found.append(sub)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def iter_primary_model_folders(root: Path):
    if not root.is_dir():
        return
    try:
        entries = sorted(root.iterdir())
    except OSError as exc:
        logger.warning("无法遍历工程共享盘目录 %s: %s", root, exc)
        return
    for sub in entries:
        try:
            if not sub.is_dir():
                continue
        except OSError:
            continue
        if any(sub.name.startswith(p) for p in SKIP_FOLDER_PREFIXES):
            continue
        if sub.name in SKIP_TOP_FOLDERS:
            continue
        yield sub.name, sub
