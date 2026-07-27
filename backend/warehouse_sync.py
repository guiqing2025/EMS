"""仓库物料定时同步"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from models import ExcelImportLog
from warehouse_excel import sync_all_from_share

logger = logging.getLogger(__name__)


def sync_warehouse_materials(db: Session) -> tuple[str, list[ExcelImportLog]]:
    logs, summary = sync_all_from_share(db)
    failed = [log for log in logs if log.status != "success"]
    if failed and not any(log.status == "success" for log in logs):
        tip = failed[0].message or "未知错误"
        if "忙" in tip or "locked" in tip.lower():
            raise RuntimeError(f"共享盘同步全部失败（数据库正忙，请稍后再试）: {tip}")
        raise RuntimeError(f"共享盘同步全部失败: {tip}")
    if failed:
        summary += f"；{len(failed)} 个客户文件失败"
    logger.info("仓库同步完成: %s", summary)
    return summary, logs
