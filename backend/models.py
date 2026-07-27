from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class SrmOrder(Base):
    """订单跟踪明细行（purchaseNo + purchaseSeq + purchasePhaseSeq）"""

    __tablename__ = "srm_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    line_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), index=True)
    purchase_seq: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    purchase_phase_seq: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    workorder_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 历史字段：内部工单号已停用，不再自动生成；列保留兼容旧数据
    internal_wo_no: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, unique=True, index=True)
    product_goods_no: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    product_goods_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    product_spec: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    batch_pur_qty: Mapped[float] = mapped_column(Float, default=0)
    delivery_qty: Mapped[float] = mapped_column(Float, default=0)
    receive_qty: Mapped[float] = mapped_column(Float, default=0)
    un_delivery_qty: Mapped[float] = mapped_column(Float, default=0)
    un_receive_qty: Mapped[float] = mapped_column(Float, default=0)
    output_qty: Mapped[float] = mapped_column(Float, default=0)
    collected_sets_qty: Mapped[float] = mapped_column(Float, default=0)
    doc_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    purchase_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    expect_arrival_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    order_type_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    no_tax_amount: Mapped[float] = mapped_column(Float, default=0)
    sum_tax_amount: Mapped[float] = mapped_column(Float, default=0)
    sum_no_tax_amount: Mapped[float] = mapped_column(Float, default=0)
    srm_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    srm_status_name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    data_source: Mapped[str] = mapped_column(String(64), default="订单跟踪")
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), default="菲利斯")
    customer_id: Mapped[str] = mapped_column(String(64), default="feilisi", index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    customer_kitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_controlled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InternalWoDailySeq(Base):
    """内部工单号按自然日（上海）流水"""

    __tablename__ = "internal_wo_daily_seq"

    day: Mapped[str] = mapped_column(String(8), primary_key=True)  # YYMMDD
    last_seq: Mapped[int] = mapped_column(Integer, default=0)


class OrderScan(Base):
    """包装扫码记录（每片 PCBA 唯一条码）"""

    __tablename__ = "order_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    line_key: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), index=True)
    barcode: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    code_type: Mapped[str] = mapped_column(String(16), default="unknown")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    shipment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class LegacyPackingScan(Base):
    """旧站 wang123 已包装冷表（全量保留，供对账/重挂）。"""

    __tablename__ = "legacy_packing_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    remote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True, index=True)
    barcode: Mapped[str] = mapped_column(String(128), default="", index=True)
    barcode_norm: Mapped[str] = mapped_column(String(128), default="", index=True)
    order_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    product_code: Mapped[str] = mapped_column(String(128), default="")
    product_name: Mapped[str] = mapped_column(String(256), default="")
    package_no: Mapped[str] = mapped_column(String(128), default="")
    package_status: Mapped[str] = mapped_column(String(16), default="")
    package_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    remote_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    line_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    match_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    synced_to_scans: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Shipment(Base):
    """本地发货单"""

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    line_key: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    product_goods_no: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    product_goods_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    ship_date: Mapped[str] = mapped_column(String(32))
    box_count: Mapped[int] = mapped_column(Integer, default=1)
    logistics: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SrmReconciliation(Base):
    """对账明细（发票/账单）"""

    __tablename__ = "srm_reconciliation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    record_type: Mapped[str] = mapped_column(String(32), default="invoice")
    record_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    no_tax_amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    status_name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    orders_synced: Mapped[int] = mapped_column(Integer, default=0)
    new_orders_count: Mapped[int] = mapped_column(Integer, default=0)
    new_orders_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kitting_alert_count: Mapped[int] = mapped_column(Integer, default=0)
    kitting_alert_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class ReceiveQtySnapshot(Base):
    """每日收货累计快照（用于推算日增量 / 月度收货）"""

    __tablename__ = "receive_qty_snapshots"
    __table_args__ = (UniqueConstraint("snap_date", "line_key", name="uq_receive_snap_date_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snap_date: Mapped[str] = mapped_column(String(10), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    line_key: Mapped[str] = mapped_column(String(128), index=True)
    product_goods_no: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    receive_qty: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReceiveQtyEvent(Base):
    """带日期的收货事件（看板月度对比底层数据）"""

    __tablename__ = "receive_qty_events"
    __table_args__ = (UniqueConstraint("source_key", name="uq_receive_event_source_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    event_date: Mapped[str] = mapped_column(String(10), index=True)
    product_goods_no: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    product_goods_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    qty: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(32), default="")
    source_key: Mapped[str] = mapped_column(String(256), index=True)
    line_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OrderLinePrice(Base):
    """订单行含税单价缓存：结案/删除后仍可供出货金额汇总。"""

    __tablename__ = "order_line_prices"
    __table_args__ = (UniqueConstraint("line_key", name="uq_order_line_price_line_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    line_key: Mapped[str] = mapped_column(String(128), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    product_goods_no: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    batch_pur_qty: Mapped[float] = mapped_column(Float, default=0)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="dept", index=True)
    department: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HrEmployee(Base):
    """人事员工档案（共享盘花名册 + 系统手工维护）"""

    __tablename__ = "hr_employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), default="", index=True)
    gender: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    id_card: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    age: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    age_band: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    hire_date: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    tenure_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tenure_band: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    position: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    education: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # 系统手工字段（共享盘同步不覆盖）
    hire_grade: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # 入职评审：A/B/C/D
    leave_date: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    leave_reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    lives_in_dorm: Mapped[bool] = mapped_column(Boolean, default=False)
    dorm_room: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="roster")  # roster | manual
    status_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # 手工改在职状态后，同步不改 is_active
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HrLeaveRecord(Base):
    """员工请假记录"""

    __tablename__ = "hr_leave_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(Integer, index=True)
    employee_no: Mapped[str] = mapped_column(String(32), index=True, default="")
    employee_name: Mapped[str] = mapped_column(String(64), default="")
    leave_type: Mapped[str] = mapped_column(String(32), default="事假", index=True)
    start_date: Mapped[str] = mapped_column(String(16), index=True)
    end_date: Mapped[str] = mapped_column(String(16), index=True)
    days: Mapped[float] = mapped_column(Float, default=1)
    reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="approved", index=True)  # approved|cancelled
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WarehouseMaterial(Base):
    """客户 + 物料编码 唯一库存"""

    __tablename__ = "warehouse_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    material_code: Mapped[str] = mapped_column(String(128), index=True)
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    spec: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    qty: Mapped[float] = mapped_column(Float, default=0)
    locked_qty: Mapped[float] = mapped_column(Float, default=0)
    excel_count_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    excel_in_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    excel_demand_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    excel_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MaterialMountProfile(Base):
    """物料贴装主数据（料号级 SMT/DIP/ASSY/N/A；internal_code 空=全局，非空=客户专属）"""

    __tablename__ = "material_mount_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_code: Mapped[str] = mapped_column(String(128), index=True)
    internal_code: Mapped[str] = mapped_column(String(16), default="", index=True)
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    mount_type: Mapped[str] = mapped_column(String(8), default="")
    mount_side: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockInRecord(Base):
    """来料/入库记录"""

    __tablename__ = "stock_in_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_no: Mapped[str] = mapped_column(String(32), index=True)
    material_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    material_code: Mapped[str] = mapped_column(String(128))
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    qty: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(24), default="manual", index=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    giver: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    receiver: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StockIssue(Base):
    """发料/领料单"""

    __tablename__ = "stock_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    material_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    material_code: Mapped[str] = mapped_column(String(128))
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    qty: Mapped[float] = mapped_column(Float, default=0)
    department: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending_confirm", index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class StockReturn(Base):
    """退料单"""

    __tablename__ = "stock_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    material_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    material_code: Mapped[str] = mapped_column(String(128))
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    qty: Mapped[float] = mapped_column(Float, default=0)
    department: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending_warehouse", index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    applicant: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class StockLedger(Base):
    """库存流水"""

    __tablename__ = "stock_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    material_code: Mapped[str] = mapped_column(String(128))
    movement_type: Mapped[str] = mapped_column(String(24), index=True)
    qty_delta: Mapped[float] = mapped_column(Float, default=0)
    qty_after: Mapped[float] = mapped_column(Float, default=0)
    ref_no: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    giver: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    receiver: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WarehouseMovement(Base):
    """共享盘 / 系统物料进出账明细（含按订单发料）"""

    __tablename__ = "warehouse_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    movement_type: Mapped[str] = mapped_column(String(24), index=True)
    material_code: Mapped[str] = mapped_column(String(128), index=True)
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    spec: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    qty: Mapped[float] = mapped_column(Float, default=0)
    qty_delta: Mapped[float] = mapped_column(Float, default=0)
    order_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    product_model: Mapped[str] = mapped_column(String(128), default="", index=True)
    order_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    process: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    doc_date: Mapped[str] = mapped_column(String(32), default="", index=True)
    ref_no: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(24), default="excel_sync", index=True)
    source_file: Mapped[str] = mapped_column(String(512), default="")
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    giver: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    receiver: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WarehouseWorkbookSnapshot(Base):
    """客户进销表 workbook 归档元数据"""

    __tablename__ = "warehouse_workbook_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    source_file: Mapped[str] = mapped_column(String(512), default="")
    file_name: Mapped[str] = mapped_column(String(256), default="")
    file_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sheet_names: Mapped[str] = mapped_column(Text, default="[]")
    sheet_count: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WarehouseSheetSnapshot(Base):
    """进销表单个 sheet 全量单元格 JSON"""

    __tablename__ = "warehouse_sheet_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    source_file: Mapped[str] = mapped_column(String(512), default="")
    sheet_name: Mapped[str] = mapped_column(String(128), index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    col_count: Mapped[int] = mapped_column(Integer, default=0)
    data_json: Mapped[str] = mapped_column(Text, default="[]")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExcelImportLog(Base):
    __tablename__ = "excel_import_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_file: Mapped[str] = mapped_column(String(512))
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="success")
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BomModel(Base):
    """工程 BOM：内部代码 + 机型料号 + 采购订单号（订单专属；purchase_no 空为历史机型级）"""

    __tablename__ = "bom_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    internal_code: Mapped[str] = mapped_column(String(16), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    model_code: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    model_spec: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    folder_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_file: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    # BOM 内容指纹：同版本（明细一致）可跨订单同步坐标/Gerber
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    mount_profile_override: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    # 工程资料审核：pending_import / pending_review / approved / rejected
    eng_review_status: Mapped[str] = mapped_column(String(24), default="pending_import", index=True)
    eng_review_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    eng_submitter: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    eng_submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    eng_reviewed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    eng_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EngReviewInbox(Base):
    """工程资料待审推送（导入后自动写入，审核员可见）"""

    __tablename__ = "eng_review_inbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_model_id: Mapped[int] = mapped_column(Integer, index=True)
    internal_code: Mapped[str] = mapped_column(String(16), default="")
    model_code: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="")
    event_type: Mapped[str] = mapped_column(String(32), default="submit")  # submit / resubmit
    summary: Mapped[str] = mapped_column(String(512), default="")
    submitter: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="unread", index=True)  # unread / read / done
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EngOrderHide(Base):
    """工程资料侧「删除订单」：从目录隐藏，不删 SRM 在制单。"""

    __tablename__ = "eng_order_hides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    internal_code: Mapped[str] = mapped_column(String(16), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), index=True)
    model_code: Mapped[str] = mapped_column(String(128), default="")
    model_code_norm: Mapped[str] = mapped_column(String(128), default="", index=True)
    hidden_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BomLine(Base):
    """BOM 明细行"""

    __tablename__ = "bom_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_model_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), index=True)
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    spec: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    qty_per: Mapped[float] = mapped_column(Float, default=1)
    position: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    process: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source: Mapped[str] = mapped_column(String(24), default="import")
    control_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    control_prev_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class MaterialControl(Base):
    """物料管制单头（可含多机型分组）"""

    __tablename__ = "material_controls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    control_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model_code: Mapped[str] = mapped_column(String(512), default="", index=True)  # 机型汇总展示
    control_type: Mapped[str] = mapped_column(String(64), default="PCBA管制")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ecn_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    attachment_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    attachment_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MaterialControlGroup(Base):
    """管制单机型分组"""

    __tablename__ = "material_control_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    control_id: Mapped[int] = mapped_column(Integer, index=True)
    model_code: Mapped[str] = mapped_column(String(128), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class MaterialControlOrder(Base):
    """管制单关联工单（归属某机型分组）"""

    __tablename__ = "material_control_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    control_id: Mapped[int] = mapped_column(Integer, index=True)
    group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), index=True)
    line_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    # 工单总量（如 10000）；与各换料行的本批管制数量不同
    order_qty: Mapped[float] = mapped_column(Float, default=0)
    # 合计管制套数（各换料行 control_qty 之和，便于列表展示）
    control_qty: Mapped[float] = mapped_column(Float, default=0)


class MaterialControlChange(Base):
    """管制单换料明细（归属某机型分组）；可带本批管制套数"""

    __tablename__ = "material_control_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    control_id: Mapped[int] = mapped_column(Integer, index=True)
    group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # 本批从工单中抽出的管制套数（如三行各 500，不是整单 10000）
    control_qty: Mapped[float] = mapped_column(Float, default=0)
    remove_code: Mapped[str] = mapped_column(String(128), default="")
    remove_qty: Mapped[float] = mapped_column(Float, default=0)
    remove_refdes: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    add_code: Mapped[str] = mapped_column(String(128), default="")
    add_qty: Mapped[float] = mapped_column(Float, default=0)
    add_refdes: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class SubstitutionRule(Base):
    """客户替代料规则（按 customer_id 隔离，人工导入）"""

    __tablename__ = "substitution_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    comp_code: Mapped[str] = mapped_column(String(64), index=True)
    comp_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    comp_spec: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comp_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    comp_unit_small: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    comp_attr: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    parent_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    parent_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    parent_spec: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    parent_unit_small: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    parent_attr: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    relation_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sub_code: Mapped[str] = mapped_column(String(64), index=True)
    sub_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    sub_spec: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sub_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sub_unit_small: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sub_attr: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sub_order: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    effective_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    expiry_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    source_file: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    import_batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class YonglianSubSheet(Base):
    """永联订单物料替代/发料明细单（对齐客户传图版式）"""

    __tablename__ = "yonglian_sub_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True, default="yonglian")
    internal_code: Mapped[str] = mapped_column(String(16), default="A067")
    model_code: Mapped[str] = mapped_column(String(128), index=True, default="")
    purchase_no: Mapped[str] = mapped_column(String(64), index=True, default="")
    order_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    process: Mapped[str] = mapped_column(String(16), default="SMT")
    fixture_note: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    source_file: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lines: Mapped[list["YonglianSubSheetLine"]] = relationship(
        "YonglianSubSheetLine",
        back_populates="sheet",
        cascade="all, delete-orphan",
    )


class YonglianSubSheetLine(Base):
    """永联替代明细行（序号/贴装/面别/元件品号/…/需求/发料/退料）"""

    __tablename__ = "yonglian_sub_sheet_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sheet_id: Mapped[int] = mapped_column(Integer, ForeignKey("yonglian_sub_sheets.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    mount_type: Mapped[str] = mapped_column(String(16), default="SMT")
    mount_side: Mapped[str] = mapped_column(String(16), default="")
    material_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    spec: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    qty_per: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    required_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    issue_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    sheet: Mapped[Optional["YonglianSubSheet"]] = relationship("YonglianSubSheet", back_populates="lines")


class ModelProcessRoute(Base):
    """机型工序对照（工艺明细 + 手工勾选）"""

    __tablename__ = "model_process_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    internal_code: Mapped[str] = mapped_column(String(16), index=True)
    model_code: Mapped[str] = mapped_column(String(128), index=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    raw_process: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    steps_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ModelToolingEntry(Base):
    """机型工装登记（钢网 / 波峰治具 / ICT·FCT 测试工装）"""

    __tablename__ = "model_tooling_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    internal_code: Mapped[str] = mapped_column(String(16), index=True)
    model_code: Mapped[str] = mapped_column(String(128), index=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    tool_type: Mapped[str] = mapped_column(String(24), index=True)
    tool_code: Mapped[str] = mapped_column(String(128), default="")
    version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    stored_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PcbPlacementFile(Base):
    """PCB 贴片坐标文件（机型级或订单级；菲利斯按 purchase_no 隔离）"""

    __tablename__ = "pcb_placement_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    internal_code: Mapped[str] = mapped_column(String(16), index=True)
    model_code: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    board_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    folder_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_file: Mapped[str] = mapped_column(String(512))
    source_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    file_format: Mapped[str] = mapped_column(String(32), default="unknown")
    units: Mapped[str] = mapped_column(String(8), default="mm")
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="share")
    audit_status: Mapped[str] = mapped_column(String(16), default="pending")
    audit_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PcbPlacementLine(Base):
    """贴片坐标明细（位号级）"""

    __tablename__ = "pcb_placement_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    placement_file_id: Mapped[int] = mapped_column(Integer, index=True)
    refdes: Mapped[str] = mapped_column(String(32), index=True)
    comment: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    footprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    layer: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    mid_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mid_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pad_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pad_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rotation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    skip: Mapped[bool] = mapped_column(Boolean, default=False)
    material_hint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class PcbRefmapFile(Base):
    """位号图 / 装配图 PDF（机型级或订单级）"""

    __tablename__ = "pcb_refmap_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    internal_code: Mapped[str] = mapped_column(String(16), index=True)
    model_code: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    folder_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    file_name: Mapped[str] = mapped_column(String(256), default="")
    source_path: Mapped[str] = mapped_column(String(512), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    source_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    audit_status: Mapped[str] = mapped_column(String(16), default="pending")
    audit_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PcbGerberPackage(Base):
    """Gerber 资料包（机型级或订单级）"""

    __tablename__ = "pcb_gerber_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    internal_code: Mapped[str] = mapped_column(String(16), index=True)
    model_code: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    package_name: Mapped[str] = mapped_column(String(256))
    folder_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_path: Mapped[str] = mapped_column(String(512))
    files_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    source_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="share")
    audit_status: Mapped[str] = mapped_column(String(16), default="pending")
    audit_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class QuoteOrder(Base):
    """独立订单报价单（不关联系统订单中心）"""

    __tablename__ = "quote_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    product_name: Mapped[str] = mapped_column(String(256), default="")
    product_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)  # draft/calculated/confirmed/void
    batch_qty: Mapped[float] = mapped_column(Float, default=0)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    tooling_total: Mapped[float] = mapped_column(Float, default=0)
    engineering_fee: Mapped[float] = mapped_column(Float, default=0)
    grand_total: Mapped[float] = mapped_column(Float, default=0)
    source_filename: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class QuoteBomLine(Base):
    """报价 BOM 快照（与工程 BomLine 无关）"""

    __tablename__ = "quote_bom_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    seq: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    spec: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    qty_per: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    position: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    package: Mapped[str] = mapped_column(String(32), default="")
    bucket: Mapped[str] = mapped_column(String(32), default="")  # chip1/chip2/ic/bigpad/dip/skip
    ic_amount: Mapped[float] = mapped_column(Float, default=0)  # P列
    dip_points: Mapped[float] = mapped_column(Float, default=0)  # Q列
    calc_points: Mapped[float] = mapped_column(Float, default=0)
    calc_amount: Mapped[float] = mapped_column(Float, default=0)


class QuoteCostLine(Base):
    """报价费用明细（对应鼎雄报价模版工艺行）"""

    __tablename__ = "quote_cost_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(String(32), default="")  # smt/dip/pre/post/tooling/summary
    item_key: Mapped[str] = mapped_column(String(64), default="")
    item_name: Mapped[str] = mapped_column(String(128), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    points: Mapped[float] = mapped_column(Float, default=0)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    note: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    editable: Mapped[bool] = mapped_column(Boolean, default=False)


class ProductionSchedule(Base):
    """SMT/DIP 排产行（计划员全编辑）"""

    __tablename__ = "production_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    line_type: Mapped[str] = mapped_column(String(8), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    line_name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    line_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    internal_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    model_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    process: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    order_qty: Mapped[float] = mapped_column(Float, default=0)
    due_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    material_status: Mapped[str] = mapped_column(String(24), default="unknown")
    daily_plan: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    schedule_status: Mapped[str] = mapped_column(String(24), default="planned")
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LaserBatch(Base):
    """镭雕/贴码登记：流水段 → 采购订单号。

    菲利斯：D0 镭雕（laser_date + model_mid/ver + seq）
    恩玖：人工贴码（barcode_prefix 12 位 + seq）
    """

    __tablename__ = "laser_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), default="feilisi", index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    laser_date: Mapped[str] = mapped_column(String(8), index=True)  # YYMMDD；恩玖用打印日期
    model_code: Mapped[str] = mapped_column(String(64), index=True)
    model_mid: Mapped[str] = mapped_column(String(16), index=True)
    model_ver: Mapped[str] = mapped_column(String(8), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), index=True)
    order_qty: Mapped[float] = mapped_column(Float, default=0)
    seq_from: Mapped[int] = mapped_column(Integer)
    seq_to: Mapped[int] = mapped_column(Integer)
    # 恩玖贴码前 12 位（固定+物料+供应商+年周）；菲利斯为空
    barcode_prefix: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="manual")
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AoiBoardResult(Base):
    """AOI 单板测试结果（按条码唯一，可归属采购单）"""

    __tablename__ = "aoi_board_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model_mid: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    model_ver: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    laser_date: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, index=True)
    seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="UNKNOWN", index=True)
    machine: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    line_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    source_file: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    laser_batch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AoiSyncFile(Base):
    """已处理的 AOI 源文件（按机台 + 文件名去重）"""

    __tablename__ = "aoi_sync_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    filename: Mapped[str] = mapped_column(String(256), index=True)
    file_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IctBoardResult(Base):
    """ICT 单板测试结果（按条码唯一，可归属采购单）"""

    __tablename__ = "ict_board_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model_mid: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    model_ver: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    laser_date: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, index=True)
    seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    board_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="UNKNOWN", index=True)
    machine_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    ict_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    source_file: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_host: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    laser_batch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IctSyncFile(Base):
    """已处理的 ICT 源文件（按机台+文件名）"""

    __tablename__ = "ict_sync_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    filename: Mapped[str] = mapped_column(String(256), index=True)
    file_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProcessScanRecord(Base):
    """产线工序扫码（插件 / 后焊 / 三防），按条码+工位唯一"""

    __tablename__ = "process_scan_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode: Mapped[str] = mapped_column(String(64), index=True)
    station: Mapped[str] = mapped_column(String(32), index=True)  # plugin / post_solder / coating
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    laser_batch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    model_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

