import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import load_config
from database import SessionLocal
from srm_sync import sync_srm_orders
from warehouse_sync import sync_warehouse_materials

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
SRM_JOB_ID = "srm_sync"
WAREHOUSE_JOB_ID = "warehouse_sync"
AOI_JOB_ID = "aoi_sync"
ICT_JOB_ID = "ict_sync"
ENJIU_ATS_JOB_ID = "enjiu_ats_sync"
TTS_LASER_JOB_ID = "tts_laser_sync"
DEVICE_RETENTION_JOB_ID = "device_data_retention"
WANG123_LEGACY_JOB_ID = "wang123_legacy_sync"
# 恩玖 ATS 相对菲利斯 ICT 错开，避免同秒抢盘/抢库
ENJIU_ATS_OFFSET_SEC = 120


def scheduled_wang123_legacy_sync():
    cfg = load_config()
    wcfg = cfg.get("wang123_legacy") or {}
    if not wcfg.get("auto_sync_enabled", False):
        return
    from wang123_client import Wang123Client
    from wang123_packing_sync import sync_packaged_from_wang123

    db = SessionLocal()
    try:
        client = Wang123Client(
            api_base=wcfg.get("api_base") or "https://zym.wang123.online",
            username=wcfg.get("username") or "blue",
            password=wcfg.get("password") or "blue1",
            token=Wang123Client.load_token(),
        )
        result = sync_packaged_from_wang123(
            db,
            client,
            full=True,
            default_status=wcfg.get("default_scan_status") or "shipped",
        )
        logger.info("旧站包装同步: %s", result.get("message") or result)
    except Exception as exc:
        logger.warning("旧站包装定时同步跳过/失败: %s", exc)
    finally:
        db.close()


async def scheduled_sync():
    cfg = load_config()
    if not cfg.get("auto_sync_enabled", True):
        return
    db = SessionLocal()
    try:
        await sync_srm_orders(db)
    except Exception:
        logger.exception("定时同步失败")
    finally:
        db.close()


def scheduled_warehouse_sync():
    cfg = load_config()
    if not cfg.get("warehouse_auto_sync_enabled", False):
        return
    db = SessionLocal()
    try:
        sync_warehouse_materials(db)
        db.commit()
    except Exception:
        logger.exception("仓库共享盘同步失败")
        db.rollback()
    finally:
        db.close()


def scheduled_aoi_sync():
    cfg = load_config()
    aoi = cfg.get("aoi") or {}
    if not aoi.get("auto_sync_enabled", False):
        return
    db = SessionLocal()
    try:
        from aoi_sync import sync_aoi_from_share
        from laser_service import rematch_aoi_to_laser

        sync_aoi_from_share(db, force_all=False)
        rematch_aoi_to_laser(db)
        db.commit()
    except Exception:
        logger.exception("AOI 定时同步失败")
        db.rollback()
    finally:
        db.close()


def scheduled_ict_sync():
    cfg = load_config()
    ict = cfg.get("ict") or {}
    if not ict.get("auto_sync_enabled", False):
        return
    from ict_sync import mark_ict_sync_ran, should_run_ict_sync

    ok, reason = should_run_ict_sync(ict)
    if not ok:
        logger.info("ICT 定时同步跳过：%s", reason)
        return
    logger.info("ICT 定时同步开始：%s", reason)
    db = SessionLocal()
    try:
        from ict_sync import rematch_ict_to_laser, sync_ict_from_shares

        sync_ict_from_shares(db, force_all=False)
        rematch_ict_to_laser(db)
        db.commit()
        mark_ict_sync_ran()
    except Exception:
        logger.exception("ICT 定时同步失败")
        db.rollback()
    finally:
        db.close()


def scheduled_enjiu_ats_sync():
    """恩玖 ATS：与菲利斯同时间窗，调度错开约 2 分钟。"""
    cfg = load_config()
    ats = cfg.get("enjiu_ats") or {}
    if not ats.get("auto_sync_enabled", False):
        return
    from enjiu_ats_sync import (
        mark_enjiu_ats_sync_ran,
        should_run_enjiu_ats_sync,
        sync_enjiu_ats_from_shares,
    )
    from ict_sync import rematch_ict_to_laser

    ok, reason = should_run_enjiu_ats_sync()
    if not ok:
        logger.info("恩玖 ATS 定时同步跳过：%s", reason)
        return
    logger.info("恩玖 ATS 定时同步开始：%s", reason)
    db = SessionLocal()
    try:
        sync_enjiu_ats_from_shares(db, force_all=False)
        rematch_ict_to_laser(db)
        db.commit()
        mark_enjiu_ats_sync_ran()
    except Exception:
        logger.exception("恩玖 ATS 定时同步失败")
        db.rollback()
    finally:
        db.close()


def scheduled_tts_laser_sync():
    cfg = load_config()
    tts = cfg.get("tts") or {}
    if not tts.get("auto_sync_enabled", False):
        return
    db = SessionLocal()
    try:
        from tts_laser_sync import sync_laser_from_tts

        sync_laser_from_tts(db, rematch=True, created_by="tts-scheduler")
        db.commit()
    except Exception:
        logger.exception("TTS 镭雕同步失败")
        db.rollback()
    finally:
        db.close()


def scheduled_device_data_retention():
    """夜间清理设备冷数据：sync 去重文件 + 板测冷热归档 + ANALYZE。"""
    db = SessionLocal()
    try:
        from device_board_archive import analyze_device_tables, archive_cold_board_results
        from device_data_retention import purge_old_sync_files

        purge_old_sync_files(db)
        archive_cold_board_results(db)
        analyze_device_tables(db)
    except Exception:
        logger.exception("设备数据保留清理失败")
        db.rollback()
    finally:
        db.close()


def _sync_warmup_next_run():
    """启动后延迟首轮 SMB/重同步，避免刚起来就被 ICT/AOI 拖死或锁库。"""
    import os
    from datetime import datetime, timedelta

    sec = int(os.environ.get("EMS_SYNC_WARMUP_SEC", "120") or "120")
    sec = max(0, min(sec, 3600))
    return datetime.now() + timedelta(seconds=sec)


def reload_scheduler() -> None:
    """按当前配置启动、更新或关闭定时同步任务。"""
    import os

    # 开发实例（EMS_DEV_MODE=1）不跑定时同步，避免与生产抢 SMB / 重复扫盘
    if os.environ.get("EMS_DEV_MODE", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
        if scheduler.running:
            for job in list(scheduler.get_jobs()):
                scheduler.remove_job(job.id)
            logger.info("EMS_DEV_MODE：已关闭全部定时同步")
        else:
            logger.info("EMS_DEV_MODE：跳过定时同步调度")
        return

    cfg = load_config()
    warmup_at = _sync_warmup_next_run()
    logger.info("定时同步首轮将不早于 %s 执行（EMS_SYNC_WARMUP_SEC）", warmup_at.strftime("%H:%M:%S"))

    if cfg.get("auto_sync_enabled", True):
        hour = int(cfg.get("sync_daily_hour", 9))
        minute = int(cfg.get("sync_daily_minute", 0))
        scheduler.add_job(
            scheduled_sync,
            CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai"),
            id=SRM_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("SRM 定时同步已重载，每天 %02d:%02d（Asia/Shanghai）", hour, minute)
    elif scheduler.get_job(SRM_JOB_ID):
        scheduler.remove_job(SRM_JOB_ID)
        logger.info("SRM 定时同步已关闭")

    if cfg.get("warehouse_auto_sync_enabled", False):
        wh_interval = cfg.get("warehouse_sync_interval_minutes", 120)
        scheduler.add_job(
            scheduled_warehouse_sync,
            "interval",
            minutes=wh_interval,
            id=WAREHOUSE_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=warmup_at,
        )
        logger.info("仓库共享盘定时同步已重载，间隔 %s 分钟", wh_interval)
    elif scheduler.get_job(WAREHOUSE_JOB_ID):
        scheduler.remove_job(WAREHOUSE_JOB_ID)
        logger.info("仓库共享盘定时同步已关闭")

    aoi = cfg.get("aoi") or {}
    if aoi.get("auto_sync_enabled", False):
        aoi_interval = int(aoi.get("sync_interval_minutes") or 15)
        scheduler.add_job(
            scheduled_aoi_sync,
            "interval",
            minutes=max(5, aoi_interval),
            id=AOI_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=warmup_at,
        )
        logger.info("AOI 定时同步已重载，间隔 %s 分钟", aoi_interval)
    elif scheduler.get_job(AOI_JOB_ID):
        scheduler.remove_job(AOI_JOB_ID)
        logger.info("AOI 定时同步已关闭")

    ict = cfg.get("ict") or {}
    if ict.get("auto_sync_enabled", False):
        ict_interval = max(1, int(ict.get("sync_interval_minutes") or 10))
        scheduler.add_job(
            scheduled_ict_sync,
            "interval",
            minutes=ict_interval,
            id=ICT_JOB_ID,
            replace_existing=True,
            # 上一轮未完成时跳过，避免跟线缩短间隔后任务叠跑
            max_instances=1,
            coalesce=True,
            next_run_time=warmup_at,
        )
        logger.info(
            "ICT 定时同步已重载，间隔 %s 分钟（含时间窗/午休降频）",
            ict_interval,
        )
    elif scheduler.get_job(ICT_JOB_ID):
        scheduler.remove_job(ICT_JOB_ID)
        logger.info("ICT 定时同步已关闭")

    ats = cfg.get("enjiu_ats") or {}
    if ats.get("auto_sync_enabled", False):
        from datetime import timedelta

        ict_interval = max(1, int((cfg.get("ict") or {}).get("sync_interval_minutes") or 10))
        ats_start = warmup_at + timedelta(seconds=ENJIU_ATS_OFFSET_SEC)
        scheduler.add_job(
            scheduled_enjiu_ats_sync,
            "interval",
            minutes=ict_interval,
            id=ENJIU_ATS_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=ats_start,
        )
        logger.info(
            "恩玖 ATS 定时同步已重载，间隔 %s 分钟，相对 ICT 错开 %ss",
            ict_interval,
            ENJIU_ATS_OFFSET_SEC,
        )
    elif scheduler.get_job(ENJIU_ATS_JOB_ID):
        scheduler.remove_job(ENJIU_ATS_JOB_ID)
        logger.info("恩玖 ATS 定时同步已关闭")

    w123 = cfg.get("wang123_legacy") or {}
    if w123.get("auto_sync_enabled", False):
        w_interval = max(15, int(w123.get("sync_interval_minutes") or 30))
        scheduler.add_job(
            scheduled_wang123_legacy_sync,
            "interval",
            minutes=w_interval,
            id=WANG123_LEGACY_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=warmup_at,
        )
        logger.info("旧站包装定时同步已重载，间隔 %s 分钟（需有效登录 token）", w_interval)
    elif scheduler.get_job(WANG123_LEGACY_JOB_ID):
        scheduler.remove_job(WANG123_LEGACY_JOB_ID)
        logger.info("旧站包装定时同步已关闭")

    tts = cfg.get("tts") or {}
    if tts.get("auto_sync_enabled", False):
        tts_interval = int(tts.get("sync_interval_minutes") or 60)
        scheduler.add_job(
            scheduled_tts_laser_sync,
            "interval",
            minutes=max(15, tts_interval),
            id=TTS_LASER_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=warmup_at,
        )
        logger.info("TTS 镭雕定时同步已重载，间隔 %s 分钟", max(15, tts_interval))
    elif scheduler.get_job(TTS_LASER_JOB_ID):
        scheduler.remove_job(TTS_LASER_JOB_ID)
        logger.info("TTS 镭雕定时同步已关闭")

    # 每天 03:20 清理设备 sync 去重冷数据（与业务高峰错开）
    scheduler.add_job(
        scheduled_device_data_retention,
        CronTrigger(hour=3, minute=20, timezone="Asia/Shanghai"),
        id=DEVICE_RETENTION_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("设备数据保留清理已重载，每天 03:20（Asia/Shanghai）")

    if not scheduler.running:
        scheduler.start()


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
