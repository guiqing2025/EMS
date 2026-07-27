from datetime import datetime as dt, timedelta
import json
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import load_config, save_config
from database import SessionLocal, get_db
from models import SyncLog
from schemas import (
    CustomerOut,
    KittingAlertItem,
    NewOrderItem,
    SrmConfigOut,
    SrmConfigUpdate,
    SyncLogOut,
    SyncNotificationOut,
    SyncResult,
)
from srm_sync import sync_srm_orders, _recover_stale_sync_logs
from sync_scheduler import reload_scheduler
from system_auth import require_admin, require_admin_or_planner, require_system_auth

router = APIRouter(
    prefix="/api/sync",
    tags=["sync"],
    dependencies=[Depends(require_system_auth)],
)


def _mask_config(cfg: dict) -> SrmConfigOut:
    customers = []
    for item in cfg.get("customers", []):
        customers.append(CustomerOut(**{**item, "password": "******"}))
    return SrmConfigOut(
        sync_interval_minutes=cfg["sync_interval_minutes"],
        auto_sync_enabled=cfg["auto_sync_enabled"],
        login_username=cfg.get("login_username") or "admin",
        login_password="******",
        dashboard_password="******",
        customers=customers,
    )


async def _run_sync():
    db = SessionLocal()
    try:
        await sync_srm_orders(db)
    finally:
        db.close()


def _parse_new_orders(log: SyncLog) -> List[NewOrderItem]:
    if not log.new_orders_detail:
        return []
    try:
        rows = json.loads(log.new_orders_detail)
    except json.JSONDecodeError:
        return []
    return [NewOrderItem(**row) for row in rows if isinstance(row, dict)]


def _parse_kitting_alerts(log: SyncLog) -> List[KittingAlertItem]:
    if not log.kitting_alert_detail:
        return []
    try:
        rows = json.loads(log.kitting_alert_detail)
    except json.JSONDecodeError:
        return []
    return [KittingAlertItem(**row) for row in rows if isinstance(row, dict)]


@router.get("/notifications")
def get_notifications(after_log_id: int = 0, db: Session = Depends(get_db)):
    logs = (
        db.query(SyncLog)
        .filter(
            SyncLog.id > after_log_id,
            SyncLog.status.in_(["success", "partial"]),
            or_(SyncLog.new_orders_count > 0, SyncLog.kitting_alert_count > 0),
        )
        .order_by(SyncLog.id.asc())
        .limit(20)
        .all()
    )
    items = [
        SyncNotificationOut(
            sync_log_id=log.id,
            finished_at=log.finished_at,
            new_orders_count=log.new_orders_count or 0,
            orders=_parse_new_orders(log),
            kitting_alert_count=log.kitting_alert_count or 0,
            kitting_alerts=_parse_kitting_alerts(log),
        )
        for log in logs
    ]
    latest_id = db.query(SyncLog.id).order_by(SyncLog.id.desc()).limit(1).scalar() or 0
    return {
        "latest_log_id": latest_id,
        "items": items,
        "total_new_orders": sum(item.new_orders_count for item in items),
        "total_kitting_alerts": sum(item.kitting_alert_count for item in items),
    }


@router.get("/config", response_model=SrmConfigOut)
def get_config():
    return _mask_config(load_config())


@router.put("/config", response_model=SrmConfigOut)
def update_config(payload: SrmConfigUpdate, principal=Depends(require_admin)):
    data = payload.model_dump(exclude_none=True)
    if data.get("login_password") == "******":
        data.pop("login_password", None)
    if data.get("dashboard_password") == "******":
        data.pop("dashboard_password", None)
    if data.get("customers"):
        cleaned = []
        for item in data["customers"]:
            if item.get("password") == "******":
                item = {k: v for k, v in item.items() if k != "password"}
            cleaned.append(item)
        data["customers"] = cleaned
    cfg = save_config(data)
    reload_scheduler()
    return _mask_config(cfg)


@router.get("/customers")
def list_customers():
    cfg = load_config()
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "api_type": c.get("api_type", "v1"),
            "enabled": c.get("enabled", True),
        }
        for c in cfg.get("customers", [])
    ]


@router.post("/run", response_model=SyncResult)
async def run_sync(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal=Depends(require_admin_or_planner),
):
    _recover_stale_sync_logs(db)
    db.commit()

    _recover_cutoff = dt.utcnow() - timedelta(minutes=15)
    running = (
        db.query(SyncLog)
        .filter(SyncLog.status == "running", SyncLog.started_at >= _recover_cutoff)
        .order_by(SyncLog.id.desc())
        .first()
    )
    if running:
        return SyncResult(status="running", message="同步任务正在进行中，请稍候", orders_synced=0)

    log = await sync_srm_orders(db)
    return SyncResult(
        status=log.status,
        message=log.message or "",
        orders_synced=log.orders_synced,
        new_orders_count=log.new_orders_count or 0,
        kitting_alert_count=log.kitting_alert_count or 0,
        sync_log_id=log.id,
        new_orders=_parse_new_orders(log),
        kitting_alerts=_parse_kitting_alerts(log),
    )


@router.get("/logs", response_model=List[SyncLogOut])
def get_logs(limit: int = 20, db: Session = Depends(get_db)):
    return db.query(SyncLog).order_by(SyncLog.id.desc()).limit(limit).all()


@router.get("/status")
def get_sync_status(db: Session = Depends(get_db)):
    cfg = load_config()
    last_log = db.query(SyncLog).order_by(SyncLog.id.desc()).first()
    return {
        "auto_sync_enabled": cfg["auto_sync_enabled"],
        "sync_interval_minutes": cfg.get("sync_interval_minutes"),
        "sync_daily_hour": cfg.get("sync_daily_hour", 9),
        "sync_daily_minute": cfg.get("sync_daily_minute", 0),
        "sync_schedule": f"每天 {int(cfg.get('sync_daily_hour', 9)):02d}:{int(cfg.get('sync_daily_minute', 0)):02d}",
        "customers": [
            {"id": c["id"], "name": c["name"], "enabled": c.get("enabled", True)}
            for c in cfg.get("customers", [])
        ],
        "last_log": SyncLogOut.model_validate(last_log) if last_log else None,
    }
