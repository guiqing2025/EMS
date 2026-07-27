"""板测结果冷热分离：热表保留近 N 天，更早迁入 *_archive。

工序扫码量小且卡控依赖「是否已扫」，暂不归档。
列表计数 / 板码抽屉 / 卡控查条码时：热表优先，必要时合并归档。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_BOARD_HOT_DAYS = 60
BATCH_SIZE = 3000

ICT_HOT = "ict_board_results"
ICT_ARCHIVE = "ict_board_results_archive"
AOI_HOT = "aoi_board_results"
AOI_ARCHIVE = "aoi_board_results_archive"

# 与热表同结构的列（归档表另加 archived_at）
ICT_COLS = (
    "id, barcode, model_mid, model_ver, laser_date, seq, model_code, board_name, "
    "result, machine_id, ict_id, tested_at, source_file, source_host, "
    "purchase_no, customer_id, laser_batch_id, synced_at"
)
AOI_COLS = (
    "id, barcode, model_mid, model_ver, laser_date, seq, model_code, product_name, "
    "side, result, machine, line_name, tested_at, source_file, "
    "purchase_no, customer_id, laser_batch_id, synced_at"
)


def board_hot_days() -> int:
    raw = (os.environ.get("EMS_BOARD_HOT_DAYS") or "").strip()
    if raw.isdigit():
        return max(30, min(int(raw), 730))
    return DEFAULT_BOARD_HOT_DAYS


def ensure_board_archive_tables(db: Session) -> None:
    """幂等创建归档表与索引（亦由 migrate_postgres 创建）。"""
    statements = [
        f"CREATE TABLE IF NOT EXISTS {ICT_ARCHIVE} AS TABLE {ICT_HOT} WITH NO DATA",
        f"CREATE TABLE IF NOT EXISTS {AOI_ARCHIVE} AS TABLE {AOI_HOT} WITH NO DATA",
        f"ALTER TABLE {ICT_ARCHIVE} ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP",
        f"ALTER TABLE {AOI_ARCHIVE} ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP",
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{ICT_ARCHIVE}_barcode ON {ICT_ARCHIVE} (barcode)",
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{AOI_ARCHIVE}_barcode ON {AOI_ARCHIVE} (barcode)",
        f"CREATE INDEX IF NOT EXISTS ix_{ICT_ARCHIVE}_purchase ON {ICT_ARCHIVE} (purchase_no)",
        f"CREATE INDEX IF NOT EXISTS ix_{AOI_ARCHIVE}_purchase ON {AOI_ARCHIVE} (purchase_no)",
        f"CREATE INDEX IF NOT EXISTS ix_{ICT_ARCHIVE}_tested ON {ICT_ARCHIVE} (tested_at)",
        f"CREATE INDEX IF NOT EXISTS ix_{AOI_ARCHIVE}_tested ON {AOI_ARCHIVE} (tested_at)",
        f"CREATE INDEX IF NOT EXISTS ix_{ICT_ARCHIVE}_purchase_tested ON {ICT_ARCHIVE} (purchase_no, tested_at DESC NULLS LAST)",
        f"CREATE INDEX IF NOT EXISTS ix_{AOI_ARCHIVE}_purchase_tested ON {AOI_ARCHIVE} (purchase_no, tested_at DESC NULLS LAST)",
    ]
    for sql in statements:
        db.execute(text(sql))
    db.commit()


def _archive_table(
    db: Session,
    *,
    hot: str,
    archive: str,
    cols: str,
    cutoff: datetime,
) -> int:
    total = 0
    while True:
        # 先插入归档（冲突则跳过），再删热表，避免唯一约束打架
        result = db.execute(
            text(
                f"""
                WITH pick AS (
                    SELECT id FROM {hot}
                    WHERE coalesce(tested_at, synced_at) < :cutoff
                    ORDER BY id
                    LIMIT :lim
                ),
                moved AS (
                    INSERT INTO {archive} ({cols}, archived_at)
                    SELECT {cols}, now()
                    FROM {hot} h
                    WHERE h.id IN (SELECT id FROM pick)
                    ON CONFLICT (barcode) DO NOTHING
                    RETURNING id
                )
                DELETE FROM {hot} h
                WHERE h.id IN (SELECT id FROM pick)
                RETURNING h.id
                """
            ),
            {"cutoff": cutoff, "lim": BATCH_SIZE},
        )
        n = len(result.fetchall())
        db.commit()
        total += n
        if n < BATCH_SIZE:
            break
    return total


def archive_cold_board_results(db: Session, days: Optional[int] = None) -> dict[str, Any]:
    """将超出热窗口的 ICT/AOI 板测迁入归档表。"""
    ensure_board_archive_tables(db)
    hot_days = board_hot_days() if days is None else max(30, int(days))
    cutoff = datetime.utcnow() - timedelta(days=hot_days)
    out: dict[str, Any] = {
        "hot_days": hot_days,
        "cutoff": cutoff.isoformat(sep=" ", timespec="seconds"),
        "ict_archived": 0,
        "aoi_archived": 0,
    }
    try:
        out["ict_archived"] = _archive_table(
            db, hot=ICT_HOT, archive=ICT_ARCHIVE, cols=ICT_COLS, cutoff=cutoff
        )
        out["aoi_archived"] = _archive_table(
            db, hot=AOI_HOT, archive=AOI_ARCHIVE, cols=AOI_COLS, cutoff=cutoff
        )
        logger.info(
            "板测冷热归档完成：热窗口 %s 天，截止 %s，ict=%s aoi=%s",
            hot_days,
            out["cutoff"],
            out["ict_archived"],
            out["aoi_archived"],
        )
    except Exception:
        logger.exception("板测冷热归档失败")
        db.rollback()
        raise
    return out


def analyze_device_tables(db: Session) -> None:
    """更新规划器统计，避免大表清理/归档后仍按旧基数规划。"""
    tables = [
        ICT_HOT,
        ICT_ARCHIVE,
        AOI_HOT,
        AOI_ARCHIVE,
        "ict_sync_files",
        "aoi_sync_files",
        "process_scan_records",
        "srm_orders",
    ]
    for t in tables:
        try:
            # ANALYZE 不能在事务块里用 ORM 事务语义干扰；autocommit 风格
            db.execute(text(f"ANALYZE {t}"))
            db.commit()
        except Exception:
            db.rollback()
            logger.debug("ANALYZE %s 跳过", t, exc_info=True)


def counts_by_purchase_nos(
    db: Session,
    purchase_nos: list[str],
    *,
    kind: str,
) -> dict[str, int]:
    """按采购单合计（热表 + 归档）。同 PO 多机型时勿用于订单行展示。"""
    out: dict[str, int] = {}
    if not purchase_nos:
        return out
    hot = ICT_HOT if kind == "ict" else AOI_HOT
    archive = ICT_ARCHIVE if kind == "ict" else AOI_ARCHIVE
    sql = text(
        f"""
        SELECT purchase_no, count(*)::int AS n FROM (
            SELECT purchase_no FROM {hot} WHERE purchase_no = ANY(:pns)
            UNION ALL
            SELECT purchase_no FROM {archive} WHERE purchase_no = ANY(:pns)
        ) t
        WHERE purchase_no IS NOT NULL AND purchase_no <> ''
        GROUP BY purchase_no
        """
    )
    try:
        rows = db.execute(sql, {"pns": purchase_nos}).fetchall()
    except Exception:
        # 归档表尚未创建时退回热表
        db.rollback()
        rows = db.execute(
            text(
                f"""
                SELECT purchase_no, count(*)::int
                FROM {hot}
                WHERE purchase_no = ANY(:pns)
                GROUP BY purchase_no
                """
            ),
            {"pns": purchase_nos},
        ).fetchall()
    for pn, n in rows:
        key = (pn or "").strip()
        if key:
            out[key] = int(n or 0)
    return out


def counts_by_purchase_model(
    db: Session,
    purchase_nos: list[str],
    *,
    kind: str,
) -> dict[tuple[str, str], int]:
    """订单列表用：按 (purchase_no, model_code) 合计。

    机型优先取 laser_batches.model_code（贴码/镭雕登记），避免 ICT 板名
    （如 03019413-Sin-…）污染导致同 PO 多行都显示整单数量。
    """
    out: dict[tuple[str, str], int] = {}
    if not purchase_nos:
        return out
    hot = ICT_HOT if kind == "ict" else AOI_HOT
    archive = ICT_ARCHIVE if kind == "ict" else AOI_ARCHIVE

    def _run(include_archive: bool) -> list:
        archive_part = (
            f"""
            UNION ALL
            SELECT
                a.purchase_no,
                COALESCE(NULLIF(TRIM(lb.model_code), ''), NULLIF(TRIM(a.model_code), '')) AS model_code
            FROM {archive} a
            LEFT JOIN laser_batches lb ON lb.id = a.laser_batch_id
            WHERE a.purchase_no = ANY(:pns)
            """
            if include_archive
            else ""
        )
        sql = text(
            f"""
            SELECT purchase_no, upper(replace(model_code, ' ', '')) AS model_key, count(*)::int AS n
            FROM (
                SELECT
                    b.purchase_no,
                    COALESCE(NULLIF(TRIM(lb.model_code), ''), NULLIF(TRIM(b.model_code), '')) AS model_code
                FROM {hot} b
                LEFT JOIN laser_batches lb ON lb.id = b.laser_batch_id
                WHERE b.purchase_no = ANY(:pns)
                {archive_part}
            ) t
            WHERE purchase_no IS NOT NULL AND purchase_no <> ''
              AND model_code IS NOT NULL AND TRIM(model_code) <> ''
            GROUP BY purchase_no, upper(replace(model_code, ' ', ''))
            """
        )
        return db.execute(sql, {"pns": purchase_nos}).fetchall()

    try:
        rows = _run(include_archive=True)
    except Exception:
        db.rollback()
        rows = _run(include_archive=False)
    from engineering_service import normalize_code

    for pn, model_key, n in rows:
        pk = (pn or "").strip()
        mk = normalize_code(model_key)
        if pk and mk:
            out[(pk, mk)] = int(n or 0)
    return out


def _row_to_ns(row) -> SimpleNamespace:
    if hasattr(row, "_mapping"):
        return SimpleNamespace(**dict(row._mapping))
    return SimpleNamespace(**dict(row))


def find_board_by_barcode(db: Session, barcode: str, *, kind: str) -> Optional[SimpleNamespace]:
    """卡控用：热表优先，没有再查归档。"""
    code = (barcode or "").strip()
    if not code:
        return None
    hot = ICT_HOT if kind == "ict" else AOI_HOT
    archive = ICT_ARCHIVE if kind == "ict" else AOI_ARCHIVE
    row = db.execute(
        text(f"SELECT * FROM {hot} WHERE barcode = :b LIMIT 1"),
        {"b": code},
    ).first()
    if row:
        return _row_to_ns(row)
    try:
        row = db.execute(
            text(f"SELECT * FROM {archive} WHERE barcode = :b LIMIT 1"),
            {"b": code},
        ).first()
    except Exception:
        db.rollback()
        return None
    return _row_to_ns(row) if row else None


def purchase_board_stats(
    db: Session,
    purchase_no: str,
    *,
    kind: str,
    customer_id: str = "",
) -> dict[str, int]:
    """单采购单 PASS/FAIL/合计（热+归档）。"""
    pn = (purchase_no or "").strip()
    if not pn:
        return {"total": 0, "pass_count": 0, "fail_count": 0, "unknown_count": 0}
    hot = ICT_HOT if kind == "ict" else AOI_HOT
    archive = ICT_ARCHIVE if kind == "ict" else AOI_ARCHIVE
    cust_sql = " AND customer_id = :cid" if customer_id else ""
    params: dict[str, Any] = {"pn": pn}
    if customer_id:
        params["cid"] = customer_id
    sql = text(
        f"""
        SELECT
          count(*)::int AS total,
          coalesce(sum(CASE WHEN upper(result) = 'PASS' THEN 1 ELSE 0 END), 0)::int AS pass_n,
          coalesce(sum(CASE WHEN upper(result) IN ('FAIL','FALL','NG') THEN 1 ELSE 0 END), 0)::int AS fail_n
        FROM (
          SELECT result FROM {hot} WHERE purchase_no = :pn{cust_sql}
          UNION ALL
          SELECT result FROM {archive} WHERE purchase_no = :pn{cust_sql}
        ) t
        """
    )
    try:
        row = db.execute(sql, params).one()
    except Exception:
        db.rollback()
        row = db.execute(
            text(
                f"""
                SELECT
                  count(*)::int,
                  coalesce(sum(CASE WHEN upper(result) = 'PASS' THEN 1 ELSE 0 END), 0)::int,
                  coalesce(sum(CASE WHEN upper(result) IN ('FAIL','FALL','NG') THEN 1 ELSE 0 END), 0)::int
                FROM {hot}
                WHERE purchase_no = :pn{cust_sql}
                """
            ),
            params,
        ).one()
    total, pass_n, fail_n = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
    return {
        "total": total,
        "pass_count": pass_n,
        "fail_count": fail_n,
        "unknown_count": max(0, total - pass_n - fail_n),
    }
