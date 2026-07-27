import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger(__name__)


def migrate():
    """增量迁移：SQLite 走本文件；Postgres 走 migrate_postgres（禁止对 PG 执行 PRAGMA）。"""
    if engine.dialect.name == "postgresql":
        from migrate_postgres import migrate_postgres

        logger.info("当前数据库为 postgresql，执行 Postgres 增量迁移")
        migrate_postgres()
        return
    if engine.dialect.name != "sqlite":
        logger.warning("跳过 migrate：不支持的数据库方言 %s", engine.dialect.name)
        return

    with engine.connect() as conn:
        order_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(srm_orders)"))}

        # 旧表 purchase_no 有 UNIQUE 约束，需重建
        if "line_key" not in order_cols:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS srm_orders_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_key VARCHAR(128) UNIQUE,
                    purchase_no VARCHAR(64),
                    purchase_seq VARCHAR(16),
                    purchase_phase_seq VARCHAR(16),
                    workorder_no VARCHAR(64),
                    product_goods_no VARCHAR(128),
                    product_goods_name VARCHAR(256),
                    product_spec VARCHAR(512),
                    batch_pur_qty FLOAT DEFAULT 0,
                    output_qty FLOAT DEFAULT 0,
                    collected_sets_qty FLOAT DEFAULT 0,
                    doc_date VARCHAR(32),
                    purchase_date VARCHAR(32),
                    expect_arrival_date VARCHAR(32),
                    order_type_name VARCHAR(64),
                    tax_amount FLOAT DEFAULT 0,
                    no_tax_amount FLOAT DEFAULT 0,
                    sum_tax_amount FLOAT DEFAULT 0,
                    sum_no_tax_amount FLOAT DEFAULT 0,
                    srm_status VARCHAR(16),
                    srm_status_name VARCHAR(32),
                    is_completed BOOLEAN DEFAULT 0,
                    data_source VARCHAR(64) DEFAULT '订单跟踪',
                    customer_name VARCHAR(128) DEFAULT '菲利斯',
                    synced_at DATETIME
                )
            """))
            conn.execute(text("DROP TABLE IF EXISTS srm_orders"))
            conn.execute(text("ALTER TABLE srm_orders_new RENAME TO srm_orders"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_srm_orders_purchase_no ON srm_orders (purchase_no)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_srm_orders_purchase_date ON srm_orders (purchase_date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_srm_orders_is_completed ON srm_orders (is_completed)"))
        else:
            new_cols = {
                "batch_pur_qty": "FLOAT DEFAULT 0",
                "delivery_qty": "FLOAT DEFAULT 0",
                "receive_qty": "FLOAT DEFAULT 0",
                "un_delivery_qty": "FLOAT DEFAULT 0",
                "un_receive_qty": "FLOAT DEFAULT 0",
                "expect_arrival_date": "VARCHAR(32)",
                "tax_amount": "FLOAT DEFAULT 0",
                "no_tax_amount": "FLOAT DEFAULT 0",
                "data_source": "VARCHAR(64) DEFAULT '订单跟踪'",
            }
            for col, typedef in new_cols.items():
                if col not in order_cols:
                    conn.execute(text(f"ALTER TABLE srm_orders ADD COLUMN {col} {typedef}"))

            # 旧版 purchase_no 唯一索引会阻止一行多单，改为普通索引
            conn.execute(text("DROP INDEX IF EXISTS ix_srm_orders_purchase_no"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_srm_orders_purchase_no ON srm_orders (purchase_no)"
            ))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_srm_orders_line_key ON srm_orders (line_key)"
            ))

        if "customer_id" not in order_cols:
            conn.execute(text(
                "ALTER TABLE srm_orders ADD COLUMN customer_id VARCHAR(64) DEFAULT 'feilisi'"
            ))
            conn.execute(text("UPDATE srm_orders SET customer_id = 'feilisi' WHERE customer_id IS NULL"))
            conn.execute(text(
                "UPDATE srm_orders SET line_key = 'feilisi|' || line_key "
                "WHERE line_key NOT LIKE '%|%|%|%'"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_srm_orders_customer_id ON srm_orders (customer_id)"
            ))

        order_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(srm_orders)"))}
        if "remark" not in order_cols:
            conn.execute(text("ALTER TABLE srm_orders ADD COLUMN remark VARCHAR(128)"))

        log_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(sync_logs)"))}
        if "new_orders_count" not in log_cols:
            conn.execute(text("ALTER TABLE sync_logs ADD COLUMN new_orders_count INTEGER DEFAULT 0"))
        if "new_orders_detail" not in log_cols:
            conn.execute(text("ALTER TABLE sync_logs ADD COLUMN new_orders_detail TEXT"))

        log_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(sync_logs)"))}
        if "customer_id" not in log_cols:
            conn.execute(text("ALTER TABLE sync_logs ADD COLUMN customer_id VARCHAR(64)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS srm_reconciliation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_no VARCHAR(64) UNIQUE,
                record_type VARCHAR(32) DEFAULT 'invoice',
                record_date VARCHAR(32),
                tax_amount FLOAT DEFAULT 0,
                no_tax_amount FLOAT DEFAULT 0,
                status VARCHAR(16),
                status_name VARCHAR(32),
                synced_at DATETIME
            )
        """))

        # 清理卡住的同步日志
        conn.execute(text(
            "UPDATE sync_logs SET status='failed', message='迁移中断，请重新同步' "
            "WHERE status='running'"
        ))

        # 停用恩玖·康虹健：清理历史订单及关联扫码/发货记录
        conn.execute(text("DELETE FROM order_scans WHERE line_key LIKE 'enjiu_kanghongjian|%'"))
        conn.execute(text("DELETE FROM shipments WHERE line_key LIKE 'enjiu_kanghongjian|%'"))
        conn.execute(text("DELETE FROM srm_orders WHERE customer_id = 'enjiu_kanghongjian'"))

        order_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(srm_orders)"))}
        if "bom_model_id" not in order_cols:
            conn.execute(text("ALTER TABLE srm_orders ADD COLUMN bom_model_id INTEGER"))

        order_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(srm_orders)"))}
        if "customer_kitted_at" not in order_cols:
            conn.execute(text("ALTER TABLE srm_orders ADD COLUMN customer_kitted_at DATETIME"))
            conn.execute(text(
                "UPDATE srm_orders SET customer_kitted_at = synced_at "
                "WHERE customer_id = 'feilisi' AND collected_sets_qty > 0 AND customer_kitted_at IS NULL"
            ))

        order_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(srm_orders)"))}
        if "material_status" not in order_cols:
            conn.execute(text("ALTER TABLE srm_orders ADD COLUMN material_status VARCHAR(24)"))

        log_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(sync_logs)"))}
        if "kitting_alert_count" not in log_cols:
            conn.execute(text("ALTER TABLE sync_logs ADD COLUMN kitting_alert_count INTEGER DEFAULT 0"))
        if "kitting_alert_detail" not in log_cols:
            conn.execute(text("ALTER TABLE sync_logs ADD COLUMN kitting_alert_detail TEXT"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bom_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                internal_code VARCHAR(16),
                customer_id VARCHAR(64),
                customer_name VARCHAR(128) DEFAULT '',
                model_code VARCHAR(128),
                purchase_no VARCHAR(64) DEFAULT '',
                model_name VARCHAR(256),
                model_spec VARCHAR(512),
                folder_name VARCHAR(256),
                source_file VARCHAR(512),
                source_mtime FLOAT,
                line_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                remark VARCHAR(256),
                synced_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_bom_models_customer_id ON bom_models (customer_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bom_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bom_model_id INTEGER,
                seq VARCHAR(16),
                material_code VARCHAR(128),
                material_name VARCHAR(256),
                spec VARCHAR(512),
                unit VARCHAR(16) DEFAULT 'PCS',
                qty_per FLOAT DEFAULT 1,
                position VARCHAR(128),
                process VARCHAR(64),
                remark VARCHAR(256),
                sort_order INTEGER DEFAULT 0
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_bom_lines_bom_model_id ON bom_lines (bom_model_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS production_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_type VARCHAR(8),
                sort_order INTEGER DEFAULT 0,
                line_name VARCHAR(32),
                line_key VARCHAR(128),
                internal_code VARCHAR(16),
                customer_id VARCHAR(64),
                purchase_no VARCHAR(64),
                model_code VARCHAR(128),
                model_name VARCHAR(256),
                process VARCHAR(64),
                order_qty FLOAT DEFAULT 0,
                due_date VARCHAR(32),
                material_status VARCHAR(24) DEFAULT 'unknown',
                daily_plan VARCHAR(128),
                schedule_status VARCHAR(24) DEFAULT 'planned',
                remark VARCHAR(256),
                updated_by VARCHAR(64),
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_production_schedules_line_type "
            "ON production_schedules (line_type, sort_order)"
        ))

        sub_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(substitution_rules)"))}
        if not sub_cols:
            conn.execute(text("""
                CREATE TABLE substitution_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comp_code VARCHAR(64),
                    comp_name VARCHAR(256),
                    comp_spec TEXT,
                    comp_unit VARCHAR(16),
                    comp_unit_small VARCHAR(16),
                    comp_attr VARCHAR(64),
                    parent_code VARCHAR(64),
                    parent_name VARCHAR(256),
                    parent_spec TEXT,
                    parent_unit VARCHAR(16),
                    parent_unit_small VARCHAR(16),
                    parent_attr VARCHAR(64),
                    relation_type VARCHAR(32),
                    sub_code VARCHAR(64),
                    sub_name VARCHAR(256),
                    sub_spec TEXT,
                    sub_unit VARCHAR(16),
                    sub_unit_small VARCHAR(16),
                    sub_attr VARCHAR(64),
                    sub_order VARCHAR(16),
                    effective_date VARCHAR(32),
                    expiry_date VARCHAR(32),
                    qty FLOAT,
                    remark VARCHAR(256),
                    source_file VARCHAR(512),
                    synced_at DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_substitution_rules_comp_code ON substitution_rules (comp_code)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_substitution_rules_parent_code ON substitution_rules (parent_code)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_substitution_rules_sub_code ON substitution_rules (sub_code)"
            ))

        proc_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(model_process_routes)"))}
        if not proc_cols:
            conn.execute(text("""
                CREATE TABLE model_process_routes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    internal_code VARCHAR(16),
                    model_code VARCHAR(128),
                    model_name VARCHAR(256),
                    bom_model_id INTEGER,
                    source VARCHAR(16) DEFAULT 'manual',
                    raw_process TEXT,
                    steps_json TEXT,
                    status VARCHAR(24) DEFAULT 'pending',
                    remark VARCHAR(256),
                    synced_at DATETIME,
                    updated_by VARCHAR(64),
                    updated_at DATETIME,
                    created_at DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_model_process_routes_code "
                "ON model_process_routes (internal_code, model_code)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_model_process_routes_status ON model_process_routes (status)"
            ))

        place_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(pcb_placement_files)"))}
        if not place_cols:
            conn.execute(text("""
                CREATE TABLE pcb_placement_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bom_model_id INTEGER,
                    internal_code VARCHAR(16),
                    model_code VARCHAR(128),
                    board_name VARCHAR(256),
                    folder_name VARCHAR(256),
                    source_file VARCHAR(512),
                    source_mtime FLOAT,
                    file_format VARCHAR(32) DEFAULT 'unknown',
                    units VARCHAR(8) DEFAULT 'mm',
                    line_count INTEGER DEFAULT 0,
                    source VARCHAR(16) DEFAULT 'share',
                    synced_at DATETIME,
                    updated_at DATETIME,
                    created_at DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_pcb_placement_files_model "
                "ON pcb_placement_files (internal_code, model_code)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_pcb_placement_files_bom ON pcb_placement_files (bom_model_id)"
            ))
            conn.execute(text("""
                CREATE TABLE pcb_placement_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    placement_file_id INTEGER,
                    refdes VARCHAR(32),
                    comment VARCHAR(128),
                    footprint VARCHAR(64),
                    layer VARCHAR(16),
                    mid_x FLOAT,
                    mid_y FLOAT,
                    pad_x FLOAT,
                    pad_y FLOAT,
                    rotation FLOAT,
                    skip BOOLEAN DEFAULT 0,
                    material_hint VARCHAR(64),
                    sort_order INTEGER DEFAULT 0
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_pcb_placement_lines_file ON pcb_placement_lines (placement_file_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_pcb_placement_lines_refdes ON pcb_placement_lines (refdes)"
            ))

        bom_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(bom_models)"))}
        if "mount_profile_override" not in bom_cols:
            conn.execute(text(
                "ALTER TABLE bom_models ADD COLUMN mount_profile_override VARCHAR(24)"
            ))
        if "purchase_no" not in bom_cols:
            conn.execute(text(
                "ALTER TABLE bom_models ADD COLUMN purchase_no VARCHAR(64) DEFAULT ''"
            ))
            conn.execute(text("UPDATE bom_models SET purchase_no = '' WHERE purchase_no IS NULL"))
        for col, typedef in {
            "eng_review_status": "VARCHAR(24) DEFAULT 'pending_import'",
            "eng_review_message": "VARCHAR(512)",
            "eng_submitter": "VARCHAR(64)",
            "eng_submitted_at": "DATETIME",
            "eng_reviewed_by": "VARCHAR(64)",
            "eng_reviewed_at": "DATETIME",
        }.items():
            if col not in bom_cols:
                conn.execute(text(f"ALTER TABLE bom_models ADD COLUMN {col} {typedef}"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eng_review_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bom_model_id INTEGER NOT NULL,
                internal_code VARCHAR(16) DEFAULT '',
                model_code VARCHAR(128) DEFAULT '',
                purchase_no VARCHAR(64) DEFAULT '',
                event_type VARCHAR(32) DEFAULT 'submit',
                summary VARCHAR(512) DEFAULT '',
                submitter VARCHAR(64),
                status VARCHAR(16) DEFAULT 'unread',
                created_at DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_eng_review_inbox_status ON eng_review_inbox (status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_eng_review_inbox_bom ON eng_review_inbox (bom_model_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eng_order_hides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                internal_code VARCHAR(16) NOT NULL,
                purchase_no VARCHAR(64) NOT NULL,
                model_code VARCHAR(128) DEFAULT '',
                model_code_norm VARCHAR(128) DEFAULT '',
                hidden_by VARCHAR(64),
                created_at DATETIME
            )
        """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_eng_order_hides_scope "
            "ON eng_order_hides (internal_code, purchase_no, model_code_norm)"
        ))

        # 唯一键改为 内部代码+机型+订单号；兼容旧机型级（purchase_no 空串）
        conn.execute(text("DROP INDEX IF EXISTS ix_bom_models_code"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_bom_models_code_order "
            "ON bom_models (internal_code, model_code, purchase_no)"
        ))
        # 旧「机型级共用」绑定作废：在制单需按订单号重新导入确认
        try:
            conn.execute(text("""
                UPDATE srm_orders
                SET bom_model_id = NULL
                WHERE is_completed = 0
                  AND bom_model_id IS NOT NULL
                  AND bom_model_id IN (
                    SELECT id FROM bom_models
                    WHERE purchase_no IS NULL OR purchase_no = ''
                  )
            """))
        except Exception:
            pass

        gerber_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(pcb_gerber_packages)"))}
        if "audit_status" not in gerber_cols:
            conn.execute(text(
                "ALTER TABLE pcb_gerber_packages ADD COLUMN audit_status VARCHAR(16) DEFAULT 'pending'"
            ))
        if "audit_message" not in gerber_cols:
            conn.execute(text(
                "ALTER TABLE pcb_gerber_packages ADD COLUMN audit_message VARCHAR(512)"
            ))

        place_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(pcb_placement_files)"))}
        if place_cols and "audit_status" not in place_cols:
            conn.execute(text(
                "ALTER TABLE pcb_placement_files ADD COLUMN audit_status VARCHAR(16) DEFAULT 'pending'"
            ))
        if place_cols and "audit_message" not in place_cols:
            conn.execute(text(
                "ALTER TABLE pcb_placement_files ADD COLUMN audit_message VARCHAR(512)"
            ))

        gerber_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(pcb_gerber_packages)"))}
        if not gerber_cols:
            conn.execute(text("""
                CREATE TABLE pcb_gerber_packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bom_model_id INTEGER,
                    internal_code VARCHAR(16),
                    model_code VARCHAR(128),
                    package_name VARCHAR(256),
                    folder_name VARCHAR(256),
                    source_path VARCHAR(512),
                    files_json TEXT,
                    file_count INTEGER DEFAULT 0,
                    source_mtime FLOAT,
                    source VARCHAR(16) DEFAULT 'share',
                    synced_at DATETIME,
                    updated_at DATETIME,
                    created_at DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_pcb_gerber_packages_model "
                "ON pcb_gerber_packages (internal_code, model_code)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_pcb_gerber_packages_bom ON pcb_gerber_packages (bom_model_id)"
            ))

        refmap_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(pcb_refmap_files)"))}
        if not refmap_cols:
            conn.execute(text("""
                CREATE TABLE pcb_refmap_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bom_model_id INTEGER,
                    internal_code VARCHAR(16),
                    model_code VARCHAR(128),
                    folder_name VARCHAR(256),
                    file_name VARCHAR(256) DEFAULT '',
                    source_path VARCHAR(512) DEFAULT '',
                    file_size INTEGER DEFAULT 0,
                    page_count INTEGER DEFAULT 0,
                    source VARCHAR(16) DEFAULT 'manual',
                    source_mtime FLOAT,
                    audit_status VARCHAR(16) DEFAULT 'pending',
                    audit_message VARCHAR(512),
                    synced_at DATETIME,
                    updated_at DATETIME,
                    created_at DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_pcb_refmap_files_model "
                "ON pcb_refmap_files (internal_code, model_code)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_pcb_refmap_files_bom ON pcb_refmap_files (bom_model_id)"
            ))

        # 恩玖 v2 无客户齐套字段：清除历史误记的齐料数据
        conn.execute(text(
            "UPDATE srm_orders SET collected_sets_qty = 0, material_status = NULL, "
            "customer_kitted_at = NULL WHERE customer_id = 'enjiu'"
        ))

        tooling_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(model_tooling_entries)"))}
        if not tooling_cols:
            conn.execute(text("""
                CREATE TABLE model_tooling_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    internal_code VARCHAR(16),
                    model_code VARCHAR(128),
                    model_name VARCHAR(256),
                    bom_model_id INTEGER,
                    tool_type VARCHAR(24),
                    tool_code VARCHAR(128) DEFAULT '',
                    version VARCHAR(64),
                    qty INTEGER DEFAULT 1,
                    stored_at VARCHAR(32),
                    remark VARCHAR(256),
                    source VARCHAR(16) DEFAULT 'manual',
                    updated_by VARCHAR(64),
                    updated_at DATETIME,
                    created_at DATETIME
                )
            """))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_model_tooling_unique "
                "ON model_tooling_entries (internal_code, model_code, tool_type)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_model_tooling_bom ON model_tooling_entries (bom_model_id)"
            ))

        wh_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(warehouse_materials)"))}
        for col, typedef in {
            "excel_count_qty": "FLOAT",
            "excel_in_qty": "FLOAT",
            "excel_demand_qty": "FLOAT",
            "excel_synced_at": "DATETIME",
        }.items():
            if col not in wh_cols:
                conn.execute(text(f"ALTER TABLE warehouse_materials ADD COLUMN {col} {typedef}"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_mount_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_code VARCHAR(128) NOT NULL UNIQUE,
                material_name VARCHAR(256),
                mount_type VARCHAR(8) DEFAULT '',
                mount_side VARCHAR(16),
                source VARCHAR(16) DEFAULT 'manual',
                updated_by VARCHAR(64),
                updated_at DATETIME,
                created_at DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_material_mount_profiles_code "
            "ON material_mount_profiles (material_code)"
        ))
        mmp_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(material_mount_profiles)"))}
        if mmp_cols and "internal_code" not in mmp_cols:
            conn.execute(text(
                "ALTER TABLE material_mount_profiles ADD COLUMN internal_code VARCHAR(16) DEFAULT ''"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_material_mount_profiles_scope "
                "ON material_mount_profiles (internal_code, material_code)"
            ))

        user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        if user_cols and "must_change_password" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS warehouse_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id VARCHAR(64) NOT NULL,
                customer_name VARCHAR(128) DEFAULT '',
                movement_type VARCHAR(24) NOT NULL,
                material_code VARCHAR(128) NOT NULL,
                material_name VARCHAR(256),
                spec VARCHAR(512),
                unit VARCHAR(16) DEFAULT 'PCS',
                qty FLOAT DEFAULT 0,
                qty_delta FLOAT DEFAULT 0,
                order_no VARCHAR(64) DEFAULT '',
                product_model VARCHAR(128) DEFAULT '',
                order_qty FLOAT,
                process VARCHAR(16),
                doc_date VARCHAR(32) DEFAULT '',
                ref_no VARCHAR(64) DEFAULT '',
                source VARCHAR(24) DEFAULT 'excel_sync',
                source_file VARCHAR(512) DEFAULT '',
                dedupe_key VARCHAR(64) NOT NULL UNIQUE,
                remark VARCHAR(256),
                operator VARCHAR(64),
                created_at DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_wh_movements_customer ON warehouse_movements (customer_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_wh_movements_order ON warehouse_movements (order_no)"
        ))
        wm_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(warehouse_movements)"))}
        if wm_cols and "operator" not in wm_cols:
            conn.execute(text("ALTER TABLE warehouse_movements ADD COLUMN operator VARCHAR(64)"))
        for col in ("giver", "receiver"):
            if wm_cols and col not in wm_cols:
                conn.execute(text(f"ALTER TABLE warehouse_movements ADD COLUMN {col} VARCHAR(64)"))

        ledger_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(stock_ledger)"))}
        for col in ("giver", "receiver"):
            if ledger_cols and col not in ledger_cols:
                conn.execute(text(f"ALTER TABLE stock_ledger ADD COLUMN {col} VARCHAR(64)"))

        stock_in_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(stock_in_records)"))}
        for col in ("giver", "receiver"):
            if stock_in_cols and col not in stock_in_cols:
                conn.execute(text(f"ALTER TABLE stock_in_records ADD COLUMN {col} VARCHAR(64)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS warehouse_workbook_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id VARCHAR(64) NOT NULL,
                customer_name VARCHAR(128) DEFAULT '',
                source_file VARCHAR(512) DEFAULT '',
                file_name VARCHAR(256) DEFAULT '',
                file_mtime FLOAT,
                sheet_names TEXT DEFAULT '[]',
                sheet_count INTEGER DEFAULT 0,
                synced_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS warehouse_sheet_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                customer_id VARCHAR(64) NOT NULL,
                customer_name VARCHAR(128) DEFAULT '',
                source_file VARCHAR(512) DEFAULT '',
                sheet_name VARCHAR(128) NOT NULL,
                row_count INTEGER DEFAULT 0,
                col_count INTEGER DEFAULT 0,
                data_json TEXT DEFAULT '[]',
                synced_at DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_wh_sheet_snap_customer ON warehouse_sheet_snapshots (customer_id, sheet_name)"
        ))

        # —— 物料管制 ——
        order_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(srm_orders)"))}
        if "is_controlled" not in order_cols:
            conn.execute(text("ALTER TABLE srm_orders ADD COLUMN is_controlled BOOLEAN DEFAULT 0"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_srm_orders_is_controlled ON srm_orders (is_controlled)"
            ))

        bom_line_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(bom_lines)"))}
        if bom_line_cols:
            if "is_active" not in bom_line_cols:
                conn.execute(text("ALTER TABLE bom_lines ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                conn.execute(text("UPDATE bom_lines SET is_active = 1 WHERE is_active IS NULL"))
            if "source" not in bom_line_cols:
                conn.execute(text("ALTER TABLE bom_lines ADD COLUMN source VARCHAR(24) DEFAULT 'import'"))
            if "control_id" not in bom_line_cols:
                conn.execute(text("ALTER TABLE bom_lines ADD COLUMN control_id INTEGER"))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_bom_lines_control_id ON bom_lines (control_id)"
                ))
            if "control_prev_qty" not in bom_line_cols:
                conn.execute(text("ALTER TABLE bom_lines ADD COLUMN control_prev_qty FLOAT"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_controls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                control_no VARCHAR(64) NOT NULL UNIQUE,
                model_code VARCHAR(128) NOT NULL,
                control_type VARCHAR(64) DEFAULT 'PCBA管制',
                reason TEXT,
                ecn_no VARCHAR(64),
                attachment_path VARCHAR(512),
                attachment_name VARCHAR(256),
                status VARCHAR(16) DEFAULT 'draft',
                created_by VARCHAR(64),
                confirmed_by VARCHAR(64),
                confirmed_at DATETIME,
                cancelled_by VARCHAR(64),
                cancelled_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_material_controls_status ON material_controls (status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_material_controls_model ON material_controls (model_code)"
        ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_control_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                control_id INTEGER NOT NULL,
                purchase_no VARCHAR(64) NOT NULL,
                line_key VARCHAR(128),
                control_qty FLOAT DEFAULT 0
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_mco_control ON material_control_orders (control_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_mco_purchase ON material_control_orders (purchase_no)"
        ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_control_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                control_id INTEGER NOT NULL,
                remove_code VARCHAR(128) DEFAULT '',
                remove_qty FLOAT DEFAULT 0,
                remove_refdes VARCHAR(128),
                add_code VARCHAR(128) DEFAULT '',
                add_qty FLOAT DEFAULT 0,
                add_refdes VARCHAR(128),
                remark VARCHAR(512)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_mcc_control ON material_control_changes (control_id)"
        ))

        # —— 多机型分组 ——
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_control_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                control_id INTEGER NOT NULL,
                model_code VARCHAR(128) NOT NULL,
                sort_order INTEGER DEFAULT 0
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_mcg_control ON material_control_groups (control_id)"
        ))
        mco_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(material_control_orders)"))}
        if mco_cols and "group_id" not in mco_cols:
            conn.execute(text("ALTER TABLE material_control_orders ADD COLUMN group_id INTEGER"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_mco_group ON material_control_orders (group_id)"
            ))
        if mco_cols and "order_qty" not in mco_cols:
            conn.execute(text("ALTER TABLE material_control_orders ADD COLUMN order_qty FLOAT DEFAULT 0"))
        mcc_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(material_control_changes)"))}
        if mcc_cols and "group_id" not in mcc_cols:
            conn.execute(text("ALTER TABLE material_control_changes ADD COLUMN group_id INTEGER"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_mcc_group ON material_control_changes (group_id)"
            ))
        if mcc_cols and "control_qty" not in mcc_cols:
            conn.execute(text("ALTER TABLE material_control_changes ADD COLUMN control_qty FLOAT DEFAULT 0"))
        # 旧数据：每张单一个分组，回填 group_id
        controls = conn.execute(text("SELECT id, model_code FROM material_controls")).fetchall()
        for cid, mcode in controls:
            gid_row = conn.execute(
                text("SELECT id FROM material_control_groups WHERE control_id = :cid LIMIT 1"),
                {"cid": cid},
            ).fetchone()
            if gid_row:
                gid = gid_row[0]
            else:
                conn.execute(
                    text(
                        "INSERT INTO material_control_groups (control_id, model_code, sort_order) "
                        "VALUES (:cid, :mc, 0)"
                    ),
                    {"cid": cid, "mc": (mcode or "").strip() or "UNKNOWN"},
                )
                gid = conn.execute(text("SELECT last_insert_rowid()")).scalar()
            conn.execute(
                text(
                    "UPDATE material_control_orders SET group_id = :gid "
                    "WHERE control_id = :cid AND (group_id IS NULL OR group_id = 0)"
                ),
                {"gid": gid, "cid": cid},
            )
            conn.execute(
                text(
                    "UPDATE material_control_changes SET group_id = :gid "
                    "WHERE control_id = :cid AND (group_id IS NULL OR group_id = 0)"
                ),
                {"gid": gid, "cid": cid},
            )

        # 收货累计日快照（菲利斯/恩玖看板月度增量）
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS receive_qty_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snap_date VARCHAR(10) NOT NULL,
                    customer_id VARCHAR(64) NOT NULL,
                    line_key VARCHAR(128) NOT NULL,
                    product_goods_no VARCHAR(128),
                    receive_qty FLOAT DEFAULT 0,
                    created_at DATETIME,
                    UNIQUE (snap_date, line_key)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_receive_qty_snapshots_snap_date "
                "ON receive_qty_snapshots (snap_date)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_receive_qty_snapshots_customer_id "
                "ON receive_qty_snapshots (customer_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_receive_qty_snapshots_line_key "
                "ON receive_qty_snapshots (line_key)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_receive_qty_snapshots_product_goods_no "
                "ON receive_qty_snapshots (product_goods_no)"
            )
        )

        # 带日期的收货事件（看板上月/本月对比底层）
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS receive_qty_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id VARCHAR(64) NOT NULL,
                    event_date VARCHAR(10) NOT NULL,
                    product_goods_no VARCHAR(128),
                    product_goods_name VARCHAR(256),
                    qty FLOAT DEFAULT 0,
                    source VARCHAR(32) DEFAULT '',
                    source_key VARCHAR(256) NOT NULL UNIQUE,
                    line_key VARCHAR(128),
                    synced_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_receive_qty_events_customer_id "
                "ON receive_qty_events (customer_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_receive_qty_events_event_date "
                "ON receive_qty_events (event_date)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_receive_qty_events_product_goods_no "
                "ON receive_qty_events (product_goods_no)"
            )
        )

        # 内部生产工单号（按订单行；与客户采购单号区分）
        order_cols = {row[1]: row for row in conn.execute(text("PRAGMA table_info(srm_orders)"))}
        if "internal_wo_no" not in order_cols:
            conn.execute(text("ALTER TABLE srm_orders ADD COLUMN internal_wo_no VARCHAR(32)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_srm_orders_internal_wo_no "
                "ON srm_orders (internal_wo_no)"
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS internal_wo_daily_seq (
                    day VARCHAR(8) PRIMARY KEY,
                    last_seq INTEGER DEFAULT 0
                )
                """
            )
        )

        # 镭雕登记 + AOI 结果
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS laser_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id VARCHAR(64) DEFAULT 'feilisi',
                    customer_name VARCHAR(128),
                    laser_date VARCHAR(8),
                    model_code VARCHAR(64),
                    model_mid VARCHAR(16),
                    model_ver VARCHAR(8),
                    purchase_no VARCHAR(64),
                    order_qty FLOAT DEFAULT 0,
                    seq_from INTEGER,
                    seq_to INTEGER,
                    remark VARCHAR(256),
                    source VARCHAR(24) DEFAULT 'manual',
                    created_by VARCHAR(64),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_laser_batches_purchase_no ON laser_batches (purchase_no)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_laser_batches_laser_date ON laser_batches (laser_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_laser_batches_model_mid ON laser_batches (model_mid)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS aoi_board_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode VARCHAR(64) UNIQUE,
                    model_mid VARCHAR(16),
                    model_ver VARCHAR(8),
                    laser_date VARCHAR(8),
                    seq INTEGER,
                    model_code VARCHAR(64),
                    product_name VARCHAR(128),
                    side VARCHAR(8),
                    result VARCHAR(16) DEFAULT 'UNKNOWN',
                    machine VARCHAR(64),
                    line_name VARCHAR(64),
                    tested_at DATETIME,
                    source_file VARCHAR(256),
                    purchase_no VARCHAR(64),
                    customer_id VARCHAR(64),
                    laser_batch_id INTEGER,
                    synced_at DATETIME
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_aoi_board_results_purchase_no ON aoi_board_results (purchase_no)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_aoi_board_results_barcode ON aoi_board_results (barcode)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS aoi_sync_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename VARCHAR(256) UNIQUE,
                    file_mtime FLOAT,
                    file_size INTEGER,
                    row_count INTEGER DEFAULT 0,
                    processed_at DATETIME
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS order_line_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_key VARCHAR(128) NOT NULL UNIQUE,
                    customer_id VARCHAR(64) NOT NULL,
                    purchase_no VARCHAR(64),
                    product_goods_no VARCHAR(128),
                    tax_amount FLOAT DEFAULT 0,
                    batch_pur_qty FLOAT DEFAULT 0,
                    unit_price FLOAT DEFAULT 0,
                    source VARCHAR(64) DEFAULT '',
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_order_line_prices_customer_id "
                "ON order_line_prices (customer_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_order_line_prices_purchase_no "
                "ON order_line_prices (purchase_no)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS hr_employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_no VARCHAR(32) NOT NULL UNIQUE,
                    name VARCHAR(64) DEFAULT '',
                    gender VARCHAR(8),
                    id_card VARCHAR(32),
                    age FLOAT,
                    age_band VARCHAR(32),
                    phone VARCHAR(32),
                    address VARCHAR(512),
                    hire_date VARCHAR(16),
                    tenure_years FLOAT,
                    tenure_band VARCHAR(32),
                    department VARCHAR(64),
                    position VARCHAR(64),
                    education VARCHAR(32),
                    remark VARCHAR(256),
                    is_active BOOLEAN DEFAULT 1,
                    synced_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_hr_employees_name ON hr_employees (name)"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hr_employees_department ON hr_employees (department)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hr_employees_is_active ON hr_employees (is_active)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hr_employees_hire_date ON hr_employees (hire_date)")
        )

        # 人事扩展字段：入职评审 / 离职 / 宿舍
        hr_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(hr_employees)"))}
        hr_extra_cols = {
            "hire_grade": "VARCHAR(16)",
            "leave_date": "VARCHAR(16)",
            "leave_reason": "VARCHAR(256)",
            "lives_in_dorm": "BOOLEAN DEFAULT 0",
            "dorm_room": "VARCHAR(32)",
            "source": "VARCHAR(16) DEFAULT 'roster'",
            "status_locked": "BOOLEAN DEFAULT 0",
        }
        for col, typedef in hr_extra_cols.items():
            if col not in hr_cols:
                conn.execute(text(f"ALTER TABLE hr_employees ADD COLUMN {col} {typedef}"))

        # 菲利斯：BOM 内容指纹 + 坐标/Gerber/位号图按订单隔离
        bom_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(bom_models)"))}
        if "content_hash" not in bom_cols:
            conn.execute(text("ALTER TABLE bom_models ADD COLUMN content_hash VARCHAR(64) DEFAULT ''"))
            conn.execute(text("UPDATE bom_models SET content_hash = '' WHERE content_hash IS NULL"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_bom_models_content_hash ON bom_models (content_hash)")
        )

        for table in ("pcb_placement_files", "pcb_gerber_packages", "pcb_refmap_files"):
            cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not cols:
                continue
            if "purchase_no" not in cols:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN purchase_no VARCHAR(64) DEFAULT ''")
                )
                conn.execute(text(f"UPDATE {table} SET purchase_no = '' WHERE purchase_no IS NULL"))
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_order "
                    f"ON {table} (internal_code, model_code, purchase_no)"
                )
            )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS hr_leave_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    employee_no VARCHAR(32) DEFAULT '',
                    employee_name VARCHAR(64) DEFAULT '',
                    leave_type VARCHAR(32) DEFAULT '事假',
                    start_date VARCHAR(16) NOT NULL,
                    end_date VARCHAR(16) NOT NULL,
                    days FLOAT DEFAULT 1,
                    reason VARCHAR(512),
                    status VARCHAR(16) DEFAULT 'approved',
                    created_by VARCHAR(64),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hr_leave_records_employee_id ON hr_leave_records (employee_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hr_leave_records_employee_no ON hr_leave_records (employee_no)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hr_leave_records_start_date ON hr_leave_records (start_date)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hr_leave_records_leave_type ON hr_leave_records (leave_type)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hr_leave_records_status ON hr_leave_records (status)")
        )

        # 替代料按客户隔离
        sub_rule_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(substitution_rules)"))}
        if sub_rule_cols:
            if "customer_id" not in sub_rule_cols:
                conn.execute(
                    text("ALTER TABLE substitution_rules ADD COLUMN customer_id VARCHAR(64) DEFAULT ''")
                )
            conn.execute(
                text(
                    "UPDATE substitution_rules SET customer_id = 'feilisi' "
                    "WHERE customer_id IS NULL OR customer_id = ''"
                )
            )
            if "source_type" not in sub_rule_cols:
                conn.execute(
                    text("ALTER TABLE substitution_rules ADD COLUMN source_type VARCHAR(24)")
                )
                conn.execute(
                    text(
                        "UPDATE substitution_rules SET source_type = 'legacy_migrate' "
                        "WHERE source_type IS NULL OR source_type = ''"
                    )
                )
            if "import_batch_id" not in sub_rule_cols:
                conn.execute(
                    text("ALTER TABLE substitution_rules ADD COLUMN import_batch_id VARCHAR(64)")
                )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_substitution_rules_customer_id "
                    "ON substitution_rules (customer_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_substitution_rules_import_batch "
                    "ON substitution_rules (import_batch_id)"
                )
            )

        # 永联订单替代/发料明细单（图片版式）
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS yonglian_sub_sheets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id VARCHAR(64) DEFAULT 'yonglian',
                    internal_code VARCHAR(16) DEFAULT 'A067',
                    model_code VARCHAR(128) DEFAULT '',
                    purchase_no VARCHAR(64) DEFAULT '',
                    order_qty FLOAT,
                    process VARCHAR(16) DEFAULT 'SMT',
                    fixture_note VARCHAR(128),
                    source_type VARCHAR(24),
                    source_file VARCHAR(512),
                    line_count INTEGER DEFAULT 0,
                    synced_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_yonglian_sub_sheets_purchase "
                "ON yonglian_sub_sheets (purchase_no)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_yonglian_sub_sheets_model "
                "ON yonglian_sub_sheets (model_code)"
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS yonglian_sub_sheet_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sheet_id INTEGER NOT NULL,
                    seq INTEGER DEFAULT 0,
                    mount_type VARCHAR(16) DEFAULT 'SMT',
                    mount_side VARCHAR(16) DEFAULT '',
                    material_code VARCHAR(64) DEFAULT '',
                    material_name VARCHAR(256),
                    spec TEXT,
                    unit VARCHAR(16),
                    qty_per FLOAT,
                    position VARCHAR(512),
                    required_qty FLOAT,
                    issue_qty FLOAT,
                    return_qty FLOAT,
                    sort_order INTEGER DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_yonglian_sub_sheet_lines_sheet "
                "ON yonglian_sub_sheet_lines (sheet_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_yonglian_sub_sheet_lines_code "
                "ON yonglian_sub_sheet_lines (material_code)"
            )
        )

        # ICT 测试结果（TRI .dcl）
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ict_board_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode VARCHAR(64) UNIQUE,
                    model_mid VARCHAR(16),
                    model_ver VARCHAR(8),
                    laser_date VARCHAR(8),
                    seq INTEGER,
                    model_code VARCHAR(64),
                    board_name VARCHAR(128),
                    result VARCHAR(16) DEFAULT 'UNKNOWN',
                    machine_id VARCHAR(32),
                    ict_id VARCHAR(32),
                    tested_at DATETIME,
                    source_file VARCHAR(256),
                    source_host VARCHAR(64),
                    purchase_no VARCHAR(64),
                    customer_id VARCHAR(64),
                    laser_batch_id INTEGER,
                    synced_at DATETIME
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ict_board_results_purchase_no ON ict_board_results (purchase_no)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ict_board_results_barcode ON ict_board_results (barcode)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ict_board_results_result ON ict_board_results (result)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ict_board_results_machine_id ON ict_board_results (machine_id)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ict_sync_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    machine_id VARCHAR(32) DEFAULT '',
                    filename VARCHAR(256),
                    file_mtime FLOAT,
                    file_size INTEGER,
                    row_count INTEGER DEFAULT 0,
                    processed_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_ict_sync_files_machine_file "
                "ON ict_sync_files (machine_id, filename)"
            )
        )

        # 产线工序扫码：插件 / 后焊 / 三防
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS process_scan_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode VARCHAR(64) NOT NULL,
                    station VARCHAR(32) NOT NULL,
                    purchase_no VARCHAR(64),
                    customer_id VARCHAR(64),
                    laser_batch_id INTEGER,
                    model_code VARCHAR(64),
                    operator VARCHAR(64),
                    scanned_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_process_scan_barcode_station "
                "ON process_scan_records (barcode, station)"
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_process_scan_purchase_no ON process_scan_records (purchase_no)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_process_scan_station ON process_scan_records (station)"))

        # AOI 多机：aoi_sync_files 增加 machine_id，去掉全局 filename 唯一
        aoi_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(aoi_sync_files)")).fetchall()}
        if aoi_cols and "machine_id" not in aoi_cols:
            conn.execute(
                text(
                    """
                    CREATE TABLE aoi_sync_files_v2 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        machine_id VARCHAR(32) DEFAULT '',
                        filename VARCHAR(256),
                        file_mtime FLOAT,
                        file_size INTEGER,
                        row_count INTEGER DEFAULT 0,
                        processed_at DATETIME
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO aoi_sync_files_v2 (id, machine_id, filename, file_mtime, file_size, row_count, processed_at)
                    SELECT id, 'aoi-115', filename, file_mtime, file_size, row_count, processed_at
                    FROM aoi_sync_files
                    """
                )
            )
            conn.execute(text("DROP TABLE aoi_sync_files"))
            conn.execute(text("ALTER TABLE aoi_sync_files_v2 RENAME TO aoi_sync_files"))
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_aoi_sync_files_machine_file "
                    "ON aoi_sync_files (machine_id, filename)"
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_aoi_sync_files_machine_id ON aoi_sync_files (machine_id)"))

        conn.commit()


if __name__ == "__main__":
    migrate()
    print("迁移完成")
