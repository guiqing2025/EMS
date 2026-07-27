"""工程客户资料本地归档（位号图 PDF 等）"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from models import PcbRefmapFile

REFMAP_STORE_ROOT = Path(__file__).parent / "data" / "refmaps"


def _safe_segment(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "_"
    return re.sub(r"[^\w\-.]+", "_", text)[:120]


def refmap_store_path(internal_code: str, model_code: str, file_id: int, file_name: str) -> Path:
    ic = _safe_segment(internal_code.upper())
    mc = _safe_segment(model_code)
    name = Path(file_name or "refmap.pdf").name
    return REFMAP_STORE_ROOT / ic / mc / f"{file_id}_{name}"


def save_refmap_pdf(
    *,
    internal_code: str,
    model_code: str,
    file_id: int,
    file_name: str,
    content: bytes,
) -> Path:
    path = refmap_store_path(internal_code, model_code, file_id, file_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def delete_refmap_store_file(internal_code: str, model_code: str, file_id: int, file_name: str) -> None:
    path = refmap_store_path(internal_code, model_code, file_id, file_name)
    if path.is_file():
        path.unlink()


def resolve_refmap_pdf(row: PcbRefmapFile) -> Optional[Path]:
    if not row or not row.file_name:
        return None
    stored = refmap_store_path(row.internal_code, row.model_code, row.id, row.file_name)
    if stored.is_file():
        return stored

    source = (row.source_path or "").strip()
    if source.startswith("store:"):
        rel = source[6:].lstrip("/\\")
        path = REFMAP_STORE_ROOT / rel
        if path.is_file():
            return path
    if source.startswith("upload:"):
        return None
    if source:
        path = Path(source)
        if path.is_file():
            return path
    return None
