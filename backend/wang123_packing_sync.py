"""旧站已包装数据 → 冷表 + order_scans（默认 shipped）。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from board_gate import norm_barcode
from models import LegacyPackingScan, OrderScan, SrmOrder
from wang123_client import Wang123Client

logger = logging.getLogger(__name__)

OPERATOR_TAG = "legacy:wang123"


def _parse_dt(text: Optional[str]) -> Optional[datetime]:
    raw = (text or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def resolve_line_key(db: Session, order_no: str, product_code: str = "") -> Optional[SrmOrder]:
    po = (order_no or "").strip()
    if not po:
        return None
    model = (product_code or "").strip()
    q = db.query(SrmOrder).filter(SrmOrder.purchase_no == po)
    rows = q.all()
    if not rows:
        return None
    if model:
        for r in rows:
            if (r.product_goods_no or "").strip() == model:
                return r
    # 优先未结案
    open_rows = [r for r in rows if not r.is_completed]
    return (open_rows or rows)[0]


def upsert_legacy_row(db: Session, row: dict) -> LegacyPackingScan:
    remote_id = int(row.get("id") or 0)
    barcode = (row.get("barcode") or "").strip()
    bnorm = norm_barcode(barcode) if barcode else ""
    existing = None
    if remote_id:
        existing = db.query(LegacyPackingScan).filter(LegacyPackingScan.remote_id == remote_id).first()
    if not existing and bnorm:
        existing = db.query(LegacyPackingScan).filter(LegacyPackingScan.barcode_norm == bnorm).first()
    now = datetime.utcnow()
    if not existing:
        existing = LegacyPackingScan(remote_id=remote_id or None, created_at=now)
        db.add(existing)
    existing.barcode = barcode
    existing.barcode_norm = bnorm
    existing.order_no = (row.get("orderNo") or "").strip()
    existing.product_code = (row.get("productCode") or "").strip()
    existing.product_name = (row.get("productName") or "").strip()
    existing.package_no = (row.get("packageNo") or "").strip()
    existing.package_status = str(row.get("packageStatus") or "")
    existing.package_at = _parse_dt(row.get("packageTestPassTime"))
    existing.remote_updated_at = _parse_dt(row.get("updateTime")) or _parse_dt(row.get("createTime"))
    existing.raw_json = json.dumps(row, ensure_ascii=False)
    existing.updated_at = now
    return existing


def link_to_order_scans(
    db: Session,
    legacy: LegacyPackingScan,
    *,
    default_status: str = "shipped",
) -> str:
    """匹配订单并写入/更新 order_scans。返回 matched|unmatched|skipped|exists。"""
    if not legacy.barcode_norm:
        legacy.match_status = "skipped"
        return "skipped"
    order = resolve_line_key(db, legacy.order_no, legacy.product_code)
    if not order:
        legacy.match_status = "unmatched"
        legacy.line_key = None
        return "unmatched"

    legacy.line_key = order.line_key
    legacy.match_status = "matched"
    existing = db.query(OrderScan).filter(OrderScan.barcode == legacy.barcode_norm).first()
    scanned_at = legacy.package_at or legacy.remote_updated_at or datetime.utcnow()
    if existing:
        # 不覆盖本系统新扫码的 pending；仅补齐历史
        if (existing.operator or "").startswith("legacy:") or existing.status == "shipped":
            if existing.line_key != order.line_key:
                existing.line_key = order.line_key
                existing.purchase_no = order.purchase_no
            legacy.synced_to_scans = True
            return "exists"
        legacy.synced_to_scans = True
        return "exists"

    status = default_status if default_status in ("pending", "shipped") else "shipped"
    scan = OrderScan(
        line_key=order.line_key,
        purchase_no=order.purchase_no or legacy.order_no,
        barcode=legacy.barcode_norm,
        code_type="legacy",
        status=status,
        shipment_id=None,
        operator=OPERATOR_TAG,
        scanned_at=scanned_at,
        shipped_at=scanned_at if status == "shipped" else None,
    )
    db.add(scan)
    legacy.synced_to_scans = True
    return "matched"


def sync_packaged_from_wang123(
    db: Session,
    client: Wang123Client,
    *,
    full: bool = True,
    page_size: int = 200,
    default_status: str = "shipped",
    commit_every: int = 200,
) -> dict:
    """拉取已包装并写入冷表/热表。"""
    client.ensure_token()
    first = client.list_packaged_page(1, page_size)
    total = first["total"]
    stats = {
        "remote_total": total,
        "fetched": 0,
        "cold_upsert": 0,
        "linked": 0,
        "unmatched": 0,
        "skipped": 0,
        "exists": 0,
        "errors": 0,
    }

    def handle_rows(rows: list[dict]):
        for row in rows:
            stats["fetched"] += 1
            try:
                legacy = upsert_legacy_row(db, row)
                stats["cold_upsert"] += 1
                result = link_to_order_scans(db, legacy, default_status=default_status)
                if result == "matched":
                    stats["linked"] += 1
                elif result == "unmatched":
                    stats["unmatched"] += 1
                elif result == "exists":
                    stats["exists"] += 1
                else:
                    stats["skipped"] += 1
            except Exception:
                stats["errors"] += 1
                logger.exception("wang123 row fail id=%s", row.get("id"))
            if stats["fetched"] % commit_every == 0:
                db.commit()

    handle_rows(first["list"])
    pages = max(1, (total + page_size - 1) // page_size)
    # full 或增量：增量同样翻页（量约 1 万，可接受）；后续可按 updateTime 优化
    start_page = 2 if full or True else 2
    for page in range(start_page, pages + 1):
        chunk = client.list_packaged_page(page, page_size)
        handle_rows(chunk["list"])
        logger.info("wang123 sync page %s/%s fetched=%s", page, pages, stats["fetched"])

    db.commit()
    stats["message"] = (
        f"旧站已包装同步完成：远端 {total}，入库冷表 {stats['cold_upsert']}，"
        f"挂单 {stats['linked']}，未匹配 {stats['unmatched']}，已存在 {stats['exists']}"
    )
    return stats
