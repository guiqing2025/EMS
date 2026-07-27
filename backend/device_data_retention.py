"""设备侧数据保留：sync 去重文件按 lookback / 保留期清理，避免与业务表抢 IO。

板测结果（aoi/ict_board_results）暂不删——订单侧仍要查历史板码；
冷热归档（热表 + 月度历史表）待行数到百万级再做。
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 去重元数据默认保留 14 天（应 ≥ ICT/AOI lookback，避免删完又重扫）
DEFAULT_SYNC_FILE_RETENTION_DAYS = 14
BATCH_SIZE = 5000


def sync_file_retention_days() -> int:
    raw = (os.environ.get("EMS_SYNC_FILE_RETENTION_DAYS") or "").strip()
    if raw.isdigit():
        return max(7, min(int(raw), 730))
    return DEFAULT_SYNC_FILE_RETENTION_DAYS


def _ict_lookback_days() -> int:
    try:
        from config import load_config

        ict = load_config().get("ict") or {}
        return max(1, int(ict.get("lookback_days") or 7))
    except Exception:
        return 7


def _aoi_lookback_days() -> int:
    try:
        from config import load_config

        aoi = load_config().get("aoi") or {}
        return max(1, int(aoi.get("lookback_days") or 14))
    except Exception:
        return 14


def _purge_by_ids(db: Session, table: str, sql: str, params: dict) -> int:
    total = 0
    while True:
        result = db.execute(text(sql), {**params, "lim": BATCH_SIZE})
        n = result.rowcount or 0
        db.commit()
        total += n
        if n < BATCH_SIZE:
            break
    return total


def _purge_table_by_processed_at(db: Session, table: str, cutoff: datetime) -> int:
    return _purge_by_ids(
        db,
        table,
        f"""
        DELETE FROM {table}
        WHERE id IN (
            SELECT id FROM {table}
            WHERE processed_at IS NOT NULL AND processed_at < :cutoff
            ORDER BY id
            LIMIT :lim
        )
        """,
        {"cutoff": cutoff},
    )


def _purge_table_by_file_mtime(db: Session, table: str, cutoff_ts: float) -> int:
    """删除 lookback 之外的去重记录（这些文件同步时本就不会再扫）。"""
    return _purge_by_ids(
        db,
        table,
        f"""
        DELETE FROM {table}
        WHERE id IN (
            SELECT id FROM {table}
            WHERE file_mtime IS NOT NULL AND file_mtime < :cutoff_ts
            ORDER BY id
            LIMIT :lim
        )
        """,
        {"cutoff_ts": cutoff_ts},
    )


def purge_old_sync_files(db: Session, days: Optional[int] = None) -> dict[str, Any]:
    """清理过期的 ICT/AOI 同步文件去重记录。

    策略：
    1) 按 file_mtime 删掉已超出 lookback 的登记（立刻瘦身，且不会被重扫）
    2) 再按 processed_at 删掉超过保留期的残留
    """
    retain = sync_file_retention_days() if days is None else max(7, int(days))
    ict_lookback = _ict_lookback_days()
    aoi_lookback = _aoi_lookback_days()
    # 保留略宽于 lookback，防止边界抖动
    ict_mtime_days = max(retain, ict_lookback)
    aoi_mtime_days = max(retain, aoi_lookback)
    now_ts = time.time()
    processed_cutoff = datetime.utcnow() - timedelta(days=retain)

    out: dict[str, Any] = {
        "retention_days": retain,
        "ict_lookback_days": ict_lookback,
        "aoi_lookback_days": aoi_lookback,
        "processed_cutoff": processed_cutoff.isoformat(sep=" ", timespec="seconds"),
        "ict_sync_files_mtime": 0,
        "aoi_sync_files_mtime": 0,
        "ict_sync_files": 0,
        "aoi_sync_files": 0,
    }
    try:
        out["ict_sync_files_mtime"] = _purge_table_by_file_mtime(
            db, "ict_sync_files", now_ts - ict_mtime_days * 86400
        )
        out["aoi_sync_files_mtime"] = _purge_table_by_file_mtime(
            db, "aoi_sync_files", now_ts - aoi_mtime_days * 86400
        )
        out["ict_sync_files"] = _purge_table_by_processed_at(db, "ict_sync_files", processed_cutoff)
        out["aoi_sync_files"] = _purge_table_by_processed_at(db, "aoi_sync_files", processed_cutoff)
        logger.info(
            "设备 sync 文件清理完成：保留 %s 天，ict_lookback=%s，"
            "ict_mtime=%s aoi_mtime=%s ict_proc=%s aoi_proc=%s",
            retain,
            ict_lookback,
            out["ict_sync_files_mtime"],
            out["aoi_sync_files_mtime"],
            out["ict_sync_files"],
            out["aoi_sync_files"],
        )
    except Exception:
        logger.exception("设备 sync 文件清理失败")
        db.rollback()
        raise
    return out
