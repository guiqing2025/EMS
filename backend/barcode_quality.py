"""条码校验（开发桩：完整实现未包含在本源码包中）。"""
from __future__ import annotations

import re


_BARCODE_RE = re.compile(r"^[A-Za-z0-9\-_.]{4,64}$")


def purge_truncated_suffixes(code: str = "", **_kwargs) -> str:
    text = (code or "").strip()
    for suffix in ("-P", "-F", "-R", "_P", "_F"):
        if text.upper().endswith(suffix):
            return text[: -len(suffix)]
    return text


def validate_packing_barcode(code: str = "", **_kwargs) -> str:
    text = purge_truncated_suffixes(code)
    if not text or not _BARCODE_RE.match(text):
        raise ValueError("条码格式无效")
    return text


def is_plausible_aoi_barcode(code: str = "") -> bool:
    text = (code or "").strip()
    return bool(text) and len(text) >= 4 and bool(_BARCODE_RE.match(text))
