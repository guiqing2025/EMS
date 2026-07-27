"""Postgres 增量迁移：补齐 SQLite migrate() 曾建、但 PG 启动跳过的唯一索引等。"""
from __future__ import annotations

import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger(__name__)


def migrate_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        # 仓库物料：先清已知重复再加唯一
        dups = conn.execute(
            text(
                """
                SELECT customer_id, material_code, array_agg(id ORDER BY id) AS ids
                FROM warehouse_materials
                GROUP BY customer_id, material_code
                HAVING count(*) > 1
                """
            )
        ).fetchall()
        for customer_id, material_code, ids in dups:
            keep, *drop = list(ids)
            logger.warning(
                "合并重复仓库物料 %s/%s 保留 id=%s 删除 %s",
                customer_id,
                material_code,
                keep,
                drop,
            )
            for did in drop:
                conn.execute(
                    text("DELETE FROM warehouse_materials WHERE id = :id"),
                    {"id": did},
                )

        statements = [
            """
            CREATE TABLE IF NOT EXISTS legacy_packing_scans (
                id SERIAL PRIMARY KEY,
                remote_id INTEGER UNIQUE,
                barcode VARCHAR(128) DEFAULT '',
                barcode_norm VARCHAR(128) DEFAULT '',
                order_no VARCHAR(64) DEFAULT '',
                product_code VARCHAR(128) DEFAULT '',
                product_name VARCHAR(256) DEFAULT '',
                package_no VARCHAR(128) DEFAULT '',
                package_status VARCHAR(16) DEFAULT '',
                package_at TIMESTAMP,
                remote_updated_at TIMESTAMP,
                line_key VARCHAR(128),
                match_status VARCHAR(16) DEFAULT 'pending',
                synced_to_scans BOOLEAN DEFAULT FALSE,
                raw_json TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_legacy_packing_barcode_norm
            ON legacy_packing_scans (barcode_norm)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_legacy_packing_order_no
            ON legacy_packing_scans (order_no)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_legacy_packing_match
            ON legacy_packing_scans (match_status)
            """,
            """
            CREATE TABLE IF NOT EXISTS eng_order_hides (
                id SERIAL PRIMARY KEY,
                internal_code VARCHAR(16) NOT NULL,
                purchase_no VARCHAR(64) NOT NULL,
                model_code VARCHAR(128) DEFAULT '',
                model_code_norm VARCHAR(128) DEFAULT '',
                hidden_by VARCHAR(64),
                created_at TIMESTAMP
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_eng_order_hides_scope
            ON eng_order_hides (internal_code, purchase_no, model_code_norm)
            """,
            # 工序扫码：同一条码同一工位只能一条
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_process_scan_barcode_station
            ON process_scan_records (barcode, station)
            """,
            # ICT / AOI 同步文件去重
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_ict_sync_files_machine_file
            ON ict_sync_files (machine_id, filename)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_aoi_sync_files_machine_file
            ON aoi_sync_files (machine_id, filename)
            """,
            # 仓库：客户 + 料号
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_warehouse_materials_customer_code
            ON warehouse_materials (customer_id, material_code)
            """,
            # 工装登记（与 SQLite migrate 一致：机型 + 工装类型）
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_model_tooling_unique
            ON model_tooling_entries (internal_code, model_code, tool_type)
            """,
            # 常用查询加速
            """
            CREATE INDEX IF NOT EXISTS ix_ict_board_barcode
            ON ict_board_results (barcode)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_ict_board_purchase_no
            ON ict_board_results (purchase_no)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_warehouse_movements_customer_code
            ON warehouse_movements (customer_id, material_code)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_process_scan_purchase_station
            ON process_scan_records (purchase_no, station)
            """,
            # —— 联合索引：避免板测/工序/订单常用列表全表扫描 ——
            """
            CREATE INDEX IF NOT EXISTS ix_ict_board_purchase_tested
            ON ict_board_results (purchase_no, tested_at DESC NULLS LAST)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_aoi_board_purchase_tested
            ON aoi_board_results (purchase_no, tested_at DESC NULLS LAST)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_process_scan_purchase_station_scanned
            ON process_scan_records (purchase_no, station, scanned_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_order_scans_line_status
            ON order_scans (line_key, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_srm_orders_customer_completed
            ON srm_orders (customer_id, is_completed)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_srm_orders_customer_purchase_date
            ON srm_orders (customer_id, purchase_date DESC NULLS LAST)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_receive_events_customer_date
            ON receive_qty_events (customer_id, event_date)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_stock_ledger_material_created
            ON stock_ledger (material_id, created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_wh_movements_customer_doc_date
            ON warehouse_movements (customer_id, doc_date DESC NULLS LAST)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_ict_sync_files_processed_at
            ON ict_sync_files (processed_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_aoi_sync_files_processed_at
            ON aoi_sync_files (processed_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_ict_board_unmatched
            ON ict_board_results (id DESC)
            WHERE purchase_no IS NULL OR purchase_no = ''
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_aoi_board_unmatched
            ON aoi_board_results (id DESC)
            WHERE purchase_no IS NULL OR purchase_no = ''
            """,
            # —— 板测冷热归档表 ——
            """
            CREATE TABLE IF NOT EXISTS ict_board_results_archive
            AS TABLE ict_board_results WITH NO DATA
            """,
            """
            CREATE TABLE IF NOT EXISTS aoi_board_results_archive
            AS TABLE aoi_board_results WITH NO DATA
            """,
            """
            ALTER TABLE ict_board_results_archive
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP
            """,
            """
            ALTER TABLE aoi_board_results_archive
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_ict_board_results_archive_barcode
            ON ict_board_results_archive (barcode)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_aoi_board_results_archive_barcode
            ON aoi_board_results_archive (barcode)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_ict_board_results_archive_purchase
            ON ict_board_results_archive (purchase_no)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_aoi_board_results_archive_purchase
            ON aoi_board_results_archive (purchase_no)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_ict_archive_purchase_tested
            ON ict_board_results_archive (purchase_no, tested_at DESC NULLS LAST)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_aoi_archive_purchase_tested
            ON aoi_board_results_archive (purchase_no, tested_at DESC NULLS LAST)
            """,
            """
            ALTER TABLE laser_batches
            ADD COLUMN IF NOT EXISTS barcode_prefix VARCHAR(16)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_laser_batches_barcode_prefix
            ON laser_batches (barcode_prefix)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_laser_enjiu_prefix_seq
            ON laser_batches (customer_id, barcode_prefix, seq_from, seq_to)
            """,
        ]
        for sql in statements:
            try:
                conn.execute(text(sql))
            except Exception:
                logger.exception("Postgres migrate 语句失败: %s", sql.strip().split("\n")[0][:80])
                raise

        # AOI CSV 无测试时间列，时间在文件名 YYYYMMDDHHMMSS；回填历史空 tested_at
        try:
            result = conn.execute(
                text(
                    """
                    UPDATE aoi_board_results
                    SET tested_at = to_timestamp(
                        substring(source_file from '(\\d{14})\\.csv$'),
                        'YYYYMMDDHH24MISS'
                    )
                    WHERE tested_at IS NULL
                      AND source_file ~ '\\d{14}\\.csv$'
                    """
                )
            )
            filled = result.rowcount or 0
            if filled:
                logger.info("AOI tested_at 自文件名回填 %s 行", filled)
        except Exception:
            logger.exception("AOI tested_at 回填失败（可忽略，不影响启动）")

    logger.info("Postgres 增量迁移完成（唯一索引/查询索引）")
