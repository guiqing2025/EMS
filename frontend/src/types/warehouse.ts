export interface WarehouseCustomer {
  id: string
  name: string
}

/** 成品库存行：结存 = 订单数量 − 客户收货数 − 入库数 */
export interface FinishedGoodsRow {
  line_key: string
  customer_id: string
  customer_name: string
  purchase_no: string
  model_code: string
  model_name: string
  order_qty: number
  receive_qty: number
  inbound_qty: number
  pending_qty: number
  shipped_qty: number
  balance_qty: number
  is_completed: boolean
}

export interface WarehouseMaterial {
  id: number
  customer_id: string
  customer_name: string
  material_code: string
  material_name?: string | null
  spec?: string | null
  qty: number
  available_qty: number
  substitute_codes: string[]
  is_substitute_alias: boolean
  excel_in_qty?: number | null
  excel_count_qty?: number | null
  excel_demand_qty?: number | null
  excel_synced_at?: string | null
  last_op_at?: string | null
  last_op_type?: string | null
  last_op_type_name?: string | null
  last_op_giver?: string | null
  last_op_receiver?: string | null
  last_op_operator?: string | null
}

export interface WarehouseBomModelCandidate {
  id: number
  model_code: string
  model_name?: string | null
  customer_id: string
  customer_name: string
  line_count: number
  purchase_no?: string
  order_qty?: number
  bom_status?: string
}

export interface WarehouseModelMaterialLine {
  material_id?: number | null
  material_code: string
  material_name?: string | null
  spec?: string | null
  unit: string
  qty_per: number
  position?: string | null
  required_qty: number
  stock_qty: number
  available_qty: number
  shortage_qty: number
  status: string
  substitute_codes: string[]
  excel_count_qty?: number | null
  excel_in_qty?: number | null
  excel_demand_qty?: number | null
  stock_primary_code?: string
}

export interface WarehouseModelMaterials {
  matched: boolean
  bom_model_id?: number | null
  model_code?: string | null
  model_name?: string | null
  customer_id?: string | null
  customer_name?: string | null
  purchase_no?: string | null
  order_qty: number
  material_status: string
  ready_count: number
  partial_count: number
  shortage_count: number
  total_lines: number
  message?: string | null
  candidates: WarehouseBomModelCandidate[]
  lines: WarehouseModelMaterialLine[]
}

export interface StockInRecord {
  id: number
  receipt_no: string
  customer_name: string
  material_code: string
  material_name?: string | null
  qty: number
  source: string
  source_name?: string
  operator?: string | null
  giver?: string | null
  receiver?: string | null
  remark?: string | null
  created_at: string
}

export interface StockIssue {
  id: number
  issue_no: string
  customer_name: string
  material_code: string
  material_name?: string | null
  qty: number
  department: string
  status: string
  created_at: string
}

export interface StockReturn {
  id: number
  return_no: string
  customer_name: string
  material_code: string
  material_name?: string | null
  qty: number
  department: string
  status: string
}

export interface StockLedger {
  id: number
  created_at: string
  movement_type: string
  material_code: string
  qty_delta: number
  qty_after: number
  ref_no?: string | null
  department?: string | null
  operator?: string | null
  giver?: string | null
  receiver?: string | null
}

export interface WarehouseMovement {
  id: number
  customer_name: string
  movement_type: string
  movement_type_name: string
  material_code: string
  material_name?: string | null
  qty: number
  qty_delta: number
  order_no: string
  product_model: string
  order_qty?: number | null
  process?: string | null
  doc_date: string
  ref_no: string
  source: string
  operator?: string | null
  giver?: string | null
  receiver?: string | null
  remark?: string | null
  created_at?: string
}

export interface MaterialOrderUsage {
  order_no: string
  product_model: string
  issued_qty: number
  returned_qty: number
  inbound_qty: number
  last_date: string
}

export interface MaterialDetailSummary {
  current_qty: number
  available_qty: number
  locked_qty: number
  excel_count_qty: number
  excel_in_qty: number
  excel_demand_qty?: number | null
  stock_status: string
  stock_gap?: number | null
  inbound_total: number
  outbound_total: number
  order_count: number
  movement_count: number
}

export interface MaterialStockInBrief {
  id: number
  receipt_no: string
  qty: number
  source: string
  source_name?: string
  operator?: string | null
  giver?: string | null
  receiver?: string | null
  remark?: string | null
  created_at: string
}

export interface WarehouseMaterialDetail {
  material: WarehouseMaterial
  summary: MaterialDetailSummary
  orders: MaterialOrderUsage[]
  movements: WarehouseMovement[]
  stock_ins: MaterialStockInBrief[]
  ledger: Array<{
    id: number
    movement_type: string
    qty_delta: number
    qty_after: number
    ref_no?: string | null
    operator?: string | null
    giver?: string | null
    receiver?: string | null
    remark?: string | null
    created_at: string
  }>
}

export interface WarehouseConfig {
  share_path: string
  share_resolved: string
  share_accessible: boolean
}

export interface DeptSummary {
  pending_issues: number
  pending_returns: number
}

export interface BatchOperationResult {
  ref_no: string
  success_count: number
  movements: WarehouseMovement[]
  errors: Array<{ row?: number; material_code?: string; material_id?: number; error: string }>
  skipped: Array<{ row?: number; material_code?: string; qty?: number; available_qty?: number; reason: string }>
  created_count?: number
  created_codes?: string[]
}

export interface OrderIssuePreviewLine {
  material_id?: number | null
  material_code: string
  material_name?: string | null
  spec?: string | null
  required_qty: number
  issued_qty: number
  remain_qty: number
  available_qty: number
  shortage_qty: number
  suggested_qty: number
  status: string
  process?: string | null
  mount_type?: string | null
  issue_qty?: number
  selected?: boolean
  department?: string
}

export interface OrderIssuePreview {
  line_key: string
  purchase_no: string
  product_goods_no: string
  product_goods_name: string
  order_qty: number
  customer_id: string
  customer_name: string
  bom_model_id?: number | null
  material_status?: string | null
  message?: string | null
  lines: OrderIssuePreviewLine[]
}

export interface BatchInboundLine {
  material_code: string
  qty: number
  remark?: string
  material_name?: string
  spec?: string
}

export interface BatchInboundParseResult {
  items: BatchInboundLine[]
  errors: Array<{ row?: number; material_code?: string; error: string }>
  parsed_count: number
  header_row?: number | null
}

export interface BatchIssueParseResult {
  lines: Array<{
    material_id: number
    material_code: string
    qty: number
    department?: string
    remark?: string
  }>
  errors: Array<{ row?: number; material_code?: string; error: string }>
  parsed_count: number
  header_row?: number | null
}
