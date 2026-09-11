from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from dashboard_auth import (
    create_token,
    is_dashboard_locked,
    verify_password,
    verify_token,
)
from database import get_db
from models import SrmOrder, SrmReconciliation, SyncLog
from receive_snapshot import build_receive_board
from schemas import (
    DashboardAuthStatus,
    DashboardLogin,
    DashboardStats,
    MonthlyFee,
    ReceiveBoardOut,
    SrmOrderOut,
)
from system_auth import require_dashboard_viewer, require_system_auth

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_system_auth), Depends(require_dashboard_viewer)],
)


def _orders_query(db: Session, customer_id: str = ""):
    q = db.query(SrmOrder).filter(SrmOrder.is_completed.is_(False))
    if customer_id:
        q = q.filter(SrmOrder.customer_id == customer_id)
    return q


def require_dashboard_auth(x_dashboard_token: Optional[str] = Header(None)):
    if not is_dashboard_locked():
        return
    if not verify_token(x_dashboard_token or ""):
        raise HTTPException(status_code=401, detail="需要看板查看密码")


@router.get("/auth-status", response_model=DashboardAuthStatus)
def auth_status(x_dashboard_token: Optional[str] = Header(None)):
    locked = is_dashboard_locked()
    authenticated = not locked or verify_token(x_dashboard_token or "")
    return DashboardAuthStatus(locked=locked, authenticated=authenticated)


@router.post("/login")
def login(payload: DashboardLogin):
    if not is_dashboard_locked():
        return {"token": "", "message": "看板未启用密码"}
    if not verify_password(payload.password):
        raise HTTPException(status_code=401, detail="看板密码错误")
    return {"token": create_token(), "message": "验证成功"}


@router.get("/stats", response_model=DashboardStats, dependencies=[Depends(require_dashboard_auth)])
def get_stats(customer_id: str = "", db: Session = Depends(get_db)):
    q = _orders_query(db, customer_id)
    total = q.count()
    hq = db.query(func.count(func.distinct(SrmOrder.purchase_no))).filter(SrmOrder.is_completed.is_(False))
    if customer_id:
        hq = hq.filter(SrmOrder.customer_id == customer_id)
    headers = hq.scalar() or 0
    incomplete = total
    tq = db.query(func.coalesce(func.sum(SrmOrder.tax_amount), 0.0)).filter(SrmOrder.is_completed.is_(False))
    if customer_id:
        tq = tq.filter(SrmOrder.customer_id == customer_id)
    total_tax = tq.scalar() or 0.0
    recon_count = db.query(SrmReconciliation).count()
    date_start = q.with_entities(func.min(SrmOrder.purchase_date)).scalar()
    date_end = q.with_entities(func.max(SrmOrder.purchase_date)).scalar()
    last_log = db.query(SyncLog).order_by(SyncLog.id.desc()).first()
    last_sync_at = last_log.finished_at or last_log.started_at if last_log else None

    fee_source = "对账明细" if recon_count > 0 else "订单行含税金额"

    return DashboardStats(
        total_orders=total,
        total_order_headers=headers,
        incomplete_orders=incomplete,
        completed_orders=0,
        total_tax_amount=float(total_tax),
        reconciliation_count=recon_count,
        last_sync_at=last_sync_at,
        sync_status=last_log.status if last_log else None,
        srm_live_total=headers,
        date_range_start=date_start,
        date_range_end=date_end,
        sync_note=last_log.message if last_log else None,
        fee_source=fee_source,
    )


@router.get("/monthly-fees", response_model=list[MonthlyFee], dependencies=[Depends(require_dashboard_auth)])
def get_monthly_fees(customer_id: str = "", db: Session = Depends(get_db)):
    recon_count = db.query(SrmReconciliation).count()
    if recon_count > 0 and not customer_id:
        rows = (
            db.query(
                func.substring(SrmReconciliation.record_date, 1, 7).label("month"),
                func.count(SrmReconciliation.id).label("order_count"),
                func.coalesce(func.sum(SrmReconciliation.tax_amount), 0.0).label("tax_amount"),
                func.coalesce(func.sum(SrmReconciliation.no_tax_amount), 0.0).label("no_tax_amount"),
            )
            .filter(SrmReconciliation.record_date.isnot(None))
            .group_by("month")
            .order_by(desc("month"))
            .all()
        )
        source = "对账明细"
    else:
        q = db.query(
            func.substring(SrmOrder.purchase_date, 1, 7).label("month"),
            func.count(SrmOrder.id).label("order_count"),
            func.coalesce(func.sum(SrmOrder.tax_amount), 0.0).label("tax_amount"),
            func.coalesce(func.sum(SrmOrder.no_tax_amount), 0.0).label("no_tax_amount"),
        ).filter(SrmOrder.purchase_date.isnot(None), SrmOrder.is_completed.is_(False))
        if customer_id:
            q = q.filter(SrmOrder.customer_id == customer_id)
        rows = q.group_by("month").order_by(desc("month")).all()
        source = "订单跟踪"

    return [
        MonthlyFee(
            month=row.month,
            order_count=row.order_count,
            tax_amount=float(row.tax_amount),
            no_tax_amount=float(row.no_tax_amount),
            source=source,
        )
        for row in rows
        if row.month
    ]


@router.get("/recent-orders", response_model=list[SrmOrderOut], dependencies=[Depends(require_dashboard_auth)])
def get_recent_orders(
    limit: int = Query(10, ge=1, le=50),
    incomplete_only: bool = True,
    customer_id: str = "",
    db: Session = Depends(get_db),
):
    q = _orders_query(db, customer_id)
    if incomplete_only:
        q = q.filter(SrmOrder.is_completed.is_(False))
    return q.order_by(SrmOrder.purchase_date.desc(), SrmOrder.id.desc()).limit(limit).all()


@router.get("/receive-board", response_model=ReceiveBoardOut)
def get_receive_board(db: Session = Depends(get_db)):
    """客户收货上月 vs 本月收货看板（基于每日收货累计快照差分）。"""
    return build_receive_board(db)
