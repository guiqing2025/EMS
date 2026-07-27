"""位号图 PDF 页面渲染为图片预览"""
from __future__ import annotations

import fitz
from sqlalchemy.orm import Session

from refmap_sync import get_refmap_pdf_path


def render_refmap_page_png(
    db: Session,
    file_id: int,
    *,
    page: int = 1,
    scale: float = 1.6,
) -> tuple[bytes, int, int]:
    path = get_refmap_pdf_path(db, file_id)
    doc = fitz.open(path)
    try:
        total = doc.page_count
        if total <= 0:
            raise ValueError("PDF 无有效页面")
        page_idx = max(0, min(page - 1, total - 1))
        pixmap = doc.load_page(page_idx).get_pixmap(
            matrix=fitz.Matrix(scale, scale),
            alpha=False,
        )
        return pixmap.tobytes("png"), page_idx + 1, total
    finally:
        doc.close()
