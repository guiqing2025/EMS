export interface MaterialControlOrder {
  id?: number
  group_id?: number | null
  purchase_no: string
  line_key?: string | null
  /** 工单总量（如 10000） */
  order_qty: number
  /** 合计管制套数（各换料行本批数量之和） */
  control_qty: number
}

export interface MaterialControlChange {
  id?: number
  group_id?: number | null
  /** 本批从工单中抽出的管制套数（如三行各 500） */
  control_qty: number
  remove_code: string
  remove_qty: number
  remove_refdes?: string | null
  add_code: string
  add_qty: number
  add_refdes?: string | null
  remark?: string | null
}

export interface MaterialControlGroup {
  id?: number | null
  model_code: string
  sort_order?: number
  orders: MaterialControlOrder[]
  changes: MaterialControlChange[]
}

export interface MaterialControl {
  id: number
  control_no: string
  model_code: string
  control_type: string
  reason?: string | null
  ecn_no?: string | null
  attachment_path?: string | null
  attachment_name?: string | null
  status: 'draft' | 'active' | 'cancelled' | string
  created_by?: string | null
  confirmed_by?: string | null
  confirmed_at?: string | null
  cancelled_by?: string | null
  cancelled_at?: string | null
  created_at?: string | null
  updated_at?: string | null
  groups?: MaterialControlGroup[]
  orders: MaterialControlOrder[]
  changes: MaterialControlChange[]
  confirm_applied?: string[]
  confirm_skipped_inactive?: string[]
  confirm_skipped_no_bom?: string[]
}

export interface MaterialControlGroupInput {
  model_code: string
  orders: Array<{ purchase_no: string; order_qty?: number; control_qty: number }>
  changes: Array<{
    control_qty?: number
    remove_code?: string
    remove_qty?: number
    remove_refdes?: string | null
    add_code?: string
    add_qty?: number
    add_refdes?: string | null
    remark?: string | null
  }>
}

export interface MaterialControlCreateInput {
  control_no: string
  control_type?: string
  reason?: string | null
  ecn_no?: string | null
  groups: MaterialControlGroupInput[]
}

export interface MaterialControlParseResult {
  source?: string
  warnings: string[]
  raw_text_preview?: string
  fields: {
    control_no?: string
    model_code?: string
    control_type?: string
    reason?: string | null
    ecn_no?: string | null
    groups?: MaterialControlGroupInput[]
    orders?: Array<{ purchase_no: string; order_qty?: number; control_qty: number }>
    changes?: MaterialControlGroupInput['changes']
  }
}

export interface MaterialControlImportResult {
  created_count: number
  error_count: number
  created: MaterialControl[]
  errors: string[]
}

export interface YonglianEcnMatchedOrder {
  purchase_no: string
  qty: number
  customer_id?: string
  customer_name?: string
  product_goods_no?: string
  product_goods_name?: string
  selected?: boolean
  from_sheet?: boolean
}

export interface YonglianEcnParseResult {
  source?: string
  filename?: string
  model_code: string
  model_name?: string
  ecn_date?: string
  suggested_control_no: string
  control_type?: string
  reason?: string
  changes: MaterialControlGroupInput['changes']
  matched_orders: YonglianEcnMatchedOrder[]
  explicit_purchase_nos?: string[]
  warnings: string[]
  message?: string
}

export interface YonglianEcnImportResult {
  ok: boolean
  message: string
  control: MaterialControl
  preview_warnings?: string[]
}
