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
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), default="客户A")
    customer_id: Mapped[str] = mapped_column(String(64), default="feilisi", index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    customer_kitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_controlled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # processing=加工订单；expense=费用订单（钢网/治具/测试工装等）
    biz_kind: Mapped[str] = mapped_column(String(16), default="processing", index=True)
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
    box_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
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


class ShipmentSlip(Base):
    """多订单合并送货单（一张打印单可含多个订单行出库）。"""

    __tablename__ = "shipment_slips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slip_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ship_date: Mapped[str] = mapped_column(String(32))
    logistics: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    total_qty: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Shipment(Base):
    """本地发货单（单订单行出库；可挂到合并送货单 slip_id）"""

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    slip_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    line_key: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    product_goods_no: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    product_goods_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    ship_date: Mapped[str] = mapped_column(String(32))
    box_count: Mapped[int] = mapped_column(Integer, default=1)
    qty_per_box: Mapped[int] = mapped_column(Integer, default=1)
    logistics: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # pending=待审核(未计入已发); approved=已确认已发货
    approval_status: Mapped[str] = mapped_column(String(16), default="approved", index=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ShipmentBox(Base):
    """发货箱：一箱绑定本箱板码，箱号二维码可追溯。"""

    __tablename__ = "shipment_boxes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    box_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    shipment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    slip_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    line_key: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="")
    product_goods_no: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    product_goods_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    box_index: Mapped[int] = mapped_column(Integer, default=1)
    box_count: Mapped[int] = mapped_column(Integer, default=1)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    qty_target: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="sealed", index=True)
    pack_mode: Mapped[str] = mapped_column(String(16), default="ship")
    ship_date: Mapped[str] = mapped_column(String(32), default="")
    label_printed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    label_printed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
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
    # JSON：{"pages":["orders-list",...]}；空=按角色默认
    module_perms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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


class EngIssuePrintLog(Base):
    """工程发料单打印记录（开发补齐模型，完整逻辑见 eng_issue_print_service）。"""

    __tablename__ = "eng_issue_print_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    model_code: Mapped[str] = mapped_column(String(128), default="")
    line_key: Mapped[str] = mapped_column(String(128), default="")
    printed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


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
    # 采购订单号：空=机型/客户级；非空=仅该订单生效
    purchase_no: Mapped[str] = mapped_column(String(64), index=True, default="")
    relation_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sub_code: Mapped[str] = mapped_column(String(64), index=True, default="")
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
    # confirmed=已确认可同步发料/BOM；pending=待人工确认替代料
    confirm_status: Mapped[str] = mapped_column(String(16), index=True, default="confirmed")
    source_type: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    source_file: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    import_batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class YonglianSubSheet(Base):
    """客户C订单物料替代/发料明细单（对齐客户传图版式）"""

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
    """客户C替代明细行（序号/贴装/面别/元件品号/…/需求/发料/退料）"""

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
    """PCB 贴片坐标文件（机型级或订单级；客户A按 purchase_no 隔离）"""

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
    """成本报价 / 对外报价（阶段1可挂询价单）"""

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
    # 阶段1：挂询价 / 供应商成本备注 / 对外卖价
    inquiry_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quote_kind: Mapped[str] = mapped_column(String(16), default="cost")  # cost / customer
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    supplier_cost: Mapped[float] = mapped_column(Float, default=0)
    sell_price: Mapped[float] = mapped_column(Float, default=0)
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
    """报价费用明细（对应加工报价模版工艺行）"""

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


class ProductionMasterPlan(Base):
    """生产主计划：客户/订单/机型/交期/上线日等（与扫码无关）"""

    __tablename__ = "production_master_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    line_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    model_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    order_qty: Mapped[float] = mapped_column(Float, default=0)
    customer_due_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    material_prep_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    smt_online_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    dip_online_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    order_status: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LaserBatch(Base):
    """镭雕/贴码登记：流水段 → 采购订单号。

    客户A：D0 镭雕（laser_date + model_mid/ver + seq）
    客户B：人工贴码（barcode_prefix 12 位 + seq）
    """

    __tablename__ = "laser_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), default="feilisi", index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    laser_date: Mapped[str] = mapped_column(String(8), index=True)  # YYMMDD；客户B用打印日期
    model_code: Mapped[str] = mapped_column(String(64), index=True)
    model_mid: Mapped[str] = mapped_column(String(16), index=True)
    model_ver: Mapped[str] = mapped_column(String(8), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), index=True)
    order_qty: Mapped[float] = mapped_column(Float, default=0)
    seq_from: Mapped[int] = mapped_column(Integer)
    seq_to: Mapped[int] = mapped_column(Integer)
    # 贴码（前缀+流水）前 12 位（固定+物料+供应商+年周）；客户A为空
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
    # 机台 CSV 缺陷明细摘要（位号:现象），供品质维修改判展示
    defect_summary: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    defect_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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


class PreOvenAoiBoardResult(Base):
    """炉前 AOI（mes_data）单板结果：同步挂单；后焊扫码卡控前置。"""

    __tablename__ = "pre_oven_aoi_board_results"

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
    fail_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    machine: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    source_file: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    laser_batch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PreOvenAoiSyncFile(Base):
    """炉前 AOI 已处理源文件去重。"""

    __tablename__ = "pre_oven_aoi_sync_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(String(32), default="pre-oven-aoi", index=True)
    filename: Mapped[str] = mapped_column(String(256), index=True)
    file_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PreOvenAoiQcRecord(Base):
    """炉前 AOI 产线复判 / 品质改判审计（独立于扫码写入路径）。"""

    __tablename__ = "pre_oven_aoi_qc_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(16), index=True)  # line_pass | line_fail | qc_pass
    prev_result: Mapped[str] = mapped_column(String(16))
    fail_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prev_machine: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    prev_source_file: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    prev_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    model_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    operator: Mapped[str] = mapped_column(String(64), index=True)
    operator_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AoiQcOverride(Base):
    """品质人工将 AOI FAIL 改判为 PASS 的审计记录（不删原机台 FAIL 痕迹字段在本表）。"""

    __tablename__ = "aoi_qc_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode: Mapped[str] = mapped_column(String(64), index=True)
    prev_result: Mapped[str] = mapped_column(String(16))
    new_result: Mapped[str] = mapped_column(String(16), default="PASS")
    prev_machine: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    prev_source_file: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    prev_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    purchase_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    model_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(256))
    remark: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    operator: Mapped[str] = mapped_column(String(64), index=True)
    operator_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    storage: Mapped[str] = mapped_column(String(16), default="hot")  # hot | archive
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ProcessDefectImportBatch(Base):
    """制程不良 Excel 导入批次"""

    __tablename__ = "process_defect_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(256))
    operator: Mapped[str] = mapped_column(String(64), index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    customers: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    year_months: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    replaced_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ProcessDefectRecord(Base):
    """制程不良明细（来自品质 Excel 导入）"""

    __tablename__ = "process_defect_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, index=True)
    seq_no: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    report_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    defect_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    year_month: Mapped[str] = mapped_column(String(7), default="", index=True)  # YYYY-MM
    customer_project: Mapped[str] = mapped_column(String(64), default="", index=True)
    model_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    ref_des: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    defect_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phenomenon: Mapped[str] = mapped_column(String(128), default="", index=True)
    phenomenon_norm: Mapped[str] = mapped_column(String(128), default="", index=True)
    qty: Mapped[float] = mapped_column(Float, default=0)
    remark: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    station: Mapped[str] = mapped_column(String(32), default="", index=True)
    inspect_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    defect_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    good_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    defect_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ComplaintImportBatch(Base):
    """客诉 Excel 导入批次"""

    __tablename__ = "complaint_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(256))
    operator: Mapped[str] = mapped_column(String(64), index=True)
    customer: Mapped[str] = mapped_column(String(64), default="", index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    year_months: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    replaced_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ComplaintRecord(Base):
    """客诉/检修不良明细"""

    __tablename__ = "complaint_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, index=True)
    customer: Mapped[str] = mapped_column(String(64), default="", index=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    complaint_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    year_month: Mapped[str] = mapped_column(String(7), default="", index=True)
    model_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    pcba_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    station: Mapped[str] = mapped_column(String(64), default="", index=True)
    ref_des: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    phenomenon: Mapped[str] = mapped_column(String(128), default="")
    phenomenon_norm: Mapped[str] = mapped_column(String(128), default="", index=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    qty: Mapped[float] = mapped_column(Float, default=1)
    dept: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ComplaintImage(Base):
    """客诉不良图片"""

    __tablename__ = "complaint_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)
    batch_id: Mapped[int] = mapped_column(Integer, index=True)
    rel_path: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(64), default="image/jpeg")
    sort_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class OpsAuditLog(Base):
    """运营写操作审计（不含产线扫码热路径）。"""

    __tablename__ = "ops_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class DipFirstArticleSession(Base):
    """DIP 首件对料会话（品质留档；不参与产线扫码卡控）。"""

    __tablename__ = "dip_first_article_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    line_key: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    model_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="in_progress", index=True)
    # in_progress / passed / cancelled
    operator: Mapped[str] = mapped_column(String(64), default="", index=True)
    board_image_rel: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    board_image_content_type: Mapped[str] = mapped_column(String(64), default="image/jpeg")
    remark: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DipFirstArticleLine(Base):
    """DIP 首件对料明细（快照自订单 DIP BOM）。"""

    __tablename__ = "dip_first_article_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    bom_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    seq: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), index=True)
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    spec: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    qty_per: Mapped[float] = mapped_column(Float, default=1)
    process: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    mount_type: Mapped[str] = mapped_column(String(16), default="DIP")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending / pass / fail
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recognized_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    verify_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # ocr / manual
    material_image_rel: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    verified_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sort_no: Mapped[int] = mapped_column(Integer, default=0)


class SmtIpqcSession(Base):
    """SMT 巡检查料会话（品质留档；不参与产线扫码卡控；无需总图）。"""

    __tablename__ = "smt_ipqc_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    line_key: Mapped[str] = mapped_column(String(128), index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    model_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="in_progress", index=True)
    # in_progress / passed / cancelled
    operator: Mapped[str] = mapped_column(String(64), default="", index=True)
    remark: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 巡检面：A / B（站位表 T→A、B→B）；空=无站位时的整单 BOM 抽检
    inspect_side: Mapped[str] = mapped_column(String(8), default="", index=True)


class SmtIpqcLine(Base):
    """SMT 巡检查料明细（快照自订单 SMT BOM，可附站位表信息）。"""

    __tablename__ = "smt_ipqc_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    bom_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    seq: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), index=True)
    material_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    spec: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    qty_per: Mapped[float] = mapped_column(Float, default=1)
    process: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    mount_type: Mapped[str] = mapped_column(String(16), default="SMT")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending / pass / fail
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recognized_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    verify_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    material_image_rel: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    verified_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sort_no: Mapped[int] = mapped_column(Integer, default=0)
    # 站位表快照（可空：无站位表时仅 BOM）
    station_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    feeder: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    station_material_spec: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    station_side: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    in_station_table: Mapped[bool] = mapped_column(Boolean, default=False)
    # 站位表文件名 _1/_2 → 1 号机 / 2 号机（巡检先核完 1 再核 2）
    station_machine_no: Mapped[int] = mapped_column(Integer, default=0)


class SmtStationFile(Base):
    """SMT 站位表文件（共享盘只读同步；不参与扫码卡控）。"""

    __tablename__ = "smt_station_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rel_path: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    folder_name: Mapped[str] = mapped_column(String(256), default="", index=True)
    filename: Mapped[str] = mapped_column(String(256), default="")
    model_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    side: Mapped[str] = mapped_column(String(16), default="", index=True)
    program_name: Mapped[str] = mapped_column(String(256), default="")
    machine_area: Mapped[str] = mapped_column(String(64), default="")
    file_mtime: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    source_path: Mapped[str] = mapped_column(String(512), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)


class SmtStationRow(Base):
    """SMT 站位表明细行。"""

    __tablename__ = "smt_station_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(Integer, index=True)
    model_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    purchase_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    side: Mapped[str] = mapped_column(String(16), default="")
    machine_id: Mapped[str] = mapped_column(String(64), default="")
    station_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    feeder: Mapped[str] = mapped_column(String(64), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    material_spec: Mapped[str] = mapped_column(String(256), default="", index=True)
    positions: Mapped[str] = mapped_column(String(1024), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    remark: Mapped[str] = mapped_column(String(256), default="")
    sort_no: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# —— 景立 ERP 阶段 0：主数据 / 仓库维度 / 单据编号 ——


class ErpCustomer(Base):
    """主数据·客户资料（销售域，非 SRM 配置）"""

    __tablename__ = "erp_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="", index=True)
    short_name: Mapped[str] = mapped_column(String(64), default="")
    contact: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    address: Mapped[str] = mapped_column(String(512), default="")
    tax_no: Mapped[str] = mapped_column(String(64), default="")
    remark: Mapped[str] = mapped_column(String(512), default="")
    # 三证图片：相对 /static 的路径，如 uploads/customers/1/business.jpg
    cert_business: Mapped[str] = mapped_column(String(512), default="")
    cert_org: Mapped[str] = mapped_column(String(512), default="")
    cert_tax: Mapped[str] = mapped_column(String(512), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ErpSupplier(Base):
    """主数据·供应商"""

    __tablename__ = "erp_suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="", index=True)
    short_name: Mapped[str] = mapped_column(String(64), default="")
    contact: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    address: Mapped[str] = mapped_column(String(512), default="")
    tax_no: Mapped[str] = mapped_column(String(64), default="")
    remark: Mapped[str] = mapped_column(String(512), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ErpWarehouse(Base):
    """仓库维度：良品仓 / 待检仓 / 退货仓等"""

    __tablename__ = "erp_warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    # good | inspect | return | wip | other
    wh_type: Mapped[str] = mapped_column(String(16), default="good", index=True)
    remark: Mapped[str] = mapped_column(String(256), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ErpStockProduct(Base):
    """库存产品 / 可售成品档案（备货与价格引用）"""

    __tablename__ = "erp_stock_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    spec: Mapped[str] = mapped_column(String(512), default="")
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    category: Mapped[str] = mapped_column(String(64), default="")
    can_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    safety_qty: Mapped[float] = mapped_column(Float, default=0)
    remark: Mapped[str] = mapped_column(String(512), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ErpPriceItem(Base):
    """价格管理：标准价 / 客户协议价"""

    __tablename__ = "erp_price_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # standard | customer
    price_type: Mapped[str] = mapped_column(String(16), default="standard", index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    effective_from: Mapped[str] = mapped_column(String(16), default="")
    effective_to: Mapped[str] = mapped_column(String(16), default="")
    remark: Mapped[str] = mapped_column(String(512), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocNumberSeq(Base):
    """单据编号序列：前缀 + 日期 + 流水"""

    __tablename__ = "doc_number_seqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16), default="")
    name: Mapped[str] = mapped_column(String(64), default="")
    date_fmt: Mapped[str] = mapped_column(String(16), default="%Y%m%d")
    seq_width: Mapped[int] = mapped_column(Integer, default=4)
    last_date: Mapped[str] = mapped_column(String(16), default="")
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# —— 景立 ERP 阶段 1：售前闭环 ——


class PresalesInquiry(Base):
    """询价单"""

    __tablename__ = "presales_inquiries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inquiry_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    contact: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    # draft / submitted / quoting / quoted / closed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PresalesInquiryLine(Base):
    """询价单行"""

    __tablename__ = "presales_inquiry_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inquiry_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    spec: Mapped[str] = mapped_column(String(512), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    remark: Mapped[str] = mapped_column(String(256), default="")


class SampleDesign(Base):
    """设计 / 打样任务（报价确认后）"""

    __tablename__ = "sample_designs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    design_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    inquiry_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    product_code: Mapped[str] = mapped_column(String(128), default="")
    product_name: Mapped[str] = mapped_column(String(256), default="")
    # draft / designing / sampling / confirmed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    owner: Mapped[str] = mapped_column(String(64), default="")
    remark: Mapped[str] = mapped_column(String(512), default="")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SampleOrder(Base):
    """打样订单"""

    __tablename__ = "sample_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    inquiry_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    design_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    product_code: Mapped[str] = mapped_column(String(128), default="")
    product_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    due_date: Mapped[str] = mapped_column(String(16), default="")
    # 打样属性：new_product / revise / competitive 等自由文本
    sample_attr: Mapped[str] = mapped_column(String(64), default="new_product")
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # draft / confirmed / in_progress / done / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ErpSalesOrder(Base):
    """销售订单头（报价转入 / 手工 / 打样转量产 / 旧 PO 导入）"""

    __tablename__ = "erp_sales_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    so_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # sales / sample_convert / srm_import
    order_kind: Mapped[str] = mapped_column(String(16), default="sales", index=True)
    inquiry_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    sample_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    external_po_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_srm_line_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    # 下推计划前是否强制行绑定工程 BOM（可配置）
    require_bom: Mapped[bool] = mapped_column(Boolean, default=False)
    # draft / confirmed / planning / executing / partial_shipped / done / closed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ErpSalesOrderLine(Base):
    """销售订单行"""

    __tablename__ = "erp_sales_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    so_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    spec: Mapped[str] = mapped_column(String(512), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    amount: Mapped[float] = mapped_column(Float, default=0)
    due_date: Mapped[str] = mapped_column(String(16), default="")
    shipped_qty: Mapped[float] = mapped_column(Float, default=0)
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    remark: Mapped[str] = mapped_column(String(256), default="")


class ErpStockOrder(Base):
    """备货单（无客户或内部备货；确认后可进 MRP）"""

    __tablename__ = "erp_stock_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # internal / customer（有客户时可选）
    stock_kind: Mapped[str] = mapped_column(String(16), default="internal", index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    warehouse_code: Mapped[str] = mapped_column(String(32), default="GOOD")
    # draft / confirmed / planning / done / closed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ErpStockOrderLine(Base):
    """备货单行"""

    __tablename__ = "erp_stock_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    remark: Mapped[str] = mapped_column(String(256), default="")


class SampleMail(Base):
    """样品邮寄 / 样品链接登记"""

    __tablename__ = "sample_mails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mail_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    inquiry_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    product_name: Mapped[str] = mapped_column(String(256), default="")
    # mail / link
    channel: Mapped[str] = mapped_column(String(16), default="mail")
    tracking_no: Mapped[str] = mapped_column(String(128), default="")
    link_url: Mapped[str] = mapped_column(String(512), default="")
    # draft / sent / received / closed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    sent_at: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SampleLoan(Base):
    """借样单（阶段8可还入/转销售）"""

    __tablename__ = "sample_loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loan_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    product_code: Mapped[str] = mapped_column(String(128), default="")
    product_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=1)
    # draft / lent / returned / converted / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    lent_at: Mapped[str] = mapped_column(String(32), default="")
    expect_return_at: Mapped[str] = mapped_column(String(32), default="")
    returned_at: Mapped[str] = mapped_column(String(32), default="")
    converted_so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# —— 阶段3：计划中枢 ——


class CustomerForecast(Base):
    """客户预告头（需求输入）"""

    __tablename__ = "customer_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    # draft / confirmed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustomerForecastLine(Base):
    __tablename__ = "customer_forecast_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    remark: Mapped[str] = mapped_column(String(256), default="")


class PurchaseForecast(Base):
    """采购预告头（采购侧提前量，可选参与 MRP）"""

    __tablename__ = "purchase_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    # draft / confirmed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchaseForecastLine(Base):
    __tablename__ = "purchase_forecast_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")


class MrpRun(Base):
    """一次 MRP 运算记录"""

    __tablename__ = "mrp_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # draft / generated / void
    status: Mapped[str] = mapped_column(String(24), default="generated", index=True)
    source_so_ids: Mapped[str] = mapped_column(Text, default="")  # 逗号分隔
    source_stock_ids: Mapped[str] = mapped_column(Text, default="")
    demand_count: Mapped[int] = mapped_column(Integer, default=0)
    purchase_plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    production_plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    outsource_plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchasePlan(Base):
    __tablename__ = "purchase_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    mrp_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # draft / confirmed / released / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchasePlanLine(Base):
    __tablename__ = "purchase_plan_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    source_type: Mapped[str] = mapped_column(String(24), default="")  # sales / stock / forecast
    source_no: Mapped[str] = mapped_column(String(64), default="")
    source_so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remark: Mapped[str] = mapped_column(String(256), default="")


class ProductionPlan(Base):
    __tablename__ = "production_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    mrp_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProductionPlanLine(Base):
    __tablename__ = "production_plan_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(24), default="")
    source_no: Mapped[str] = mapped_column(String(64), default="")
    source_so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remark: Mapped[str] = mapped_column(String(256), default="")


class OutsourcePlan(Base):
    __tablename__ = "outsource_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    mrp_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutsourcePlanLine(Base):
    __tablename__ = "outsource_plan_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    process: Mapped[str] = mapped_column(String(128), default="")
    source_type: Mapped[str] = mapped_column(String(24), default="")
    source_no: Mapped[str] = mapped_column(String(64), default="")
    source_so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remark: Mapped[str] = mapped_column(String(256), default="")


# —— 阶段4：采购执行链 ——


class PurchaseOrder(Base):
    """采购单"""

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    source_plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source_plan_no: Mapped[str] = mapped_column(String(32), default="")
    stock_owner: Mapped[str] = mapped_column(String(64), default="internal", index=True)
    # draft / confirmed / partial / closed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    due_date: Mapped[str] = mapped_column(String(16), default="")
    arrived_qty: Mapped[float] = mapped_column(Float, default=0)
    pass_qty: Mapped[float] = mapped_column(Float, default=0)
    fail_qty: Mapped[float] = mapped_column(Float, default=0)
    received_qty: Mapped[float] = mapped_column(Float, default=0)
    returned_qty: Mapped[float] = mapped_column(Float, default=0)
    remark: Mapped[str] = mapped_column(String(256), default="")


class PurchaseArrivalBarcode(Base):
    __tablename__ = "purchase_arrival_barcodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_id: Mapped[int] = mapped_column(Integer, index=True)
    po_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    barcode: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    qty: Mapped[float] = mapped_column(Float, default=1)
    scanned_by: Mapped[str] = mapped_column(String(64), default="")
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    remark: Mapped[str] = mapped_column(String(256), default="")


class PurchaseInspect(Base):
    __tablename__ = "purchase_inspects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspect_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    po_id: Mapped[int] = mapped_column(Integer, index=True)
    po_no: Mapped[str] = mapped_column(String(32), default="")
    warehouse_code: Mapped[str] = mapped_column(String(32), default="INSPECT")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    result: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    judged_by: Mapped[str] = mapped_column(String(64), default="")
    judged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchaseInspectLine(Base):
    __tablename__ = "purchase_inspect_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspect_id: Mapped[int] = mapped_column(Integer, index=True)
    po_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    pass_qty: Mapped[float] = mapped_column(Float, default=0)
    fail_qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    remark: Mapped[str] = mapped_column(String(256), default="")


class PurchaseReceipt(Base):
    __tablename__ = "purchase_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    po_id: Mapped[int] = mapped_column(Integer, index=True)
    po_no: Mapped[str] = mapped_column(String(32), default="")
    inspect_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), default="GOOD")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchaseReceiptLine(Base):
    __tablename__ = "purchase_receipt_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(Integer, index=True)
    po_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    remark: Mapped[str] = mapped_column(String(256), default="")


class PurchaseReturn(Base):
    __tablename__ = "purchase_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    po_id: Mapped[int] = mapped_column(Integer, index=True)
    po_no: Mapped[str] = mapped_column(String(32), default="")
    inspect_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), default="RETURN")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchaseReturnLine(Base):
    __tablename__ = "purchase_return_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(Integer, index=True)
    po_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    remark: Mapped[str] = mapped_column(String(256), default="")


class ApPayableStub(Base):
    """应付台账（采购/委外入库等过账挂钩；阶段9核销）"""

    __tablename__ = "ap_payable_stubs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(32), default="purchase_receipt", index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    source_no: Mapped[str] = mapped_column(String(32), default="")
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    settled_amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# —— 阶段5：生产执行链 ——


class ProductionOrder(Base):
    """生产单"""

    __tablename__ = "production_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mo_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    source_plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source_plan_no: Mapped[str] = mapped_column(String(32), default="")
    source_so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source_so_no: Mapped[str] = mapped_column(String(32), default="")
    bom_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    stock_owner: Mapped[str] = mapped_column(String(64), default="internal", index=True)
    issued_sets: Mapped[float] = mapped_column(Float, default=0)
    qa_pass_qty: Mapped[float] = mapped_column(Float, default=0)
    qa_fail_qty: Mapped[float] = mapped_column(Float, default=0)
    fg_qty: Mapped[float] = mapped_column(Float, default=0)
    # draft / released / issuing / in_process / qa / fg_done / closed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProductionBarcode(Base):
    __tablename__ = "production_barcodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mo_id: Mapped[int] = mapped_column(Integer, index=True)
    barcode: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scanned_by: Mapped[str] = mapped_column(String(64), default="")
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    remark: Mapped[str] = mapped_column(String(256), default="")


class ProdMaterialDoc(Base):
    """生产领料/补料/退料单头"""

    __tablename__ = "prod_material_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # issue / supplement / return
    kind: Mapped[str] = mapped_column(String(16), default="issue", index=True)
    mo_id: Mapped[int] = mapped_column(Integer, index=True)
    mo_no: Mapped[str] = mapped_column(String(32), default="")
    # draft / confirmed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    confirmed_by: Mapped[str] = mapped_column(String(64), default="")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProdMaterialLine(Base):
    __tablename__ = "prod_material_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(Integer, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    remark: Mapped[str] = mapped_column(String(256), default="")


class ProductionQa(Base):
    __tablename__ = "production_qas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    qa_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    mo_id: Mapped[int] = mapped_column(Integer, index=True)
    mo_no: Mapped[str] = mapped_column(String(32), default="")
    # draft / judged / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    # pending / pass / fail / partial
    result: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    qty: Mapped[float] = mapped_column(Float, default=0)
    pass_qty: Mapped[float] = mapped_column(Float, default=0)
    fail_qty: Mapped[float] = mapped_column(Float, default=0)
    judged_by: Mapped[str] = mapped_column(String(64), default="")
    judged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FgReceipt(Base):
    __tablename__ = "fg_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    mo_id: Mapped[int] = mapped_column(Integer, index=True)
    mo_no: Mapped[str] = mapped_column(String(32), default="")
    qa_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    warehouse_code: Mapped[str] = mapped_column(String(32), default="GOOD")
    # 入库直接出库开关（阶段7生成出库草稿）
    direct_outbound: Mapped[bool] = mapped_column(Boolean, default=False)
    # draft / posted / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# —— 阶段6：委外执行链 ——


class OutsourceOrder(Base):
    """委外单"""

    __tablename__ = "outsource_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ww_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    process: Mapped[str] = mapped_column(String(128), default="")
    source_plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source_plan_no: Mapped[str] = mapped_column(String(32), default="")
    stock_owner: Mapped[str] = mapped_column(String(64), default="internal", index=True)
    # draft / confirmed / shipped / partial / closed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutsourceOrderLine(Base):
    __tablename__ = "outsource_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ww_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    process: Mapped[str] = mapped_column(String(128), default="")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    shipped_qty: Mapped[float] = mapped_column(Float, default=0)
    pass_qty: Mapped[float] = mapped_column(Float, default=0)
    fail_qty: Mapped[float] = mapped_column(Float, default=0)
    received_qty: Mapped[float] = mapped_column(Float, default=0)
    returned_qty: Mapped[float] = mapped_column(Float, default=0)
    remark: Mapped[str] = mapped_column(String(256), default="")


class OutsourceShipDoc(Base):
    """发料给委外（扣内部库存，记在途语义）"""

    __tablename__ = "outsource_ship_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ship_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    ww_id: Mapped[int] = mapped_column(Integer, index=True)
    ww_no: Mapped[str] = mapped_column(String(32), default="")
    # draft / confirmed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutsourceShipLine(Base):
    __tablename__ = "outsource_ship_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(Integer, index=True)
    ww_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")


class OutsourceBarcode(Base):
    __tablename__ = "outsource_barcodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ww_id: Mapped[int] = mapped_column(Integer, index=True)
    barcode: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    qty: Mapped[float] = mapped_column(Float, default=1)
    scanned_by: Mapped[str] = mapped_column(String(64), default="")
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutsourceInspect(Base):
    __tablename__ = "outsource_inspects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspect_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    ww_id: Mapped[int] = mapped_column(Integer, index=True)
    ww_no: Mapped[str] = mapped_column(String(32), default="")
    warehouse_code: Mapped[str] = mapped_column(String(32), default="INSPECT")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    result: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    judged_by: Mapped[str] = mapped_column(String(64), default="")
    judged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutsourceInspectLine(Base):
    __tablename__ = "outsource_inspect_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspect_id: Mapped[int] = mapped_column(Integer, index=True)
    ww_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    pass_qty: Mapped[float] = mapped_column(Float, default=0)
    fail_qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")


class OutsourceReceipt(Base):
    """委托入库单（合格）"""

    __tablename__ = "outsource_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    ww_id: Mapped[int] = mapped_column(Integer, index=True)
    ww_no: Mapped[str] = mapped_column(String(32), default="")
    inspect_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), default="GOOD")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutsourceReceiptLine(Base):
    __tablename__ = "outsource_receipt_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(Integer, index=True)
    ww_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)


class OutsourceReturn(Base):
    __tablename__ = "outsource_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    ww_id: Mapped[int] = mapped_column(Integer, index=True)
    ww_no: Mapped[str] = mapped_column(String(32), default="")
    inspect_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), default="RETURN")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutsourceReturnLine(Base):
    __tablename__ = "outsource_return_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(Integer, index=True)
    ww_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")


# —— 阶段7：销售出货 ——


class SalesIssue(Base):
    """销售出库单（按销售订单行扣成品）"""

    __tablename__ = "sales_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    so_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    stock_owner: Mapped[str] = mapped_column(String(64), default="internal", index=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), default="GOOD")
    # draft / posted / delivered / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    source_fg_receipt_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalesIssueLine(Base):
    __tablename__ = "sales_issue_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(Integer, index=True)
    so_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    packed_qty: Mapped[float] = mapped_column(Float, default=0)


class SalesIssueBarcode(Base):
    """出库打包条码（MVP：挂出库单，可走现有箱标签页）"""

    __tablename__ = "sales_issue_barcodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(Integer, index=True)
    barcode: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    qty: Mapped[float] = mapped_column(Float, default=1)
    box_no: Mapped[str] = mapped_column(String(64), default="")
    scanned_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeliveryNote(Base):
    """发货单（业务单据）"""

    __tablename__ = "delivery_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    issue_id: Mapped[int] = mapped_column(Integer, index=True)
    issue_no: Mapped[str] = mapped_column(String(32), default="")
    so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    so_no: Mapped[str] = mapped_column(String(32), default="")
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    # draft / confirmed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    ship_date: Mapped[str] = mapped_column(String(16), default="")
    carrier: Mapped[str] = mapped_column(String(64), default="")
    tracking_no: Mapped[str] = mapped_column(String(64), default="")
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    confirmed_by: Mapped[str] = mapped_column(String(64), default="")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeliveryNoteLine(Base):
    __tablename__ = "delivery_note_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[int] = mapped_column(Integer, index=True)
    issue_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    so_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    material_code: Mapped[str] = mapped_column(String(128), default="")
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)


class ArReceivableStub(Base):
    """应收台账（发货确认等挂钩；阶段9核销）"""

    __tablename__ = "ar_receivable_stubs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(32), default="delivery_note", index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    source_no: Mapped[str] = mapped_column(String(32), default="")
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    settled_amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# —— 阶段8：售后与仓储辅助 ——


class ComplaintDoc(Base):
    """业务投诉单（与品质 Excel 客诉看板分离）"""

    __tablename__ = "complaint_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    complaint_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    so_no: Mapped[str] = mapped_column(String(32), default="")
    delivery_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    delivery_no: Mapped[str] = mapped_column(String(32), default="")
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(String(1024), default="")
    # draft / open / closed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalesReturn(Base):
    """销售出库退货单"""

    __tablename__ = "sales_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    so_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    so_no: Mapped[str] = mapped_column(String(32), default="")
    issue_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    issue_no: Mapped[str] = mapped_column(String(32), default="")
    delivery_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    delivery_no: Mapped[str] = mapped_column(String(32), default="")
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    stock_owner: Mapped[str] = mapped_column(String(64), default="internal", index=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), default="RETURN")
    # draft / confirmed / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    # none / reissue / replenish
    branch: Mapped[str] = mapped_column(String(24), default="none", index=True)
    reissue_issue_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reissue_delivery_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    replenish_mo_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    confirmed_by: Mapped[str] = mapped_column(String(64), default="")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalesReturnLine(Base):
    __tablename__ = "sales_return_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(Integer, index=True)
    so_line_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")
    unit_price: Mapped[float] = mapped_column(Float, default=0)


class StocktakeDoc(Base):
    """库存盘点单"""

    __tablename__ = "stocktake_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stocktake_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    stock_owner: Mapped[str] = mapped_column(String(64), default="internal", index=True)
    # draft / posted / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StocktakeLine(Base):
    __tablename__ = "stocktake_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stocktake_id: Mapped[int] = mapped_column(Integer, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    book_qty: Mapped[float] = mapped_column(Float, default=0)
    count_qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")


class TransferDoc(Base):
    """库存调拨 / 库存出库（kind=transfer|out）"""

    __tablename__ = "transfer_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # transfer / out
    kind: Mapped[str] = mapped_column(String(16), default="transfer", index=True)
    from_owner: Mapped[str] = mapped_column(String(64), default="internal", index=True)
    to_owner: Mapped[str] = mapped_column(String(64), default="", index=True)
    # draft / posted / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TransferLine(Base):
    __tablename__ = "transfer_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transfer_id: Mapped[int] = mapped_column(Integer, index=True)
    material_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    material_name: Mapped[str] = mapped_column(String(256), default="")
    qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="PCS")


# —— 阶段9：财务应收应付与出纳 ——


class CashAccount(Base):
    """出纳账户"""

    __tablename__ = "cash_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    # cash / bank
    kind: Mapped[str] = mapped_column(String(16), default="bank", index=True)
    opening_balance: Mapped[float] = mapped_column(Float, default=0)
    balance: Mapped[float] = mapped_column(Float, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CashLedger(Base):
    """出纳流水"""

    __tablename__ = "cash_ledgers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    account_code: Mapped[str] = mapped_column(String(32), default="")
    # payment / receipt / manual / reimbursement / transfer_out / transfer_in
    movement_type: Mapped[str] = mapped_column(String(24), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0)  # 正=收入，负=支出
    balance_after: Mapped[float] = mapped_column(Float, default=0)
    ref_type: Mapped[str] = mapped_column(String(32), default="")
    ref_no: Mapped[str] = mapped_column(String(32), default="")
    counterparty: Mapped[str] = mapped_column(String(128), default="")
    remark: Mapped[str] = mapped_column(String(512), default="")
    operator: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PaymentRequest(Base):
    """付款申请单（需审批）"""

    __tablename__ = "payment_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    # draft / submitted / approved / rejected / paid / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    approved_by: Mapped[str] = mapped_column(String(64), default="")
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    payment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaymentRequestLine(Base):
    __tablename__ = "payment_request_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(Integer, index=True)
    ap_id: Mapped[int] = mapped_column(Integer, index=True)
    ap_source_no: Mapped[str] = mapped_column(String(32), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)


class PaymentDoc(Base):
    """付款单"""

    __tablename__ = "payment_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    request_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    request_no: Mapped[str] = mapped_column(String(32), default="")
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    # draft / posted / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReceiptDoc(Base):
    """收款单"""

    __tablename__ = "receipt_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    # draft / posted / void
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReceiptDocLine(Base):
    __tablename__ = "receipt_doc_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(Integer, index=True)
    ar_id: Mapped[int] = mapped_column(Integer, index=True)
    ar_source_no: Mapped[str] = mapped_column(String(32), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)


class InvoiceReg(Base):
    """发票登记（简版）"""

    __tablename__ = "invoice_regs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    # in / out
    direction: Mapped[str] = mapped_column(String(8), default="in", index=True)
    counterparty: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    related_doc_no: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinBill(Base):
    """应收/应付票据（简版）"""

    __tablename__ = "fin_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    # receivable / payable
    bill_kind: Mapped[str] = mapped_column(String(16), default="receivable", index=True)
    counterparty: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    due_date: Mapped[str] = mapped_column(String(16), default="")
    # draft / held / settled / void
    status: Mapped[str] = mapped_column(String(24), default="held", index=True)
    remark: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# —— 阶段10：总账与月末 ——


class GlAccount(Base):
    """会计科目"""

    __tablename__ = "gl_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    # asset / liability / equity / cost / income / expense
    category: Mapped[str] = mapped_column(String(16), default="asset", index=True)
    # debit / credit 余额方向
    balance_dir: Mapped[str] = mapped_column(String(8), default="debit")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    balance: Mapped[float] = mapped_column(Float, default=0)
    remark: Mapped[str] = mapped_column(String(256), default="")


class GlPeriod(Base):
    """会计期间"""

    __tablename__ = "gl_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(8), unique=True, index=True)  # YYYYMM
    # open / closing / closed
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(256), default="")


class GlVoucher(Base):
    """记账凭证"""

    __tablename__ = "gl_vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voucher_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    period: Mapped[str] = mapped_column(String(8), default="", index=True)
    # draft / reviewed / posted / void
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source_no: Mapped[str] = mapped_column(String(32), default="")
    summary: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    posted_by: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GlVoucherLine(Base):
    __tablename__ = "gl_voucher_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    account_code: Mapped[str] = mapped_column(String(32), default="", index=True)
    account_name: Mapped[str] = mapped_column(String(128), default="")
    debit: Mapped[float] = mapped_column(Float, default=0)
    credit: Mapped[float] = mapped_column(Float, default=0)
    summary: Mapped[str] = mapped_column(String(256), default="")


class FixedAsset(Base):
    """固定资产（简版）"""

    __tablename__ = "fixed_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    original_value: Mapped[float] = mapped_column(Float, default=0)
    residual_rate: Mapped[float] = mapped_column(Float, default=0.05)
    months: Mapped[int] = mapped_column(Integer, default=36)
    accumulated_depr: Mapped[float] = mapped_column(Float, default=0)
    # active / disposed
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    remark: Mapped[str] = mapped_column(String(256), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
