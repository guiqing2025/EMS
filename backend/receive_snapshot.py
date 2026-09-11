"""看板收货量日快照与月度汇总。"""

from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import load_config
from models import ReceiveQtyEvent, ReceiveQtySnapshot, SrmOrder, SyncLog

logger = logging.getLogger(__name__)

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
# 景立创部署：不预置外部客户名；有真实客户数据后再由配置/业务接入
BOARD_CUSTOMERS: tuple[tuple[str, str], ...] = ()
BOARD_CUSTOMER_IDS = [cid for cid, _ in BOARD_CUSTOMERS]
# 订单/事件里可能出现的别名 → 看板规范客户 id（保留映射，当前看板客户为空时不生效）
BOARD_CUSTOMER_ALIASES = {
    "manual_daeae675": "yilanke",
    "wh_yilanke": "yilanke",
    "a067": "yonglian",
    "a116": "enjiu",
    "a120": "yilanke",
}
# 无 ASN/发货单日粒度时，用订单累计收货按采购日挂月
ORDER_BALANCE_BOARD_IDS = frozenset({"yonglian", "yilanke"})


def canonical_board_customer_id(customer_id: str) -> str:
    cid = (customer_id or "").strip()
    return BOARD_CUSTOMER_ALIASES.get(cid, cid)


def board_source_customer_ids() -> list[str]:
    """查询用：规范 id + 别名。"""
    ids = list(BOARD_CUSTOMER_IDS)
    for alias, canon in BOARD_CUSTOMER_ALIASES.items():
        if canon in BOARD_CUSTOMER_IDS:
            ids.append(alias)
    return list(dict.fromkeys(ids))


def today_shanghai() -> date:
    return datetime.now(TZ_SHANGHAI).date()


def board_history_start(today: date | None = None) -> date:
    """看板/回填起点：优先 srm_config.receive_board.history_start，否则上月 1 日。"""
    day = today or today_shanghai()
    try:
        raw = ((load_config().get("receive_board") or {}).get("history_start") or "").strip()
        if raw:
            if len(raw) == 7 and raw[4] == "-":
                return _month_start(raw)
            return date.fromisoformat(raw[:10])
    except Exception:
        logger.exception("读取 receive_board.history_start 失败，回退上月 1 日")
    return _month_start(_prev_month(day.strftime("%Y-%m")))


def snapshot_receive_qty(db: Session, snap_day: date | None = None) -> int:
    """对看板客户全部在库订单行写入/覆盖当日收货累计快照。返回写入行数。"""
    day = snap_day or today_shanghai()
    snap_date = day.isoformat()
    source_ids = board_source_customer_ids()

    orders = (
        db.query(SrmOrder)
        .filter(SrmOrder.customer_id.in_(source_ids))
        .all()
    )
    if not orders:
        return 0

    line_keys = [o.line_key for o in orders]
    existing = {
        row.line_key: row
        for row in db.query(ReceiveQtySnapshot)
        .filter(
            ReceiveQtySnapshot.snap_date == snap_date,
            ReceiveQtySnapshot.line_key.in_(line_keys),
        )
        .all()
    }

    written = 0
    for order in orders:
        qty = float(order.receive_qty or 0)
        canon = canonical_board_customer_id(order.customer_id)
        row = existing.get(order.line_key)
        if row:
            row.customer_id = canon
            row.product_goods_no = order.product_goods_no
            row.receive_qty = qty
        else:
            db.add(
                ReceiveQtySnapshot(
                    snap_date=snap_date,
                    customer_id=canon,
                    line_key=order.line_key,
                    product_goods_no=order.product_goods_no,
                    receive_qty=qty,
                )
            )
        written += 1

    db.commit()
    logger.info("收货快照 %s 写入 %s 行", snap_date, written)
    return written


def _month_start(ym: str) -> date:
    y, m = ym.split("-")
    return date(int(y), int(m), 1)


def _month_end(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y, m, calendar.monthrange(y, m)[1])


def _prev_month(ym: str) -> str:
    start = _month_start(ym)
    prev = start.replace(day=1) - timedelta(days=1)
    return prev.strftime("%Y-%m")


def _month_range(start_ym: str, end_ym: str) -> list[str]:
    """含起止的 YYYY-MM 列表。"""
    months: list[str] = []
    y, m = int(start_ym[:4]), int(start_ym[5:7])
    ey, em = int(end_ym[:4]), int(end_ym[5:7])
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _unit_price_map(db: Session) -> dict[str, float]:
    """含税单价优先读持久化缓存（含已结案/已删除订单），再合并当前订单。"""
    from order_price_service import unit_price_map

    return unit_price_map(db, board_source_customer_ids())


def _order_event_date(order: SrmOrder, history_start: date, today: date) -> date | None:
    """返回订单挂月日期；早于 history_start 的返回 None（不挤进首月）。"""
    raw = order.purchase_date or order.doc_date
    if isinstance(raw, datetime):
        d = raw.date()
    elif isinstance(raw, date):
        d = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            d = date.fromisoformat(raw.strip()[:10].replace("/", "-"))
        except ValueError:
            d = today
    else:
        d = today
    if d < history_start:
        return None
    if d > today:
        return today
    return d


def _parse_order_day(raw: Any) -> date | None:
    """解析采购日/单据日；无法解析则返回 None。"""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and raw.strip():
        text = raw.strip().replace("/", "-")[:10]
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    return None


def _this_month_order_intake(
    db: Session,
    *,
    this_start: date,
    this_end: date,
) -> dict[str, dict[str, float]]:
    """按采购日汇总当月接单数量/含税金额（看板客户）。"""
    out: dict[str, dict[str, float]] = {
        cid: {"qty": 0.0, "amount": 0.0} for cid, _ in BOARD_CUSTOMERS
    }
    source_ids = board_source_customer_ids()
    ym = this_start.strftime("%Y-%m")
    ym_slash = this_start.strftime("%Y/%m")
    # 先用前缀收窄，再精确落到当月区间
    candidates = (
        db.query(
            SrmOrder.customer_id,
            SrmOrder.purchase_date,
            SrmOrder.doc_date,
            SrmOrder.batch_pur_qty,
            SrmOrder.tax_amount,
        )
        .filter(SrmOrder.customer_id.in_(source_ids))
        .filter(
            or_(
                (
                    (SrmOrder.purchase_date.isnot(None))
                    & (SrmOrder.purchase_date != "")
                    & or_(
                        SrmOrder.purchase_date.like(f"{ym}%"),
                        SrmOrder.purchase_date.like(f"{ym_slash}%"),
                    )
                ),
                (
                    (SrmOrder.doc_date.isnot(None))
                    & (SrmOrder.doc_date != "")
                    & or_(
                        SrmOrder.doc_date.like(f"{ym}%"),
                        SrmOrder.doc_date.like(f"{ym_slash}%"),
                    )
                ),
            )
        )
        .all()
    )
    for customer_id, purchase_date, doc_date, qty, tax_amount in candidates:
        cid = canonical_board_customer_id(customer_id)
        if cid not in out:
            continue
        day = _parse_order_day(purchase_date) or _parse_order_day(doc_date)
        if day is None or day < this_start or day > this_end:
            continue
        out[cid]["qty"] += float(qty or 0)
        out[cid]["amount"] += float(tax_amount or 0)
    return out


def _fill_board_from_order_balances(
    db: Session,
    *,
    months: list[str],
    monthly_acc: dict[str, dict[str, dict[str, float]]],
    totals: dict[str, dict[str, dict[str, float]]],
    name_hint: dict[tuple[str, str], str],
    unit_prices: dict[str, float],
    history_start: date,
    today: date,
    last_month: str,
    this_month: str,
    only_ids: set[str] | None = None,
) -> None:
    """永联/亿兰科等无日收货流水时：用订单累计收货按采购日挂到对应月份。"""
    target = set(only_ids) if only_ids is not None else set(ORDER_BALANCE_BOARD_IDS)
    target &= set(ORDER_BALANCE_BOARD_IDS)
    if not target:
        return
    source_ids = [
        cid
        for cid in board_source_customer_ids()
        if canonical_board_customer_id(cid) in target
    ]
    if not source_ids:
        return
    orders = (
        db.query(SrmOrder)
        .filter(
            SrmOrder.customer_id.in_(source_ids),
            SrmOrder.receive_qty > 0,
        )
        .all()
    )
    for order in orders:
        canon = canonical_board_customer_id(order.customer_id)
        if canon not in target:
            continue
        qty = float(order.receive_qty or 0)
        if qty <= 0:
            continue
        event_day = _order_event_date(order, history_start, today)
        if event_day is None:
            continue
        ym = event_day.strftime("%Y-%m")
        if ym not in monthly_acc.get(canon, {}):
            continue
        amount = qty * unit_prices.get((order.line_key or "").strip(), 0.0)
        if amount <= 0 and order.tax_amount and order.batch_pur_qty:
            try:
                amount = qty * (float(order.tax_amount) / float(order.batch_pur_qty))
            except (TypeError, ValueError, ZeroDivisionError):
                amount = 0.0
        monthly_acc[canon][ym]["qty"] += qty
        monthly_acc[canon][ym]["amount"] += amount
        model_code = (order.product_goods_no or "").strip() or "(无料号)"
        bucket = totals[canon][model_code]
        if ym == last_month:
            bucket["last_month_qty"] += qty
            bucket["last_month_amount"] += amount
        if ym == this_month:
            bucket["this_month_qty"] += qty
            bucket["this_month_amount"] += amount
        if order.product_goods_name and model_code != "(无料号)":
            name_hint[(canon, model_code)] = str(order.product_goods_name).strip()


def _model_names(db: Session, customer_id: str, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    from_events = (
        db.query(ReceiveQtyEvent.product_goods_no, ReceiveQtyEvent.product_goods_name)
        .filter(
            ReceiveQtyEvent.customer_id == customer_id,
            ReceiveQtyEvent.product_goods_no.in_(list(codes)),
        )
        .all()
    )
    out: dict[str, str] = {}
    for code, name in from_events:
        if not code or code in out:
            continue
        if name:
            out[code] = str(name).strip()
    missing = codes - set(out.keys())
    if missing:
        rows = (
            db.query(SrmOrder.product_goods_no, SrmOrder.product_goods_name)
            .filter(
                SrmOrder.customer_id == customer_id,
                SrmOrder.product_goods_no.in_(list(missing)),
            )
            .all()
        )
        for code, name in rows:
            if not code or code in out:
                continue
            out[code] = (name or "").strip()
    return out


def build_ship_feed(db: Session) -> dict[str, Any]:
    """今日（或最近有数据日）出货增量滚动：按客户分机型汇总，同步后刷新。"""
    today = today_shanghai()
    today_s = today.isoformat()
    lookback_start = (today - timedelta(days=7)).isoformat()

    last_log = (
        db.query(SyncLog)
        .filter(SyncLog.status.in_(("success", "partial")))
        .order_by(SyncLog.id.desc())
        .first()
    )
    last_synced_at = None
    if last_log and last_log.finished_at:
        last_synced_at = last_log.finished_at.isoformat()

    # 优先今天；若今天无事件则取近 7 天内最近一天
    source_ids = board_source_customer_ids()
    dates = [
        d
        for (d,) in (
            db.query(ReceiveQtyEvent.event_date)
            .filter(
                ReceiveQtyEvent.customer_id.in_(source_ids),
                ReceiveQtyEvent.event_date >= lookback_start,
                ReceiveQtyEvent.event_date <= today_s,
                ReceiveQtyEvent.qty > 0,
            )
            .distinct()
            .all()
        )
    ]
    feed_date = today_s
    if today_s not in dates and dates:
        feed_date = max(dates)
    elif today_s not in dates:
        feed_date = today_s

    events = (
        db.query(ReceiveQtyEvent)
        .filter(
            ReceiveQtyEvent.customer_id.in_(source_ids),
            ReceiveQtyEvent.event_date == feed_date,
            ReceiveQtyEvent.qty > 0,
        )
        .all()
    )

    buckets: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for ev in events:
        cid = canonical_board_customer_id(ev.customer_id)
        if cid not in BOARD_CUSTOMER_IDS:
            continue
        code = (ev.product_goods_no or "").strip() or "(无料号)"
        slot = buckets[cid].get(code)
        if not slot:
            buckets[cid][code] = {
                "model_code": code,
                "model_name": (ev.product_goods_name or "").strip(),
                "qty": float(ev.qty or 0),
            }
        else:
            slot["qty"] += float(ev.qty or 0)
            if not slot["model_name"] and ev.product_goods_name:
                slot["model_name"] = ev.product_goods_name.strip()

    groups = []
    for customer_id, customer_name in BOARD_CUSTOMERS:
        names = _model_names(db, customer_id, set(buckets.get(customer_id, {}).keys()) - {"(无料号)"})
        items = []
        for code, row in buckets.get(customer_id, {}).items():
            items.append(
                {
                    "model_code": code,
                    "model_name": row["model_name"] or names.get(code, ""),
                    "qty": round(row["qty"], 2),
                }
            )
        items.sort(key=lambda x: (-x["qty"], x["model_code"]))
        groups.append(
            {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "items": items,
                "total_qty": round(sum(i["qty"] for i in items), 2),
            }
        )

    return {
        "feed_date": feed_date,
        "is_today": feed_date == today_s,
        "last_synced_at": last_synced_at,
        "groups": groups,
    }


def build_receive_board(db: Session) -> dict[str, Any]:
    """看板优先汇总 receive_qty_events（上月/本月 + 自 history_start 的月序列）；无事件时回退快照差分。"""
    today = today_shanghai()
    this_month = today.strftime("%Y-%m")
    last_month = _prev_month(this_month)
    as_of = today.isoformat()
    history_start = board_history_start(today)
    history_start_s = history_start.isoformat()
    history_start_ym = history_start.strftime("%Y-%m")

    last_start_s = _month_start(last_month).isoformat()
    last_end_s = _month_end(last_month).isoformat()
    this_start_s = _month_start(this_month).isoformat()
    this_end_s = min(_month_end(this_month), today).isoformat()

    # 全年 X 轴固定铺到当年 12 月，未到月份保持 0，避免随月份推进轴距跳动
    chart_end_ym = f"{max(history_start.year, today.year)}-12"
    months = _month_range(history_start_ym, chart_end_ym)
    monthly_acc: dict[str, dict[str, dict[str, float]]] = {
        cid: {ym: {"qty": 0.0, "amount": 0.0} for ym in months} for cid, _ in BOARD_CUSTOMERS
    }
    source_ids = board_source_customer_ids()

    events = (
        db.query(ReceiveQtyEvent)
        .filter(
            ReceiveQtyEvent.customer_id.in_(source_ids),
            ReceiveQtyEvent.event_date >= history_start_s,
            ReceiveQtyEvent.event_date <= this_end_s,
            ReceiveQtyEvent.qty > 0,
        )
        .all()
    )

    unit_prices = _unit_price_map(db)
    empty_bucket = lambda: {
        "last_month_qty": 0.0,
        "this_month_qty": 0.0,
        "last_month_amount": 0.0,
        "this_month_amount": 0.0,
    }
    totals: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(empty_bucket)
    )
    name_hint: dict[tuple[str, str], str] = {}

    if events:
        for ev in events:
            cid = canonical_board_customer_id(ev.customer_id)
            if cid not in monthly_acc:
                continue
            model_code = (ev.product_goods_no or "").strip() or "(无料号)"
            qty = float(ev.qty or 0)
            amount = qty * unit_prices.get((ev.line_key or "").strip(), 0.0)
            bucket = totals[cid][model_code]
            if last_start_s <= ev.event_date <= last_end_s:
                bucket["last_month_qty"] += qty
                bucket["last_month_amount"] += amount
            if this_start_s <= ev.event_date <= this_end_s:
                bucket["this_month_qty"] += qty
                bucket["this_month_amount"] += amount
            if ev.product_goods_name and model_code != "(无料号)":
                name_hint[(cid, model_code)] = ev.product_goods_name.strip()
            ym = (ev.event_date or "")[:7]
            if ym in monthly_acc[cid]:
                monthly_acc[cid][ym]["qty"] += qty
                monthly_acc[cid][ym]["amount"] += amount
        note = (
            f"底层：按客户收货事件汇总。"
            f"金额=出货数量×含税单价。当月接单=采购日落在本月的订单含税金额。"
            f"月度自 {history_start_ym} 起至 {chart_end_ym}。"
        )
    else:
        # 回退：快照差分（仅上月/本月 KPI；月序列保持 0）
        query_from = (date.fromisoformat(last_start_s) - timedelta(days=1)).isoformat()
        snaps = (
            db.query(ReceiveQtySnapshot)
            .filter(
                ReceiveQtySnapshot.customer_id.in_(source_ids),
                ReceiveQtySnapshot.snap_date >= query_from,
                ReceiveQtySnapshot.snap_date <= this_end_s,
            )
            .all()
        )
        qty_by_key_date: dict[tuple[str, str], float] = {}
        by_date: dict[str, list[ReceiveQtySnapshot]] = defaultdict(list)
        for s in snaps:
            qty_by_key_date[(s.line_key, s.snap_date)] = float(s.receive_qty or 0)
            by_date[s.snap_date].append(s)
        for snap_date in sorted(by_date.keys()):
            if snap_date < last_start_s or snap_date > this_end_s:
                continue
            prev_date = (date.fromisoformat(snap_date) - timedelta(days=1)).isoformat()
            in_last = last_start_s <= snap_date <= last_end_s
            in_this = this_start_s <= snap_date <= this_end_s
            for s in by_date[snap_date]:
                today_qty = float(s.receive_qty or 0)
                prev_qty = qty_by_key_date.get((s.line_key, prev_date))
                delta = max(today_qty - prev_qty, 0.0) if prev_qty is not None else 0.0
                if delta <= 0:
                    continue
                cid = canonical_board_customer_id(s.customer_id)
                if cid not in monthly_acc:
                    continue
                model_code = (s.product_goods_no or "").strip() or "(无料号)"
                amount = delta * unit_prices.get((s.line_key or "").strip(), 0.0)
                bucket = totals[cid][model_code]
                if in_last:
                    bucket["last_month_qty"] += delta
                    bucket["last_month_amount"] += amount
                if in_this:
                    bucket["this_month_qty"] += delta
                    bucket["this_month_amount"] += amount
        note = (
            "暂无收货事件底层，已回退日快照差分；金额按订单含税单价估算。"
            "请先同步拉取 ASN/订单收货后再看全年曲线。"
        )

    # 永联/亿兰科：若该客户事件月序列全 0，用订单累计收货按采购日补月度
    need_order_fill = {
        cid
        for cid, _name in BOARD_CUSTOMERS
        if cid in ORDER_BALANCE_BOARD_IDS
        and not any(monthly_acc[cid][ym]["qty"] > 0 for ym in months)
    }
    if need_order_fill:
        _fill_board_from_order_balances(
            db,
            months=months,
            monthly_acc=monthly_acc,
            totals=totals,
            name_hint=name_hint,
            unit_prices=unit_prices,
            history_start=history_start,
            today=today,
            last_month=last_month,
            this_month=this_month,
            only_ids=need_order_fill,
        )
        if "已回退日快照" not in note:
            note = (
                f"底层：按客户收货事件汇总。"
                f"金额=出货数量×含税单价。月度自 {history_start_ym} 起至 {chart_end_ym}。"
            )

    customers_out = []
    order_intake = _this_month_order_intake(
        db,
        this_start=_month_start(this_month),
        this_end=min(_month_end(this_month), today),
    )
    for customer_id, customer_name in BOARD_CUSTOMERS:
        model_map = totals.get(customer_id, {})
        names = _model_names(db, customer_id, set(model_map.keys()) - {"(无料号)"})
        for code, nm in list(names.items()):
            if not nm and (customer_id, code) in name_hint:
                names[code] = name_hint[(customer_id, code)]
        models = []
        for model_code, qtys in model_map.items():
            models.append(
                {
                    "model_code": model_code,
                    "model_name": (
                        ""
                        if model_code == "(无料号)"
                        else (names.get(model_code) or name_hint.get((customer_id, model_code), ""))
                    ),
                    "last_month_qty": round(qtys["last_month_qty"], 2),
                    "this_month_qty": round(qtys["this_month_qty"], 2),
                    "last_month_amount": round(qtys["last_month_amount"], 2),
                    "this_month_amount": round(qtys["this_month_amount"], 2),
                }
            )
        models.sort(key=lambda m: (-m["this_month_qty"], -m["last_month_qty"], m["model_code"]))
        booked = order_intake.get(customer_id) or {"qty": 0.0, "amount": 0.0}
        customers_out.append(
            {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "last_month_total": round(sum(m["last_month_qty"] for m in models), 2),
                "this_month_total": round(sum(m["this_month_qty"] for m in models), 2),
                "last_month_amount": round(sum(m["last_month_amount"] for m in models), 2),
                "this_month_amount": round(sum(m["this_month_amount"] for m in models), 2),
                "this_month_order_qty": round(float(booked["qty"]), 2),
                "this_month_order_amount": round(float(booked["amount"]), 2),
                "models": models,
            }
        )

    monthly_customers = []
    for customer_id, customer_name in BOARD_CUSTOMERS:
        series = []
        for ym in months:
            cell = monthly_acc[customer_id][ym]
            series.append(
                {
                    "month": ym,
                    "qty": round(cell["qty"], 2),
                    "amount": round(cell["amount"], 2),
                }
            )
        monthly_customers.append(
            {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "series": series,
            }
        )

    return {
        "as_of": as_of,
        "this_month": this_month,
        "last_month": last_month,
        "note": note,
        "customers": customers_out,
        "feed": build_ship_feed(db),
        "monthly": {
            "history_start": history_start_s,
            "months": months,
            "customers": monthly_customers,
        },
    }
