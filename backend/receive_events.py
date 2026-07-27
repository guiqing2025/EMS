"""从菲利斯 ASN / 恩玖发货单明细拉取带日期的收货事件，供看板月度对比。"""

from __future__ import annotations

import calendar
import io
import logging
from datetime import date, datetime
from typing import Optional

import httpx
import openpyxl
from sqlalchemy.orm import Session

from config import get_enabled_customers
from models import ReceiveQtyEvent
from receive_snapshot import board_history_start, today_shanghai
from srm_client import SrmClient, _normalize_seq, make_line_key
from srm_client_v2 import SrmClientV2

logger = logging.getLogger(__name__)

VOID_STATUS = {"已作废", "作废", "取消", "已取消"}
SOURCE_FEILISI_ASN = "feilisi_asn"
SOURCE_ENJIU_DEPOT = "enjiu_depot"  # 旧口径，同步时清理
SOURCE_ENJIU_DELIVERY = "enjiu_delivery"

ENJIU_RECEIVE_STATUSES = {"已收货", "部分收货", "已完成"}
ENJIU_EXPORT_CUSTOMIZE = (
    "deliveryNo,deliveryDate,status,purchaseNo,purchaseSeq,purchaseLineSeq,"
    "purchaseBatchSeq,itemNo,itemName,deliveryQty,receiptQty"
)
# 恩玖全量导出常贴 120s 超时线；按月拉取 + 单月超时放宽
ENJIU_EXPORT_TIMEOUT = httpx.Timeout(300.0, connect=30.0)


def _upsert_events(db: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    keys = [r["source_key"] for r in rows]
    existing = {
        e.source_key: e
        for e in db.query(ReceiveQtyEvent).filter(ReceiveQtyEvent.source_key.in_(keys)).all()
    }
    now = datetime.utcnow()
    n = 0
    for data in rows:
        row = existing.get(data["source_key"])
        if row:
            for k, v in data.items():
                setattr(row, k, v)
            row.synced_at = now
        else:
            db.add(ReceiveQtyEvent(**data, synced_at=now))
        n += 1
    return n


async def sync_feilisi_asn_events(
    db: Session,
    *,
    date_from: str,
    date_to: str,
    customer: Optional[dict] = None,
) -> int:
    customer = customer or next(
        (c for c in get_enabled_customers() if c["id"] == "feilisi"), None
    )
    if not customer:
        return 0
    client = SrmClient(customer)
    lines = await client.fetch_all_asn_body_lines(
        delivery_date_start=date_from,
        delivery_date_end=date_to,
        order_type="2",
    )

    db.query(ReceiveQtyEvent).filter(
        ReceiveQtyEvent.customer_id == "feilisi",
        ReceiveQtyEvent.source == SOURCE_FEILISI_ASN,
        ReceiveQtyEvent.event_date >= date_from,
        ReceiveQtyEvent.event_date <= date_to,
    ).delete(synchronize_session=False)

    rows: list[dict] = []
    for line in lines:
        status = (line.get("statusName") or "").strip()
        if status in VOID_STATUS or int(line.get("delflg") or 0) == 1:
            continue
        event_date = (line.get("deliveryDate") or "")[:10]
        if not event_date or event_date < date_from or event_date > date_to:
            continue
        qty = float(line.get("receiveQty") or 0)
        if qty <= 0 and status == "已收货":
            qty = float(line.get("deliveryQty") or 0)
        if qty <= 0:
            continue
        asn_no = str(line.get("asnNo") or "").strip()
        asn_seq = str(line.get("asnSeq") if line.get("asnSeq") is not None else "").strip() or "0"
        purchase_no = str(line.get("purchaseNo") or "").strip()
        seq = _normalize_seq(line.get("purchaseSeq"), width=4)
        phase = _normalize_seq(line.get("purchasePhaseSeq"))
        goods_no = (line.get("goodsNo") or "").strip()
        goods_name = (line.get("goodsName") or "").strip()
        source_key = f"feilisi|asn|{asn_no}|{asn_seq}|{purchase_no}|{seq}|{phase}"
        rows.append(
            {
                "customer_id": "feilisi",
                "event_date": event_date,
                "product_goods_no": goods_no or None,
                "product_goods_name": goods_name or None,
                "qty": qty,
                "source": SOURCE_FEILISI_ASN,
                "source_key": source_key,
                "line_key": make_line_key("feilisi", purchase_no, seq, phase) if purchase_no else None,
            }
        )
    n = _upsert_events(db, rows)
    db.commit()
    logger.info("菲利斯 ASN 收货事件 %s~%s 写入 %s 行（源 %s）", date_from, date_to, n, len(lines))
    return n


def _parse_enjiu_delivery_export(content: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    if len(rows) < 3:
        return []
    header = [str(h or "").strip() for h in rows[1]]
    cols = {h: i for i, h in enumerate(header) if h}

    def col(*names: str) -> Optional[int]:
        for name in names:
            if name in cols:
                return cols[name]
        for h, i in cols.items():
            for name in names:
                if name in h:
                    return i
        return None

    i_dno = col("发货单号")
    i_date = col("发货日期")
    i_status = col("发货状态", "状态")
    i_po = col("采购单号")
    i_seq = col("采购项次")
    i_line = col("采购单项次")
    i_batch = col("采购单分批序")
    i_item = col("料件编码", "品号")
    i_name = col("品名")
    i_del = col("发货数量")
    i_recv = col("SRM收货数量", "已收货量", "收货数量")

    out: list[dict] = []
    for r in rows[2:]:
        if not r or (i_dno is not None and r[i_dno] is None):
            continue
        status = str(r[i_status] or "").strip() if i_status is not None else ""
        if status in VOID_STATUS or status == "已取消":
            continue
        if status not in ENJIU_RECEIVE_STATUSES and "收货" not in status:
            continue
        event_date = str(r[i_date] or "")[:10] if i_date is not None else ""
        if not event_date:
            continue
        try:
            recv_qty = float(r[i_recv] or 0) if i_recv is not None else 0.0
        except (TypeError, ValueError):
            recv_qty = 0.0
        try:
            del_qty = float(r[i_del] or 0) if i_del is not None else 0.0
        except (TypeError, ValueError):
            del_qty = 0.0
        qty = recv_qty if recv_qty > 0 else del_qty
        if qty <= 0:
            continue
        delivery_no = str(r[i_dno] or "").strip() if i_dno is not None else ""
        purchase_no = str(r[i_po] or "").strip() if i_po is not None else ""
        seq = str(r[i_seq] if i_seq is not None and r[i_seq] is not None else "0")
        line_seq = r[i_line] if i_line is not None else None
        batch_seq = r[i_batch] if i_batch is not None else None
        if line_seq is not None and batch_seq is not None:
            phase = f"{line_seq}-{batch_seq}"
        else:
            phase = "0"
        item_no = str(r[i_item] or "").strip() if i_item is not None else ""
        item_name = str(r[i_name] or "").strip() if i_name is not None else ""
        source_key = f"enjiu|dn|{delivery_no}|{purchase_no}|{seq}|{phase}|{item_no}"
        out.append(
            {
                "customer_id": "enjiu",
                "event_date": event_date,
                "product_goods_no": item_no or None,
                "product_goods_name": item_name or None,
                "qty": qty,
                "source": SOURCE_ENJIU_DELIVERY,
                "source_key": source_key,
                "line_key": make_line_key("enjiu", purchase_no, seq, phase) if purchase_no else None,
            }
        )
    return out


def _month_windows(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """把闭区间拆成自然月窗口，降低恩玖单次导出体积。"""
    start = date.fromisoformat(date_from[:10])
    end = date.fromisoformat(date_to[:10])
    if start > end:
        return []
    windows: list[tuple[str, str]] = []
    y, m = start.year, start.month
    while True:
        month_start = date(y, m, 1)
        month_end = date(y, m, calendar.monthrange(y, m)[1])
        w0 = max(start, month_start)
        w1 = min(end, month_end)
        if w0 <= w1:
            windows.append((w0.isoformat(), w1.isoformat()))
        if (y, m) >= (end.year, end.month):
            break
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return windows


async def _export_enjiu_delivery_chunk(
    http: httpx.AsyncClient,
    client: SrmClientV2,
    *,
    date_from: str,
    date_to: str,
) -> bytes:
    params = {
        "token": client._token or "",
        "selItems": "",
        "deliveryNo": "",
        "purchaseNo": "",
        "deliveryDateStart": date_from,
        "deliveryDateEnd": date_to,
        "fuzzyQuery": "",
        "itemFeatureNo": "",
        "itemSpec": "",
        "itemName": "",
        "itemNo": "",
        "orderBy": "[]",
        "site": "",
        "purchaseType": "",
        "customizeParam": ENJIU_EXPORT_CUSTOMIZE,
    }
    resp = await http.get(
        client._api_url("api/srm/delivery/export"),
        params=params,
        timeout=ENJIU_EXPORT_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content


async def sync_enjiu_delivery_events(
    db: Session,
    *,
    date_from: str,
    date_to: str,
    customer: Optional[dict] = None,
) -> int:
    """恩玖：导出「发货单明细」按发货日 + SRM收货数量（已收货/部分收货）。

    按自然月分批拉取，避免全年一次导出经常超过 120s 读超时。
    """
    customer = customer or next(
        (c for c in get_enabled_customers() if c["id"] == "enjiu"), None
    )
    if not customer:
        return 0
    windows = _month_windows(date_from, date_to)
    if not windows:
        return 0

    client = SrmClientV2(customer)
    parsed_all: list[dict] = []
    try:
        await client.login()
        http = await client._get_client()
        for w0, w1 in windows:
            try:
                content = await _export_enjiu_delivery_chunk(
                    http, client, date_from=w0, date_to=w1
                )
            except httpx.TimeoutException as exc:
                raise TimeoutError(
                    f"恩玖发货单导出超时 {w0}~{w1}（单月上限 {ENJIU_EXPORT_TIMEOUT.read}s）"
                ) from exc
            chunk = _parse_enjiu_delivery_export(content)
            logger.info(
                "恩玖发货单导出分片 %s~%s bytes=%s rows=%s",
                w0,
                w1,
                len(content),
                len(chunk),
            )
            parsed_all.extend(chunk)
    finally:
        await client.close()

    # 同 source_key 去重（跨月边界偶发重叠时以后写为准）
    by_key: dict[str, dict] = {}
    for row in parsed_all:
        by_key[row["source_key"]] = row
    parsed = list(by_key.values())

    db.query(ReceiveQtyEvent).filter(
        ReceiveQtyEvent.customer_id == "enjiu",
        ReceiveQtyEvent.source.in_([SOURCE_ENJIU_DEPOT, SOURCE_ENJIU_DELIVERY]),
        ReceiveQtyEvent.event_date >= date_from,
        ReceiveQtyEvent.event_date <= date_to,
    ).delete(synchronize_session=False)

    n = _upsert_events(db, parsed)
    db.commit()
    logger.info(
        "恩玖发货单收货事件 %s~%s 写入 %s 行（分片 %s）",
        date_from,
        date_to,
        n,
        len(windows),
    )
    return n


async def sync_receive_events(
    db: Session,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """拉取看板所需收货事件（默认 history_start ~ 今天）。

    菲利斯 / 恩玖彼此独立：一侧失败不拖垮另一侧已写入的数据。
    """
    today = today_shanghai()
    start = date_from or board_history_start(today).isoformat()
    end = date_to or today.isoformat()
    feilisi_n = 0
    enjiu_n = 0
    errors: list[str] = []

    try:
        feilisi_n = await sync_feilisi_asn_events(db, date_from=start, date_to=end)
    except Exception as exc:
        logger.exception("菲利斯收货事件拉取失败")
        errors.append(f"菲利斯: {exc or type(exc).__name__}")

    try:
        enjiu_n = await sync_enjiu_delivery_events(db, date_from=start, date_to=end)
    except Exception as exc:
        logger.exception("恩玖收货事件拉取失败")
        errors.append(f"恩玖: {exc or type(exc).__name__}")

    result = {
        "date_from": start,
        "date_to": end,
        "feilisi": feilisi_n,
        "enjiu": enjiu_n,
        "total": feilisi_n + enjiu_n,
        "errors": errors,
    }
    if errors and feilisi_n == 0 and enjiu_n == 0:
        raise RuntimeError("；".join(errors))
    return result
