"""位号图（装配图 PDF）审核"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REFMAP_NAME_HINTS = (
    "位号图",
    "位号",
    "丝印图",
    "丝印",
    "refmap",
    "ref_des",
    "refdes",
    "assembly",
    "asm",
    "装配",
    "贴装图",
    "元件图",
    "silkscreen",
    "silk",
    "component",
)


@dataclass
class RefmapAudit:
    status: str = "pending"
    message: str = ""
    file_name: str = ""
    file_size: int = 0
    page_count: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "page_count": self.page_count,
        }


def is_refmap_usable(status: Optional[str]) -> bool:
    return (status or "").strip() in ("passed", "warning")


def audit_status_label(status: Optional[str]) -> str:
    return {
        "passed": "审核通过",
        "warning": "审核警告",
        "failed": "审核未通过",
        "pending": "待审核",
    }.get((status or "").strip(), "待审核")


def _name_matches_refmap(name: str) -> bool:
    lower = (name or "").lower()
    return any(hint in lower for hint in REFMAP_NAME_HINTS)


def _is_pdf_bytes(content: bytes) -> bool:
    return content[:5] == b"%PDF-"


def _count_pdf_pages(content: bytes) -> int:
    try:
        text = content.decode("latin-1", errors="ignore")
    except Exception:
        return 0
    matches = re.findall(r"/Type\s*/Page\b", text)
    return max(len(matches), 1 if _is_pdf_bytes(content) else 0)


def audit_refmap_path(path: Path) -> RefmapAudit:
    result = RefmapAudit(file_name=path.name)
    if not path.is_file():
        result.status = "failed"
        result.message = "文件不存在"
        return result
    content = path.read_bytes()
    return audit_refmap_bytes(content, path.name)


def audit_refmap_bytes(content: bytes, file_name: str = "") -> RefmapAudit:
    result = RefmapAudit(file_name=file_name or "unknown.pdf", file_size=len(content or b""))
    if not content:
        result.status = "failed"
        result.message = "文件为空"
        return result
    if not _is_pdf_bytes(content):
        result.status = "failed"
        result.message = "位号图须为 PDF 格式（%PDF- 文件头）"
        return result
    result.page_count = _count_pdf_pages(content)
    if result.page_count <= 0:
        result.status = "failed"
        result.message = "PDF 无法读取或页数为 0"
        return result
    name_ok = _name_matches_refmap(file_name)
    size_kb = max(1, result.file_size // 1024)
    if name_ok:
        result.status = "passed"
        result.message = f"审核通过：位号图 PDF，{result.page_count} 页，{size_kb} KB"
        return result
    result.status = "warning"
    result.message = (
        f"有效 PDF（{result.page_count} 页，{size_kb} KB），"
        f"但文件名未含位号图/丝印图/ASM 等关键字，请确认是否为装配位号图"
    )
    return result


def audit_refmap_record(
    *,
    file_name: str,
    file_size: int,
    page_count: int,
    source_path: str = "",
) -> RefmapAudit:
    name = file_name or (Path(source_path).name if source_path else "")
    if file_size <= 0 or not name:
        return RefmapAudit(
            status="failed",
            message="尚未导入有效位号图",
            file_name=name,
            file_size=file_size,
            page_count=page_count,
        )
    size_kb = max(1, file_size // 1024)
    if _name_matches_refmap(name):
        return RefmapAudit(
            status="passed",
            message=f"审核通过：位号图 PDF，{page_count or 1} 页，{size_kb} KB",
            file_name=name,
            file_size=file_size,
            page_count=page_count,
        )
    return RefmapAudit(
        status="warning",
        message=(
            f"有效 PDF（{page_count or 1} 页，{size_kb} KB），"
            f"但文件名未含位号图/丝印图/ASM 等关键字，请确认是否为装配位号图"
        ),
        file_name=name,
        file_size=file_size,
        page_count=page_count,
    )
