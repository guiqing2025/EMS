from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class SrmConfigUpdate(BaseModel):
    sync_interval_minutes: Optional[int] = Field(None, ge=1, le=1440)
    auto_sync_enabled: Optional[bool] = None
    login_username: Optional[str] = None
    login_password: Optional[str] = None
    dashboard_password: Optional[str] = None
    customers: Optional[list] = None


class CustomerOut(BaseModel):
    id: str
    name: str
    api_type: str
    srm_base_url: str
    api_path: str = ""
    login_name: str
    password: str = "******"
    enabled: bool = True


class SrmConfigOut(BaseModel):
    sync_interval_minutes: int
    auto_sync_enabled: bool
    login_username: str
    login_password: str = "******"
    dashboard_password: str = "******"
    customers: List[CustomerOut] = []


class SystemLogin(BaseModel):
    username: str
    password: str


class AuthStatus(BaseModel):
    authenticated: bool
    username: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    display_name: Optional[str] = None
    must_change_password: bool = False
    module_pages: Optional[list[str]] = None
    module_pages_mode: Optional[str] = None
    allowed_scan_stations: Optional[list[str]] = None


class LoginResponse(BaseModel):
    token: str
    message: str = "登录成功"
    username: str
    role: str
    department: Optional[str] = None
    display_name: str = ""
    must_change_password: bool = False
    module_pages: Optional[list[str]] = None
    module_pages_mode: Optional[str] = None
    allowed_scan_stations: Optional[list[str]] = None


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=64)


class DashboardLogin(BaseModel):
    password: str


class DashboardAuthStatus(BaseModel):
    locked: bool
    authenticated: bool


class NewOrderItem(BaseModel):
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    purchase_no: str
    purchase_seq: Optional[str] = None
    purchase_phase_seq: Optional[str] = None
    product_goods_no: Optional[str] = None
    product_goods_name: Optional[str] = None
    batch_pur_qty: float = 0


class KittingAlertItem(BaseModel):
    line_key: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    purchase_no: str
    product_goods_no: Optional[str] = None
    product_goods_name: Optional[str] = None
    collected_sets_qty: float = 0
    batch_pur_qty: float = 0
    kitted_at: Optional[datetime] = None


class SyncResult(BaseModel):
    status: str
    message: str
    orders_synced: int
    new_orders_count: int = 0
    kitting_alert_count: int = 0
    sync_log_id: Optional[int] = None
    new_orders: List[NewOrderItem] = []
    kitting_alerts: List[KittingAlertItem] = []


class SyncNotificationOut(BaseModel):
    sync_log_id: int
    finished_at: Optional[datetime]
    new_orders_count: int = 0
    orders: List[NewOrderItem] = []
    kitting_alert_count: int = 0
    kitting_alerts: List[KittingAlertItem] = []


class SyncLogOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    message: Optional[str]
    orders_synced: int
    new_orders_count: int = 0
    kitting_alert_count: int = 0

    class Config:
        from_attributes = True


class OrderRemarkUpdate(BaseModel):
    remark: Optional[str] = Field(None, max_length=256)


class OrderDeleteIn(BaseModel):
    password: str = Field(..., description="删除订单操作密码")


class ManualOrderIn(BaseModel):
    customer_name: str
    purchase_no: str
    purchase_seq: str = "1"
    purchase_phase_seq: str = "1"
    product_goods_no: Optional[str] = None
    product_goods_name: Optional[str] = None
    product_spec: Optional[str] = None
    batch_pur_qty: float
    purchase_date: Optional[str] = None
    expect_arrival_date: Optional[str] = None
    remark: Optional[str] = None


class SrmOrderOut(BaseModel):
    id: int
    line_key: str
    purchase_no: str
    purchase_seq: Optional[str] = None
    purchase_phase_seq: Optional[str] = None
    workorder_no: Optional[str]
    product_goods_no: Optional[str]
    product_goods_name: Optional[str]
    product_spec: Optional[str]
    batch_pur_qty: float = 0
    delivery_qty: float = 0
    receive_qty: float = 0
    un_delivery_qty: float = 0
    un_receive_qty: float = 0
    output_qty: float
    collected_sets_qty: float
    doc_date: Optional[str]
    purchase_date: Optional[str]
    expect_arrival_date: Optional[str] = None
    order_type_name: Optional[str]
    tax_amount: float = 0
    no_tax_amount: float = 0
    sum_tax_amount: float
    sum_no_tax_amount: float
    srm_status: Optional[str] = None
    srm_status_name: Optional[str] = None
    is_completed: bool
    customer_id: str = "feilisi"
    data_source: str = "订单跟踪"
    customer_name: Optional[str]
    remark: Optional[str] = None
    bom_model_id: Optional[int] = None
    material_status: Optional[str] = None
    customer_kit_status: Optional[str] = None
    customer_kit_status_label: Optional[str] = None
    customer_kitted_at: Optional[datetime] = None
    tooling_registered_count: int = 0
    tooling_complete: bool = False
    tooling_status: str = "unknown"
    tooling_status_label: str = "—"
    biz_kind: str = "processing"
    biz_kind_label: str = "加工订单"
    synced_at: datetime
    pending_ship_qty: int = 0
    shipped_local_qty: int = 0
    # 本订单今日已确认发货数（Shipment.ship_date=今天且已审核）
    shipped_today_qty: int = 0
    # 已点发货待审核（未计入已发）
    awaiting_ship_qty: int = 0
    # 未入库 = 未收 − 入库（入库=待发+已发）；字段名沿用 stock_balance_qty
    stock_balance_qty: int = 0
    aoi_test_qty: int = 0
    pre_oven_aoi_qty: int = 0
    plugin_qty: int = 0
    post_solder_qty: int = 0
    ict_test_qty: int = 0
    coating_qty: int = 0
    is_controlled: bool = False
    control_nos: list[str] = []
    control_draft_nos: list[str] = []
    has_control: bool = False
    is_new_order: bool = False  # 下单日期在近 3 个自然日内
    # 计划排产：按订单行（line_key）是否已进入生产主计划
    in_plan: bool = False
    plan_status: str = "pending"  # pending | done
    plan_status_label: str = "待转计划"

    class Config:
        from_attributes = True


class PackingSearchOrderOut(BaseModel):
    line_key: str
    purchase_no: str
    customer_name: Optional[str] = None
    product_goods_no: Optional[str] = None
    product_goods_name: Optional[str] = None
    batch_pur_qty: float = 0
    pending_ship_qty: int = 0


class PackingOrderOut(BaseModel):
    line_key: str
    purchase_no: str
    purchase_seq: Optional[str] = None
    purchase_phase_seq: Optional[str] = None
    customer_name: Optional[str] = None
    remark: Optional[str] = None
    product_goods_no: Optional[str] = None
    product_goods_name: Optional[str] = None
    product_spec: Optional[str] = None
    batch_pur_qty: float = 0
    un_delivery_qty: float = 0
    expect_arrival_date: Optional[str] = None
    pending_ship_qty: int = 0
    shipped_local_qty: int = 0
    remain_scan_qty: float = 0
    is_completed: bool = False


class PackingScanIn(BaseModel):
    line_key: str
    barcode: str
    code_type: Optional[str] = None
    operator: Optional[str] = None
    # 多人同时入箱：指定扫入哪一箱（不传则挂到该单最新开箱）
    box_id: Optional[int] = None


class PackingScanOut(BaseModel):
    id: int
    barcode: str
    code_type: str
    pending_ship_qty: int
    shipped_local_qty: int
    order_qty: float
    message: str
    # 镭雕纠正后的实际入库行（前端可同步显示机型）
    line_key: Optional[str] = None
    purchase_no: Optional[str] = None
    product_goods_no: Optional[str] = None
    box_id: Optional[int] = None
    box_no: Optional[str] = None
    box_qty: Optional[int] = None
    box_qty_target: Optional[int] = None
    box_sealed: Optional[bool] = False


class PackBoxOpenIn(BaseModel):
    line_key: str
    qty_target: int = 60
    # True=即使已有装箱中的箱也再开一箱（多人并行「新增箱」）
    force_new: bool = False


class PackBoxSealIn(BaseModel):
    box_id: int


class PackBoxResumeIn(BaseModel):
    box_id: int


class PackBoxAbsorbIn(BaseModel):
    box_id: int


class PackScanDeleteIn(BaseModel):
    barcode: str


class ShipmentCreateIn(BaseModel):
    line_key: str
    ship_date: Optional[str] = None
    box_count: int = 1
    qty_per_box: int = 1
    qty: Optional[int] = None  # 出货数；空则全部待出
    logistics: Optional[str] = None
    remark: Optional[str] = None
    operator: Optional[str] = None


class PackSpecIn(BaseModel):
    qty: int
    qty_per_box: int
    box_count: Optional[int] = None


class ShipmentMultiLineIn(BaseModel):
    line_key: str
    qty: int
    box_count: int = 1
    qty_per_box: int = 1
    box_ids: list[int] = []
    pack_specs: list[PackSpecIn] = []
    remainder_qty: int = 0


class ShipmentMultiCreateIn(BaseModel):
    customer_id: str
    ship_date: Optional[str] = None
    logistics: Optional[str] = None
    remark: Optional[str] = None
    operator: Optional[str] = None
    lines: list[ShipmentMultiLineIn]


class ShipmentMultiOut(BaseModel):
    slip_id: int
    slip_no: str
    customer_id: str = ""
    customer_name: str = ""
    ship_date: str
    logistics: str = ""
    remark: str = ""
    operator: str = ""
    line_count: int = 0
    total_qty: int = 0
    shipment_ids: list[int] = []
    approval_status: str = "pending"
    message: str = ""


class ShipmentOut(BaseModel):
    id: int
    shipment_no: str
    line_key: str
    purchase_no: str
    customer_name: Optional[str] = None
    product_goods_no: Optional[str] = None
    product_goods_name: Optional[str] = None
    qty: int
    ship_date: str
    box_count: int
    qty_per_box: Optional[int] = 1
    logistics: Optional[str] = None
    remark: Optional[str] = None
    operator: Optional[str] = None
    created_at: datetime
    slip_id: Optional[int] = None
    approval_status: Optional[str] = "approved"
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ShipmentApproveIn(BaseModel):
    shipment_id: Optional[int] = None
    slip_id: Optional[int] = None


class ShipmentApproveOut(BaseModel):
    approved_count: int
    shipment_ids: list[int] = []
    total_qty: int = 0
    approver: str = ""
    message: str = ""


class ShipmentRevokeIn(BaseModel):
    line_key: str = ""
    shipment_id: Optional[int] = None


class ShipmentRevokeOut(BaseModel):
    id: int
    shipment_no: str
    line_key: str
    purchase_no: str
    qty: int
    restored_qty: int
    ship_date: str
    message: str = "已撤销出库"


class ShipmentBackfillIn(BaseModel):
    """历史发货补录：追加数量计入累计已发，不计入今日发（不影响生产扫码）。"""

    line_key: str
    add_qty: Optional[int] = None
    target_shipped_qty: Optional[int] = None  # 兼容旧：补到目标累计
    ship_date: Optional[str] = None
    remark: Optional[str] = None
    operator: Optional[str] = None


class ShipmentBackfillOut(BaseModel):
    shipment_id: int
    shipment_no: str
    line_key: str
    purchase_no: str = ""
    added_qty: int
    target_shipped_qty: int
    shipped_qty: int
    pending_qty: int
    unshipped_qty: int
    order_qty: int
    ship_date: str
    message: str = ""


class DashboardStats(BaseModel):
    total_orders: int
    total_order_headers: int
    incomplete_orders: int
    completed_orders: int
    total_tax_amount: float
    reconciliation_count: int = 0
    last_sync_at: Optional[datetime]
    sync_status: Optional[str]
    srm_live_total: Optional[int] = None
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    data_source: str = "SRM · 订单跟踪 + 对账明细"
    sync_note: Optional[str] = None
    fee_source: str = "订单行含税金额"


class ReceiveBoardModel(BaseModel):
    model_code: str
    model_name: str = ""
    last_month_qty: float = 0
    this_month_qty: float = 0
    last_month_amount: float = 0
    this_month_amount: float = 0


class ReceiveBoardCustomer(BaseModel):
    customer_id: str
    customer_name: str
    last_month_total: float = 0
    this_month_total: float = 0
    last_month_amount: float = 0
    this_month_amount: float = 0
    this_month_order_qty: float = 0
    this_month_order_amount: float = 0
    models: List[ReceiveBoardModel] = []


class ShipFeedItem(BaseModel):
    model_code: str
    model_name: str = ""
    qty: float = 0


class ShipFeedGroup(BaseModel):
    customer_id: str
    customer_name: str
    items: List[ShipFeedItem] = []
    total_qty: float = 0


class ShipFeedOut(BaseModel):
    feed_date: str
    is_today: bool = True
    last_synced_at: Optional[str] = None
    groups: List[ShipFeedGroup] = []


class ReceiveBoardMonthlyPoint(BaseModel):
    month: str
    qty: float = 0
    amount: float = 0


class ReceiveBoardMonthlyCustomer(BaseModel):
    customer_id: str
    customer_name: str
    series: List[ReceiveBoardMonthlyPoint] = []


class ReceiveBoardMonthly(BaseModel):
    history_start: str
    months: List[str] = []
    customers: List[ReceiveBoardMonthlyCustomer] = []


class ReceiveBoardOut(BaseModel):
    as_of: str
    this_month: str
    last_month: str
    note: str = ""
    customers: List[ReceiveBoardCustomer] = []
    feed: Optional[ShipFeedOut] = None
    monthly: Optional[ReceiveBoardMonthly] = None


class WarehouseMaterialOut(BaseModel):
    id: int
    customer_id: str
    customer_name: str
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    unit: str = "PCS"
    qty: float = 0
    locked_qty: float = 0
    available_qty: float = 0
    group_available_qty: float = 0
    stock_primary_code: str = ""
    substitute_codes: List[str] = []
    is_substitute_alias: bool = False
    excel_count_qty: Optional[float] = None
    excel_in_qty: Optional[float] = None
    excel_demand_qty: Optional[float] = None
    excel_synced_at: Optional[datetime] = None
    remark: Optional[str] = None
    last_inbound_at: Optional[datetime] = None
    last_inbound_qty: Optional[float] = None
    last_inbound_source: Optional[str] = None
    last_inbound_source_name: Optional[str] = None
    last_op_at: Optional[datetime] = None
    last_op_type: Optional[str] = None
    last_op_type_name: Optional[str] = None
    last_op_giver: Optional[str] = None
    last_op_receiver: Optional[str] = None
    last_op_operator: Optional[str] = None

    class Config:
        from_attributes = True


class WarehouseMaterialEnsureIn(BaseModel):
    """BOM 缺料号点开明细时：无库存账则自动建零库存档案。"""

    customer_id: str
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = "PCS"


class WarehouseBomModelCandidateOut(BaseModel):
    id: int
    model_code: str
    model_name: Optional[str] = None
    customer_id: str
    customer_name: str
    line_count: int = 0
    purchase_no: str = ""
    order_qty: float = 0
    bom_status: str = "pending"


class WarehouseOpenOrderOut(BaseModel):
    """物料明细：客户在制订单摘要（齐料状态读库，不现场重算）。"""

    line_key: str = ""
    purchase_no: str = ""
    model_code: str = ""
    model_name: Optional[str] = None
    customer_id: str = ""
    customer_name: str = ""
    order_qty: float = 0
    bom_model_id: Optional[int] = None
    bom_status: str = "pending"
    line_count: int = 0
    material_status: str = "unknown"
    material_status_label: str = "—"
    customer_kit_status: str = "na"
    customer_kit_status_label: str = "—"


class FinishedGoodsRowOut(BaseModel):
    """成品发货行。未发完 = 订单数 − 已发货（内部口径）。"""

    line_key: str
    customer_id: str = ""
    customer_name: str = ""
    purchase_no: str = ""
    model_code: str = ""
    model_name: str = ""
    product_spec: str = ""
    order_qty: float = 0
    receive_qty: float = 0
    inbound_qty: int = 0
    pending_qty: int = 0
    shipped_qty: int = 0
    unshipped_qty: int = 0
    balance_qty: float = 0
    status_label: str = ""
    expect_arrival_date: str = ""
    is_completed: bool = False


class WarehouseModelMaterialLineOut(BaseModel):
    material_id: Optional[int] = None
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    unit: str = "PCS"
    qty_per: float = 1
    position: Optional[str] = None
    required_qty: float = 0
    stock_qty: float = 0
    available_qty: float = 0
    shortage_qty: float = 0
    status: str = "unknown"
    substitute_codes: List[str] = []
    excel_count_qty: Optional[float] = None
    excel_in_qty: Optional[float] = None
    excel_demand_qty: Optional[float] = None
    stock_primary_code: str = ""


class WarehouseModelMaterialsOut(BaseModel):
    matched: bool = False
    bom_model_id: Optional[int] = None
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    purchase_no: Optional[str] = None
    order_qty: float = 1
    material_status: str = "unknown"
    ready_count: int = 0
    partial_count: int = 0
    shortage_count: int = 0
    total_lines: int = 0
    message: Optional[str] = None
    candidates: List[WarehouseBomModelCandidateOut] = []
    lines: List[WarehouseModelMaterialLineOut] = []


class StockInRecordOut(BaseModel):
    id: int
    receipt_no: str
    material_id: int
    customer_id: str
    customer_name: str
    material_code: str
    material_name: Optional[str] = None
    qty: float
    source: str
    source_name: str = ""
    operator: Optional[str] = None
    giver: Optional[str] = None
    receiver: Optional[str] = None
    remark: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class StockInIn(BaseModel):
    material_id: int
    qty: float = Field(gt=0)
    remark: Optional[str] = None


class StockIssueIn(BaseModel):
    material_id: int
    qty: float = Field(gt=0)
    department: str
    remark: Optional[str] = None


class StockReturnIn(BaseModel):
    material_id: int
    qty: float = Field(gt=0)
    remark: Optional[str] = None


class StockIssueOut(BaseModel):
    id: int
    issue_no: str
    material_id: int
    customer_id: str
    customer_name: str
    material_code: str
    material_name: Optional[str] = None
    qty: float
    department: str
    status: str
    remark: Optional[str] = None
    operator: Optional[str] = None
    confirmed_by: Optional[str] = None
    created_at: datetime
    confirmed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StockReturnOut(BaseModel):
    id: int
    return_no: str
    material_id: int
    customer_id: str
    customer_name: str
    material_code: str
    material_name: Optional[str] = None
    qty: float
    department: str
    status: str
    remark: Optional[str] = None
    applicant: Optional[str] = None
    confirmed_by: Optional[str] = None
    created_at: datetime
    confirmed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StockLedgerOut(BaseModel):
    id: int
    material_id: int
    customer_id: str
    material_code: str
    movement_type: str
    qty_delta: float
    qty_after: float
    ref_no: Optional[str] = None
    department: Optional[str] = None
    operator: Optional[str] = None
    giver: Optional[str] = None
    receiver: Optional[str] = None
    remark: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WarehouseMovementOut(BaseModel):
    id: int
    customer_id: str
    customer_name: str
    movement_type: str
    movement_type_name: str = ""
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    unit: str = "PCS"
    qty: float = 0
    qty_delta: float = 0
    order_no: str = ""
    product_model: str = ""
    order_qty: Optional[float] = None
    process: Optional[str] = None
    doc_date: str = ""
    ref_no: str = ""
    source: str = "excel_sync"
    operator: Optional[str] = None
    giver: Optional[str] = None
    receiver: Optional[str] = None
    remark: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WarehouseOperationIn(BaseModel):
    material_id: int
    movement_type: str
    qty: float
    order_no: Optional[str] = ""
    product_model: Optional[str] = ""
    order_qty: Optional[float] = None
    process: Optional[str] = None
    ref_no: Optional[str] = ""
    remark: Optional[str] = ""
    doc_date: Optional[str] = None
    department: Optional[str] = None
    giver: Optional[str] = ""
    receiver: Optional[str] = ""


class BatchInboundLineIn(BaseModel):
    material_code: str
    qty: float = Field(gt=0)
    remark: Optional[str] = ""
    material_name: Optional[str] = ""
    spec: Optional[str] = ""


class BatchInboundIn(BaseModel):
    customer_id: str
    items: List[BatchInboundLineIn]
    ref_no: Optional[str] = ""
    remark: Optional[str] = ""
    giver: Optional[str] = ""
    receiver: Optional[str] = ""


class BatchOperationErrorOut(BaseModel):
    row: int = 0
    material_code: Optional[str] = None
    material_id: Optional[int] = None
    error: str = ""


class BatchInboundParseOut(BaseModel):
    items: List[BatchInboundLineIn]
    errors: List[BatchOperationErrorOut] = []
    parsed_count: int = 0
    header_row: Optional[int] = None


class BatchSkippedLineOut(BaseModel):
    row: int = 0
    material_code: str = ""
    qty: float = 0
    available_qty: float = 0
    reason: str = ""


class BatchOperationResultOut(BaseModel):
    ref_no: str
    success_count: int
    movements: List[WarehouseMovementOut] = []
    errors: List[BatchOperationErrorOut] = []
    skipped: List[BatchSkippedLineOut] = []
    created_count: int = 0
    created_codes: List[str] = []


class OrderIssuePreviewLineOut(BaseModel):
    material_id: Optional[int] = None
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    required_qty: float = 0
    issued_qty: float = 0
    remain_qty: float = 0
    available_qty: float = 0
    shortage_qty: float = 0
    suggested_qty: float = 0
    status: str = ""
    process: Optional[str] = None
    mount_type: Optional[str] = None


class OrderIssuePreviewOut(BaseModel):
    line_key: str
    purchase_no: str = ""
    product_goods_no: str = ""
    product_goods_name: str = ""
    order_qty: float = 0
    customer_id: str = ""
    customer_name: str = ""
    bom_model_id: Optional[int] = None
    material_status: Optional[str] = None
    message: Optional[str] = None
    lines: List[OrderIssuePreviewLineOut] = []


class BatchIssueLineIn(BaseModel):
    material_id: int
    qty: float = Field(gt=0)
    process: Optional[str] = None
    department: Optional[str] = None
    remark: Optional[str] = ""


class BatchIssueIn(BaseModel):
    lines: List[BatchIssueLineIn]
    ref_no: Optional[str] = ""
    remark: Optional[str] = ""
    skip_shortage: bool = True
    giver: Optional[str] = ""
    receiver: Optional[str] = ""


class BatchIssueImportLineOut(BaseModel):
    material_id: int
    material_code: str
    qty: float
    department: Optional[str] = "smt"
    remark: Optional[str] = ""


class BatchIssueParseOut(BaseModel):
    lines: List[BatchIssueImportLineOut] = []
    errors: List[BatchOperationErrorOut] = []
    parsed_count: int = 0
    header_row: Optional[int] = None


class MaterialOrderUsageOut(BaseModel):
    order_no: str = ""
    product_model: str = ""
    issued_qty: float = 0
    returned_qty: float = 0
    inbound_qty: float = 0
    last_date: str = ""


class MaterialDetailSummaryOut(BaseModel):
    current_qty: float = 0
    available_qty: float = 0
    locked_qty: float = 0
    excel_count_qty: float = 0
    excel_in_qty: float = 0
    excel_demand_qty: Optional[float] = None
    stock_status: str = "unknown"
    stock_gap: Optional[float] = None
    inbound_total: float = 0
    outbound_total: float = 0
    order_count: int = 0
    movement_count: int = 0


class WarehouseMaterialDetailOut(BaseModel):
    material: WarehouseMaterialOut
    summary: MaterialDetailSummaryOut
    orders: List[MaterialOrderUsageOut] = []
    movements: List[WarehouseMovementOut] = []
    stock_ins: List[dict] = []
    ledger: List[dict] = []


class WorkbookSnapshotOut(BaseModel):
    id: int
    customer_id: str
    customer_name: str
    source_file: str
    file_name: str
    sheet_count: int
    sheet_names: List[str] = []
    synced_at: datetime


class SheetSnapshotMetaOut(BaseModel):
    id: int
    snapshot_id: int
    sheet_name: str
    row_count: int
    col_count: int


class SheetSnapshotDataOut(BaseModel):
    id: int
    snapshot_id: int
    sheet_name: str
    row_count: int
    col_count: int
    offset: int = 0
    limit: int = 0
    rows: List[List[Optional[object]]] = []


class ExcelImportResult(BaseModel):
    source_file: str
    customer_name: Optional[str] = None
    rows_imported: int = 0
    rows_updated: int = 0
    status: str
    message: Optional[str] = None


class MonthlyFee(BaseModel):
    month: str
    order_count: int
    tax_amount: float
    no_tax_amount: float
    source: str = "订单跟踪"


class EngineeringConfigOut(BaseModel):
    share_path: str = ""
    share_accessible: bool = False
    assets_share_sync_enabled: bool = False
    assets_import_mode: str = "manual"
    substitution_file_path: str = ""
    substitution_file_accessible: bool = False
    process_detail_file_path: str = ""
    process_detail_file_accessible: bool = False
    customers: list = []


class SubstitutionRuleOut(BaseModel):
    id: int
    customer_id: str = ""
    comp_code: str
    comp_name: Optional[str] = None
    comp_spec: Optional[str] = None
    comp_unit: Optional[str] = None
    comp_attr: Optional[str] = None
    parent_code: str = ""
    parent_name: Optional[str] = None
    parent_spec: Optional[str] = None
    parent_unit: Optional[str] = None
    parent_attr: Optional[str] = None
    purchase_no: str = ""
    relation_type: Optional[str] = None
    sub_code: str = ""
    sub_name: Optional[str] = None
    sub_spec: Optional[str] = None
    sub_unit: Optional[str] = None
    sub_attr: Optional[str] = None
    sub_order: Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    qty: Optional[float] = None
    remark: Optional[str] = None
    confirm_status: str = "confirmed"
    source_type: Optional[str] = None
    source_file: Optional[str] = None
    import_batch_id: Optional[str] = None
    synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SubstitutionMetaOut(BaseModel):
    customer_id: str = ""
    customer_name: str = ""
    row_count: int = 0
    synced_at: Optional[datetime] = None
    source_file: str = ""
    source_accessible: bool = False


class SubstitutionSyncResult(BaseModel):
    status: str
    message: str
    rows_imported: int = 0
    source_file: str = ""
    synced_at: Optional[datetime] = None
    customer_id: str = ""


class SubstitutionPreviewRow(BaseModel):
    comp_code: str
    comp_name: Optional[str] = None
    comp_spec: Optional[str] = None
    comp_unit: Optional[str] = None
    parent_code: str = ""
    parent_name: Optional[str] = None
    purchase_no: str = ""
    relation_type: Optional[str] = "替代料件"
    sub_code: str = ""
    sub_name: Optional[str] = None
    sub_spec: Optional[str] = None
    sub_order: Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    qty: Optional[float] = None
    remark: Optional[str] = None
    confirm_status: str = "confirmed"
    board_tag: Optional[str] = None


class SubstitutionParseOut(BaseModel):
    rows: List[SubstitutionPreviewRow] = []
    format: str = ""
    message: str = ""
    raw_text: str = ""


class SubstitutionImportConfirmIn(BaseModel):
    customer_id: str
    mode: str = "add"  # 兼容旧字段，实际一律按订单号新增
    source_type: str = "xlsx"
    source_file: str = ""
    rows: List[SubstitutionPreviewRow]


class SubstitutionImportResult(BaseModel):
    status: str
    message: str
    customer_id: str = ""
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    import_batch_id: str = ""
    row_count: int = 0
    synced_at: Optional[datetime] = None


class SubstitutionRuleCreateIn(BaseModel):
    customer_id: str
    comp_code: str
    sub_code: str
    parent_code: str = ""
    purchase_no: str = ""
    comp_name: Optional[str] = None
    comp_spec: Optional[str] = None
    comp_unit: Optional[str] = None
    parent_name: Optional[str] = None
    relation_type: Optional[str] = "替代料件"
    sub_name: Optional[str] = None
    sub_spec: Optional[str] = None
    sub_order: Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    qty: Optional[float] = None
    remark: Optional[str] = None
    confirm_status: str = "confirmed"


class SubstitutionRuleUpdateIn(BaseModel):
    comp_code: Optional[str] = None
    sub_code: Optional[str] = None
    parent_code: Optional[str] = None
    purchase_no: Optional[str] = None
    comp_name: Optional[str] = None
    comp_spec: Optional[str] = None
    comp_unit: Optional[str] = None
    parent_name: Optional[str] = None
    relation_type: Optional[str] = None
    sub_name: Optional[str] = None
    sub_spec: Optional[str] = None
    sub_order: Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    qty: Optional[float] = None
    remark: Optional[str] = None
    confirm_status: Optional[str] = None


class SubstitutionManualConfirmIn(BaseModel):
    sub_code: str
    sub_name: Optional[str] = None
    sub_spec: Optional[str] = None


class ProcessMapLineOut(BaseModel):
    seq: Optional[str] = None
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    qty_per: float = 1
    unit: str = "PCS"
    position: Optional[str] = None
    process: Optional[str] = None


class ProcessMapGroupOut(BaseModel):
    process: str
    line_count: int
    lines: List[ProcessMapLineOut] = []


class ProcessMapOut(BaseModel):
    bom_model_id: int
    model_code: str
    model_name: Optional[str] = None
    internal_code: str
    customer_name: str = ""
    process_count: int = 0
    total_lines: int = 0
    processes: List[ProcessMapGroupOut] = []


class ProcessStepDefOut(BaseModel):
    key: str
    label: str
    sub_options: List[str] = []


class ProcessStepsIn(BaseModel):
    laser_label: bool = False
    smt: bool = False
    pre_oven_aoi: bool = False
    insert: bool = False
    post_solder: bool = False
    post_oven_label: bool = False
    test: bool = False
    conformal_enabled: bool = False
    conformal_type: str = "普通三防"
    potting: bool = False


class ProcessRouteSaveIn(BaseModel):
    internal_code: str
    model_code: str
    model_name: Optional[str] = None
    remark: Optional[str] = None
    steps: ProcessStepsIn


class ProcessRouteOut(BaseModel):
    id: int
    internal_code: str
    model_code: str
    model_name: Optional[str] = None
    bom_model_id: Optional[int] = None
    source: str = "manual"
    raw_process: Optional[str] = None
    steps: dict = {}
    route_display: str = ""
    status: str = "pending"
    remark: Optional[str] = None
    synced_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


class ProcessRouteMetaOut(BaseModel):
    source_file: str
    source_accessible: bool
    row_count: int = 0
    pending_count: int = 0
    synced_at: Optional[datetime] = None


class ToolingEntryIn(BaseModel):
    tool_type: str
    tool_code: str = ""
    version: str = ""
    qty: int = 1
    stored_at: str = ""
    remark: Optional[str] = None


class ToolingEntryOut(BaseModel):
    id: Optional[int] = None
    internal_code: str = ""
    model_code: str = ""
    model_name: Optional[str] = None
    bom_model_id: Optional[int] = None
    tool_type: str
    tool_type_label: str = ""
    tool_code: str = ""
    version: str = ""
    qty: int = 1
    stored_at: str = ""
    remark: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class ToolingCatalogOut(BaseModel):
    internal_code: str
    model_code: str
    model_name: Optional[str] = None
    bom_model_id: Optional[int] = None
    order_count: int = 0
    stencil_registered: bool = False
    wave_fixture_registered: bool = False
    ict_fct_fixture_registered: bool = False
    registered_count: int = 0
    tooling_complete: bool = False
    supplier: Optional[str] = None


class ToolingLookupOut(BaseModel):
    internal_code: str
    model_code: str
    model_name: Optional[str] = None
    bom_model_id: Optional[int] = None
    entries: List[ToolingEntryOut] = []
    registered_count: int = 0
    tooling_complete: bool = False


class ToolingSaveIn(BaseModel):
    internal_code: str
    model_code: str
    model_name: Optional[str] = None
    entries: List[ToolingEntryIn]


class ToolingSyncResult(BaseModel):
    ok: bool = True
    dry_run: bool = False
    message: str = ""
    stencil_file: str = ""
    fixture_file: str = ""
    stencil_parsed: int = 0
    fixture_parsed: int = 0
    merged_count: int = 0
    created: int = 0
    updated: int = 0
    by_tool_type: dict = {}
    by_internal_code: dict = {}
    unmapped_stencil_customers: List[str] = []
    unmapped_fixture_sheets: List[str] = []
    samples: List[dict] = []


class ProcessRouteSyncResult(BaseModel):
    status: str
    message: str
    rows_imported: int = 0
    source_file: str = ""
    synced_at: Optional[datetime] = None


class PlacementMetaOut(BaseModel):
    share_path: str = ""
    share_accessible: bool = False
    assets_share_sync_enabled: bool = False
    import_mode: str = "manual"
    file_count: int = 0
    line_count: int = 0
    a123_count: int = 0
    a116_count: int = 0
    synced_at: Optional[datetime] = None


class PlacementFileOut(BaseModel):
    id: Optional[int] = None
    bom_model_id: Optional[int] = None
    internal_code: str
    model_code: str
    model_name: Optional[str] = None
    board_name: Optional[str] = None
    folder_name: Optional[str] = None
    source_file: str = ""
    file_format: str = "unknown"
    units: str = "mm"
    line_count: int = 0
    source: str = "share"
    status: str = "ready"
    audit_status: str = "pending"
    audit_message: str = ""
    asset_status: str = "pending"
    bom_status: str = "pending"
    order_count: int = 0
    synced_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PlacementLineOut(BaseModel):
    id: int
    refdes: str
    comment: Optional[str] = None
    footprint: Optional[str] = None
    layer: Optional[str] = None
    mid_x: Optional[float] = None
    mid_y: Optional[float] = None
    rotation: Optional[float] = None
    skip: bool = False
    material_hint: Optional[str] = None


class PlacementSyncResult(BaseModel):
    status: str
    message: str
    files: list = []
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    share_path: str = ""


class PlacementImportResult(BaseModel):
    status: str
    message: str
    lines: int = 0
    placement_file_id: int = 0
    audit_status: str = ""
    audit_message: str = ""
    internal_code: str = ""
    model_code: str = ""
    file: str = ""


class CustomerAssetOut(BaseModel):
    internal_code: str
    model_code: str
    model_name: Optional[str] = None
    purchase_no: str = ""
    bom_model_id: Optional[int] = None
    bom_status: str = "pending"
    order_count: int = 0
    content_hash: str = ""
    placement_file_id: Optional[int] = None
    placement_line_count: int = 0
    placement_format: str = ""
    placement_audit_status: str = "pending"
    placement_audit_message: str = ""
    placement_asset_status: str = "pending"
    gerber_package_id: Optional[int] = None
    gerber_file_count: int = 0
    gerber_audit_status: str = "pending"
    gerber_audit_message: str = ""
    gerber_asset_status: str = "pending"
    refmap_file_id: Optional[int] = None
    refmap_file_name: str = ""
    refmap_file_size: int = 0
    refmap_page_count: int = 0
    refmap_audit_status: str = "pending"
    refmap_audit_message: str = ""
    refmap_asset_status: str = "pending"


class RefmapImportResult(BaseModel):
    status: str
    message: str
    refmap_file_id: int = 0
    audit_status: str = ""
    audit_message: str = ""
    page_count: int = 0
    file_size: int = 0
    internal_code: str = ""
    model_code: str = ""
    file: str = ""


class GerberMetaOut(BaseModel):
    share_path: str = ""
    share_accessible: bool = False
    assets_share_sync_enabled: bool = False
    import_mode: str = "manual"
    package_count: int = 0
    a123_count: int = 0
    a116_count: int = 0
    synced_at: Optional[datetime] = None


class GerberPackageOut(BaseModel):
    id: Optional[int] = None
    bom_model_id: Optional[int] = None
    internal_code: str
    model_code: str
    model_name: Optional[str] = None
    package_name: str = ""
    folder_name: Optional[str] = None
    source_path: str = ""
    file_count: int = 0
    source: str = "share"
    status: str = "ready"
    audit_status: str = "pending"
    audit_message: str = ""
    asset_status: str = "pending"
    bom_status: str = "pending"
    order_count: int = 0
    synced_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GerberFileOut(BaseModel):
    name: str
    size: int = 0
    ext: str = ""
    kind: str = ""
    valid: bool = True
    message: str = ""


class GerberAuditOut(BaseModel):
    gerber_package_id: int
    audit_status: str
    audit_message: str
    file_count: int = 0
    files: list[GerberFileOut] = []


class GerberSyncResult(BaseModel):
    status: str
    message: str
    packages: list = []
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    share_path: str = ""


class GerberImportResult(BaseModel):
    status: str
    message: str
    file_count: int = 0
    gerber_package_id: int = 0
    audit_status: str = ""
    audit_message: str = ""
    internal_code: str = ""
    model_code: str = ""
    package: str = ""


class BomSyncResult(BaseModel):
    status: str
    message: str
    files: list = []
    models_created: int = 0
    models_updated: int = 0
    share_path: str = ""


class BomImportResult(BaseModel):
    status: str
    message: str
    model_code: str = ""
    lines: int = 0
    bom_model_id: int = 0
    internal_code: str = ""
    purchase_no: str = ""
    file: str = ""


class BomModelOut(BaseModel):
    id: int
    internal_code: str
    customer_id: str
    customer_name: str
    model_code: str
    purchase_no: str = ""
    model_name: Optional[str] = None
    model_spec: Optional[str] = None
    folder_name: Optional[str] = None
    remark: Optional[str] = None
    mount_profile_override: Optional[str] = None
    line_count: int = 0
    is_active: bool = True
    synced_at: Optional[datetime] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class BomModelListOut(BaseModel):
    id: Optional[int] = None
    internal_code: str
    customer_id: str
    customer_name: str
    model_code: str
    model_name: Optional[str] = None
    model_spec: Optional[str] = None
    folder_name: Optional[str] = None
    remark: Optional[str] = None
    purchase_no: str = ""
    line_key: Optional[str] = None
    line_count: int = 0
    bom_status: str = "pending"
    bom_confirmed: bool = False
    bom_model_id: Optional[int] = None
    eng_review_status: str = ""
    eng_review_message: Optional[str] = None
    mount_profile_override: Optional[str] = None
    order_count: int = 0
    order_qty: float = 0
    latest_purchase_date: Optional[str] = None
    is_order_completed: bool = False
    is_active: bool = True
    synced_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    substitution_rule_count: int = 0
    has_substitution: bool = False


class BomLineOut(BaseModel):
    id: int
    bom_model_id: int
    seq: Optional[str] = None
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    unit: str = "PCS"
    qty_per: float = 1
    position: Optional[str] = None
    process: Optional[str] = None
    remark: Optional[str] = None
    sort_order: int = 0
    mount_type: str = ""
    mount_side: str = ""
    mount_source: str = ""
    mount_reason: str = ""
    is_active: bool = True
    source: str = "import"
    control_id: Optional[int] = None
    # 本机型/订单下可替料号（供 BOM 明细与发料单展示）
    substitute_codes: list[str] = []
    # 替代明细（料号/品名/规格），发料单打印用
    substitute_details: list[dict] = []

    class Config:
        from_attributes = True


class BomLineUpdateIn(BaseModel):
    material_code: Optional[str] = None
    material_name: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = None
    qty_per: Optional[float] = None
    position: Optional[str] = None
    process: Optional[str] = None
    remark: Optional[str] = None
    seq: Optional[str] = None


class BomModelMountProfileIn(BaseModel):
    mount_profile_override: str = ""


class MaterialMountProfileIn(BaseModel):
    material_code: str
    mount_type: str
    mount_side: str = ""
    material_name: Optional[str] = None
    bom_model_id: Optional[int] = None
    internal_code: str = ""


class MaterialMountProfileOut(BaseModel):
    id: int
    material_code: str
    internal_code: str = ""
    material_name: Optional[str] = None
    mount_type: str
    mount_side: Optional[str] = None
    source: str = "manual"
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UnresolvedMountLineOut(BaseModel):
    line_id: int
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    position: Optional[str] = None
    process: Optional[str] = None
    mount_reason: str = ""


class MountReadinessIssueOut(BaseModel):
    code: str
    severity: str = "block"
    title: str = ""
    advice: str = ""
    count: int = 0
    samples: list[str] = []


class MountReadinessRowOut(BaseModel):
    line_id: int
    material_code: str = ""
    material_name: str = ""
    position: str = ""
    mount_type: str = ""
    mount_side: str = ""
    mount_source: str = ""
    side_precise: bool = False
    process_precise: bool = False
    row_precise: bool = False
    skipped: bool = False
    issue_codes: list[str] = []
    note: str = ""


class MountReadinessOut(BaseModel):
    bom_model_id: int
    internal_code: str = ""
    model_code: str = ""
    ready: bool = False
    threshold: float = 0.98
    message: str = ""
    reject_text: str = ""
    weld_total: int = 0
    precise_count: int = 0
    side_ok_count: int = 0
    process_ok_count: int = 0
    has_placement: bool = False
    placement_ref_count: int = 0
    ais_skip_repaired: int = 0
    note: str = ""
    detected_profile: str = ""
    issues: list[MountReadinessIssueOut] = []
    rows: list[MountReadinessRowOut] = []
    all_row_count: int = 0


class EngReviewActionIn(BaseModel):
    message: str = ""


class EngIssuePrintMaterialIn(BaseModel):
    material_code: str = ""
    material_name: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = None
    qty_per: float = 0
    issue_qty: float = 0
    mount_type: Optional[str] = None
    mount_side: Optional[str] = None
    position: Optional[str] = None


class EngIssuePrintLogIn(BaseModel):
    process_filter: str = "SMT"
    stencil_src: str = ""
    wave_src: str = ""
    order_qty: float = 0
    line_key: str = ""
    materials: list[EngIssuePrintMaterialIn] = Field(default_factory=list)


class EngIssuePrintLogOut(BaseModel):
    id: int
    bom_model_id: int
    internal_code: str = ""
    model_code: str = ""
    purchase_no: str = ""
    line_key: str = ""
    process_filter: str = ""
    stencil_src: str = ""
    wave_src: str = ""
    operator: str = ""
    order_qty: float = 0
    material_count: int = 0
    material_codes: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None


class EngReviewInboxOut(BaseModel):
    id: int
    bom_model_id: int
    internal_code: str = ""
    model_code: str = ""
    purchase_no: str = ""
    event_type: str = ""
    summary: str = ""
    submitter: Optional[str] = None
    status: str = ""
    created_at: Optional[str] = None


class BomModelLinesOut(BaseModel):
    mount_profile_override: str = ""
    detected_profile: str = ""
    profile_confidence: str = ""
    profile_source: str = ""
    lines: list["BomLineOut"] = []
    unresolved_mount_count: int = 0
    eng_review_status: str = ""
    eng_review_message: Optional[str] = None


class OrderBindBomIn(BaseModel):
    bom_model_id: Optional[int] = None


class KittingSubstituteOut(BaseModel):
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    stock_qty: float = 0
    available_qty: float = 0


class KittingLineOut(BaseModel):
    material_code: str
    material_name: Optional[str] = None
    spec: Optional[str] = None
    unit: str = "PCS"
    qty_per: float = 1
    position: Optional[str] = None
    mount_type: str = ""
    mount_side: str = ""
    mount_source: str = ""
    mount_reason: str = ""
    required_qty: float = 0
    stock_qty: float = 0
    available_qty: float = 0
    own_stock_qty: float = 0
    own_available_qty: float = 0
    excel_count_qty: Optional[float] = None
    excel_in_qty: Optional[float] = None
    excel_demand_qty: Optional[float] = None
    ledger_owe_qty: float = 0
    main_gap_qty: float = 0
    kitting_supply_qty: float = 0
    stock_primary_code: str = ""
    shortage_qty: float = 0
    status: str
    substitute_codes: List[str] = []
    substitutes: List[KittingSubstituteOut] = []


class KittingOut(BaseModel):
    line_key: Optional[str] = None
    purchase_no: Optional[str] = None
    product_goods_no: Optional[str] = None
    bom_model_id: Optional[int] = None
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    order_qty: float = 0
    material_status: str = "unknown"
    message: Optional[str] = None
    ready_count: int = 0
    partial_count: int = 0
    shortage_count: int = 0
    total_lines: int = 0
    lines: List[KittingLineOut] = []


class ScheduleOut(BaseModel):
    id: int
    line_type: str
    sort_order: int
    line_name: Optional[str] = None
    line_key: Optional[str] = None
    internal_code: Optional[str] = None
    customer_id: Optional[str] = None
    purchase_no: Optional[str] = None
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    process: Optional[str] = None
    order_qty: float = 0
    due_date: Optional[str] = None
    material_status: str = "unknown"
    daily_plan: Optional[str] = None
    schedule_status: str = "planned"
    remark: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: datetime
    tooling_registered_count: int = 0
    tooling_complete: bool = False
    tooling_status: str = "unknown"
    tooling_status_label: str = "—"

    class Config:
        from_attributes = True


class ScheduleIn(BaseModel):
    line_type: str
    line_name: Optional[str] = None
    line_key: Optional[str] = None
    internal_code: Optional[str] = None
    customer_id: Optional[str] = None
    purchase_no: Optional[str] = None
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    process: Optional[str] = None
    order_qty: float = 0
    due_date: Optional[str] = None
    material_status: Optional[str] = None
    daily_plan: Optional[str] = None
    schedule_status: Optional[str] = "planned"
    remark: Optional[str] = None
    sort_order: Optional[int] = None
    refresh_kitting: bool = False


class ScheduleReorderIn(BaseModel):
    line_type: str
    ids: List[int]


class ScheduleImportOrderIn(BaseModel):
    line_key: str
    line_type: str
    to_pool: bool = True  # True=计划池（不卡齐套）；False=直接正式排产（卡齐套）


# —— 物料管制 ——
class MaterialControlOrderIn(BaseModel):
    purchase_no: str
    order_qty: float = 0  # 工单总量
    control_qty: float = 0  # 合计管制套数（可等于各换料行之和）


class MaterialControlChangeIn(BaseModel):
    control_qty: float = 0  # 本批管制套数（从工单总量中抽出）
    remove_code: str = ""
    remove_qty: float = 0
    remove_refdes: Optional[str] = None
    add_code: str = ""
    add_qty: float = 0
    add_refdes: Optional[str] = None
    remark: Optional[str] = None


class MaterialControlGroupIn(BaseModel):
    model_code: str
    orders: list[MaterialControlOrderIn]
    changes: list[MaterialControlChangeIn]


class MaterialControlCreateIn(BaseModel):
    control_no: str
    control_type: str = "PCBA管制"
    reason: Optional[str] = None
    ecn_no: Optional[str] = None
    # 多机型（优先）
    groups: Optional[list[MaterialControlGroupIn]] = None
    # 兼容旧单机型
    model_code: Optional[str] = None
    orders: Optional[list[MaterialControlOrderIn]] = None
    changes: Optional[list[MaterialControlChangeIn]] = None


class MaterialControlUpdateIn(BaseModel):
    control_no: Optional[str] = None
    control_type: Optional[str] = None
    reason: Optional[str] = None
    ecn_no: Optional[str] = None
    groups: Optional[list[MaterialControlGroupIn]] = None
    model_code: Optional[str] = None
    orders: Optional[list[MaterialControlOrderIn]] = None
    changes: Optional[list[MaterialControlChangeIn]] = None
