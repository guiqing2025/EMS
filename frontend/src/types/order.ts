export interface SrmOrder {
  id: number
  line_key: string
  purchase_no: string
  purchase_seq?: string | null
  purchase_phase_seq?: string | null
  product_goods_no?: string | null
  product_goods_name?: string | null
  product_spec?: string | null
  batch_pur_qty: number
  output_qty: number
  delivery_qty: number
  receive_qty: number
  un_receive_qty: number
  purchase_date?: string | null
  expect_arrival_date?: string | null
  srm_status_name?: string | null
  /** 内部统一状态：open | partial | closed | cancelled */
  internal_status?: string
  /** 内部统一状态中文：进行中 / 部分交付 / 已结案 / 已取消 */
  internal_status_label?: string
  is_completed: boolean
  customer_id?: string | null
  customer_name?: string | null
  remark?: string | null
  collected_sets_qty: number
  customer_kit_status?: string | null
  customer_kit_status_label?: string | null
  customer_kitted_at?: string | null
  pending_ship_qty: number
  shipped_local_qty: number
  /** 未入库 = 未收 − 入库（入库=待发+已发） */
  stock_balance_qty?: number
  /** SMT-AOI 已测试板数（按采购单汇总，随 AOI 同步更新） */
  aoi_test_qty?: number
  /** 插件工序扫码数 */
  plugin_qty?: number
  /** 后焊工序扫码数 */
  post_solder_qty?: number
  /** ICT 已测试板数（按采购单汇总，随 ICT 同步更新） */
  ict_test_qty?: number
  /** 三防工序扫码数 */
  coating_qty?: number
  is_controlled?: boolean
  control_nos?: string[]
  control_draft_nos?: string[]
  has_control?: boolean
  /** 下单日期在近 3 个自然日内 */
  is_new_order?: boolean
  /** processing=加工订单；expense=费用订单（钢网/治具等） */
  biz_kind?: string
  biz_kind_label?: string
  /** 是否已进入计划池/正式排产（按订单行） */
  in_plan?: boolean
  /** pending=待转计划；done=已转计划 */
  plan_status?: string
  plan_status_label?: string
}

export interface OrderFilters {
  customer_id?: string
  keyword?: string
  completed?: string
  srm_status?: string
  receive_filter?: string
  date_from?: string
  date_to?: string
  controlled?: string
  /** 仅近 3 天新订单 */
  new_only?: boolean | string
  /** all | processing | expense；列表默认 processing */
  biz_kind?: string
  /** false=跳过 AOI/ICT/工序/工装汇总（静默刷新减负）；入库数量仍返回 */
  include_device_stats?: boolean | string
}

export interface ManualOrderInput {
  customer_name: string
  purchase_no: string
  purchase_seq?: string
  product_goods_no?: string
  product_goods_name?: string
  product_spec?: string
  batch_pur_qty: number
  purchase_date?: string
  expect_arrival_date?: string
  remark?: string
}

export interface StatusOption {
  name: string
  count: number
}

export interface CustomerOption {
  id: string
  name: string
}

export interface ScanRecord {
  id: number
  barcode: string
}

export interface ScanResult {
  pending_ship_qty: number
  shipped_local_qty: number
  order_qty: number
}

export interface ShipmentResult {
  id: number
  shipment_no: string
  line_key?: string
  purchase_no?: string
  qty: number
  ship_date?: string
  box_count?: number
}
