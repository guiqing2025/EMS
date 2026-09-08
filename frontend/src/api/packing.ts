import { apiFetch } from '@/api/http'
import type { ScanRecord, ScanResult, ShipmentResult } from '@/types/order'

export async function fetchPendingScans(lineKey: string) {
  return apiFetch<ScanRecord[]>(
    `/packing/scans/${encodeURIComponent(lineKey)}?status=pending&limit=15`,
  )
}

export interface InboundScanItem {
  id: number
  barcode: string
  code_type?: string | null
  status: string
  status_label?: string
  operator?: string | null
  scanned_at?: string | null
  shipped_at?: string | null
  shipment_id?: number | null
  box_no?: string | null
}

export interface InboundDetailResult {
  line_key: string
  purchase_no: string
  model_code: string
  model_name: string
  pending_count: number
  shipped_count: number
  total: number
  items: InboundScanItem[]
}

export async function fetchInboundDetail(
  lineKey: string,
  opts?: { status?: string; keyword?: string; limit?: number },
) {
  const qs = new URLSearchParams()
  qs.set('status', opts?.status || 'all')
  if (opts?.keyword) qs.set('keyword', opts.keyword)
  qs.set('limit', String(opts?.limit ?? 5000))
  return apiFetch<InboundDetailResult>(
    `/packing/inbound-detail/${encodeURIComponent(lineKey)}?${qs.toString()}`,
  )
}

export async function exportInboundDetailBlob(
  lineKey: string,
  opts?: { status?: string; keyword?: string },
) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const qs = new URLSearchParams()
  qs.set('status', opts?.status || 'all')
  if (opts?.keyword) qs.set('keyword', opts.keyword)
  const res = await fetch(
    `/api/packing/inbound-detail/${encodeURIComponent(lineKey)}/export?${qs.toString()}`,
    { headers: token ? { 'X-Auth-Token': token } : {} },
  )
  if (!res.ok) {
    let msg = '导出入库明细失败'
    try {
      const data = await res.json()
      if (data?.detail) msg = typeof data.detail === 'string' ? data.detail : msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  const disposition = res.headers.get('Content-Disposition') || ''
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const plain = disposition.match(/filename="?([^";]+)"?/i)
  const filename = star
    ? decodeURIComponent(star[1])
    : plain
      ? decodeURIComponent(plain[1])
      : '入库明细.xlsx'
  const blob = await res.blob()
  return { blob, filename }
}

export async function submitScan(lineKey: string, barcode: string, operator: string) {
  return apiFetch<ScanResult>('/packing/scan', {
    method: 'POST',
    body: JSON.stringify({ line_key: lineKey, barcode, operator }),
  })
}

export interface ShipInput {
  line_key: string
  ship_date: string
  qty?: number
  box_count?: number
  qty_per_box?: number
  logistics?: string
  remark?: string
  operator?: string
}

export async function confirmShipment(payload: ShipInput) {
  return apiFetch<ShipmentResult>('/packing/ship', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface ShipPackSpec {
  qty: number
  qty_per_box: number
  box_count?: number
}

export interface ShipMultiLineInput {
  line_key: string
  qty: number
  box_count?: number
  qty_per_box?: number
  box_ids?: number[]
  pack_specs?: ShipPackSpec[]
  remainder_qty?: number
}

export interface ShipMultiInput {
  customer_id: string
  ship_date: string
  logistics?: string
  remark?: string
  operator?: string
  lines: ShipMultiLineInput[]
}

export interface ShipMultiResult {
  slip_id: number
  slip_no: string
  customer_id: string
  customer_name: string
  ship_date: string
  logistics: string
  remark: string
  operator: string
  line_count: number
  total_qty: number
  shipment_ids: number[]
  approval_status?: string
  message?: string
}

export async function confirmMultiShipment(payload: ShipMultiInput) {
  return apiFetch<ShipMultiResult>('/packing/ship-multi', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function fetchLatestShipment(lineKey: string) {
  return apiFetch<ShipmentResult>(
    `/packing/shipments/latest?line_key=${encodeURIComponent(lineKey)}`,
  )
}

export interface ShipmentRevokeResult {
  id: number
  shipment_no: string
  line_key: string
  purchase_no: string
  qty: number
  restored_qty: number
  ship_date: string
  message: string
}

export async function revokeShipment(payload: { line_key?: string; shipment_id?: number }) {
  return apiFetch<ShipmentRevokeResult>('/packing/ship/revoke', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface ShipReconcileShipment {
  id: number
  shipment_no: string
  ship_date: string
  qty: number
  box_count: number
  qty_per_box?: number
  logistics?: string
  remark?: string
  operator?: string
  created_at?: string | null
}

export interface ShipReconcileResult {
  line_key: string
  purchase_no: string
  customer_name: string
  model_code: string
  model_name: string
  product_spec?: string
  order_qty: number
  inbound_qty: number
  pending_qty: number
  shipped_qty: number
  unshipped_qty: number
  balanced: boolean
  can_close: boolean
  status_label: string
  is_completed: boolean
  srm_delivery_qty: number
  srm_receive_qty: number
  srm_un_delivery_qty: number
  shipments: ShipReconcileShipment[]
}

export async function fetchShipReconcile(lineKey: string) {
  return apiFetch<ShipReconcileResult>(`/packing/reconcile/${encodeURIComponent(lineKey)}`)
}

export interface ShipBackfillInput {
  line_key: string
  /** 追加历史数量（优先） */
  add_qty?: number
  /** 兼容旧：补到目标累计 */
  target_shipped_qty?: number
  ship_date?: string
  remark?: string
  operator?: string
}

export interface ShipBackfillResult {
  shipment_id: number
  shipment_no: string
  line_key: string
  purchase_no: string
  added_qty: number
  target_shipped_qty: number
  shipped_qty: number
  pending_qty: number
  unshipped_qty: number
  order_qty: number
  ship_date: string
  message: string
}

/** 历史发货补录：对齐上线前客户已收（不影响生产扫码） */
export async function backfillHistoricalShip(payload: ShipBackfillInput) {
  return apiFetch<ShipBackfillResult>('/packing/ship/backfill', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface PendingShipApprovalItem {
  id: number
  shipment_no: string
  slip_id?: number | null
  line_key: string
  purchase_no: string
  customer_name: string
  product_goods_no: string
  product_goods_name: string
  qty: number
  ship_date: string
  box_count?: number
  qty_per_box?: number
  operator: string
  remark: string
  pack_note?: string
  approval_status: string
  created_at?: string | null
}

export interface PendingShipApprovalsResult {
  items: PendingShipApprovalItem[]
  can_approve: boolean
  approver_usernames: string[]
}

export async function fetchPendingShipApprovals(limit = 200) {
  return apiFetch<PendingShipApprovalsResult>(
    `/packing/ship/pending-approvals?limit=${limit}`,
  )
}

export interface ShipApproveInput {
  shipment_id?: number
  slip_id?: number
}

export interface ShipApproveResult {
  approved_count: number
  shipment_ids: number[]
  total_qty: number
  approver: string
  message: string
}

export async function approveShipment(payload: ShipApproveInput) {
  return apiFetch<ShipApproveResult>('/packing/ship/approve', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface PendingShipLabelJob {
  key: string
  slip_id?: number | null
  shipment_id?: number | null
  slip_no: string
  customer_name: string
  ship_date: string
  operator: string
  line_count: number
  total_qty: number
  total_boxes: number
}

export interface PendingShipLabelsResult {
  items: PendingShipLabelJob[]
  slip_count: number
  label_count: number
  total_qty: number
}

export async function fetchPendingShipLabels(limit = 200) {
  return apiFetch<PendingShipLabelsResult>(
    `/packing/ship/pending-labels?limit=${limit}`,
  )
}

export interface PackBoxInfo {
  id: number
  box_no: string
  line_key: string
  purchase_no?: string
  goods_no?: string
  goods_name?: string
  qty: number
  qty_target: number
  status: string
  pack_mode?: string
  shipment_id?: number | null
  full?: boolean
  barcodes?: string[]
  sealed?: boolean
  printed?: boolean
  label_printed_at?: string | null
  label_printed_by?: string | null
}

export interface PackBoxStationState {
  box: PackBoxInfo | null
  sealed_boxes: PackBoxInfo[]
  records?: PackBoxInfo[]
  loose_pending: number
}

export function canResumePackBox(row: PackBoxInfo) {
  const st = (row.status || '').trim()
  if (st === 'awaiting' || st === 'shipped' || row.shipment_id) return false
  const qty = Number(row.qty || 0)
  const target = Number(row.qty_target || 0)
  if (st === 'open') return true
  if (st === 'sealed' && (!target || qty < target)) return true
  return false
}

export async function fetchPackingOrder(lineKey: string) {
  return apiFetch<{
    line_key: string
    purchase_no: string
    batch_pur_qty: number
    pending_ship_qty: number
    shipped_local_qty: number
  }>(`/packing/order/${encodeURIComponent(lineKey)}`)
}

export async function fetchPackBoxRecords(opts?: {
  keyword?: string
  status?: string
  limit?: number
}) {
  const qs = new URLSearchParams()
  qs.set('scan_only', 'true')
  if (opts?.keyword) qs.set('keyword', opts.keyword)
  if (opts?.status) qs.set('status', opts.status)
  qs.set('limit', String(opts?.limit ?? 300))
  return apiFetch<{
    items: PackBoxInfo[]
    matched_barcode?: string | null
    matched_box_no?: string | null
    barcode_hint?: string | null
  }>(`/packing/boxes?${qs.toString()}`)
}

export async function lookupPackBox(q: string) {
  return apiFetch<{
    box_no: string
    qty: number
    qty_target: number
    status: string
    status_label: string
    purchase_no: string
    goods_no: string
    goods_name: string
    matched_barcode: string
  }>(`/packing/box-lookup?q=${encodeURIComponent(q)}`)
}

export async function fetchPackBoxCurrent(lineKey: string) {
  return apiFetch<PackBoxStationState>(
    `/packing/box/current?line_key=${encodeURIComponent(lineKey)}`,
  )
}

export async function openPackBox(lineKey: string, qtyTarget: number) {
  return apiFetch<PackBoxInfo>('/packing/box/open', {
    method: 'POST',
    body: JSON.stringify({ line_key: lineKey, qty_target: qtyTarget }),
  })
}

export async function sealPackBox(boxId: number) {
  return apiFetch<PackBoxInfo>('/packing/box/seal', {
    method: 'POST',
    body: JSON.stringify({ box_id: boxId }),
  })
}

export async function resumePackBox(boxId: number) {
  return apiFetch<PackBoxInfo>('/packing/box/resume', {
    method: 'POST',
    body: JSON.stringify({ box_id: boxId }),
  })
}

export async function absorbLooseIntoBox(boxId: number) {
  return apiFetch<PackBoxInfo & { absorbed?: number; remaining_loose?: number; sealed?: boolean }>(
    '/packing/box/absorb-loose',
    {
      method: 'POST',
      body: JSON.stringify({ box_id: boxId }),
    },
  )
}

export async function deletePackBox(boxId: number) {
  return apiFetch<{ id: number; box_no: string; qty: number }>(`/packing/box/${boxId}`, {
    method: 'DELETE',
  })
}

export async function deleteInboundScan(barcode: string) {
  return apiFetch<{
    barcode: string
    purchase_no: string
    box_no: string
    box_deleted: boolean
    box_remaining: number
  }>('/packing/scan/delete', {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}

export function isBoxLabelPrinted(row?: { printed?: boolean; label_printed_at?: string | null } | null) {
  return !!(row?.printed || row?.label_printed_at)
}

export function openBoxLabelPrint(boxNo: string) {
  const no = (boxNo || '').trim()
  if (!no) return
  window.open(`/static/ship_label.html?box_no=${encodeURIComponent(no)}`, '_blank')
}

export function onBoxLabelPrinted(handler: (boxNo: string) => void) {
  const fn = (e: MessageEvent) => {
    if (e?.data?.type === 'ems-box-label-printed' && e.data.box_no) {
      handler(String(e.data.box_no))
    }
  }
  window.addEventListener('message', fn)
  return () => window.removeEventListener('message', fn)
}

export interface ShipmentRecordRow {
  id: number
  shipment_no: string
  slip_id?: number | null
  slip_no?: string
  line_key: string
  purchase_no: string
  customer_name?: string
  product_goods_no?: string
  product_goods_name?: string
  qty: number
  ship_date: string
  box_count: number
  qty_per_box?: number
  logistics?: string
  remark?: string
  operator?: string
  approval_status?: string
  status_label?: string
  approved_by?: string
  approved_at?: string | null
  created_at?: string | null
}

export interface ShipmentRecordLookup {
  lookup_type: string
  found: boolean
  scan: {
    barcode: string
    status: string
    status_label: string
    line_key: string
    purchase_no: string
    product_goods_no?: string
    product_goods_name?: string
    customer_name?: string
    operator?: string
    scanned_at?: string | null
    shipped_at?: string | null
    shipment_id?: number | null
  } | null
  shipment: ShipmentRecordRow | null
  batch_barcodes: Array<{
    barcode: string
    operator?: string
    scanned_at?: string | null
    shipped_at?: string | null
    status?: string
    status_label?: string
  }>
  batch_total: number
  message?: string
}

export async function fetchShipmentRecords(opts?: {
  keyword?: string
  status?: string
  limit?: number
}) {
  const qs = new URLSearchParams()
  if (opts?.keyword) qs.set('keyword', opts.keyword)
  if (opts?.status) qs.set('status', opts.status)
  qs.set('limit', String(opts?.limit ?? 200))
  return apiFetch<{
    items: ShipmentRecordRow[]
    highlight_id?: number | null
    matched_barcode?: string
    matched_shipment_no?: string
    barcode_hint?: string
  }>(`/packing/shipment-records?${qs.toString()}`)
}

export async function lookupShipmentRecord(q: string) {
  return apiFetch<ShipmentRecordLookup>(
    `/packing/shipment-records/lookup?q=${encodeURIComponent(q)}`,
  )
}

export async function fetchShipmentRecordBarcodes(shipmentId: number) {
  return apiFetch<{
    shipment: ShipmentRecordRow
    total: number
    items: ShipmentRecordLookup['batch_barcodes']
  }>(`/packing/shipment-records/${shipmentId}/barcodes`)
}

export async function exportShipmentRecordBlob(shipmentId: number) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const res = await fetch(`/api/packing/shipment-records/${shipmentId}/export`, {
    headers: token ? { 'X-Auth-Token': token } : {},
  })
  if (!res.ok) {
    let msg = '导出批次板码失败'
    try {
      const data = await res.json()
      if (data?.detail) msg = typeof data.detail === 'string' ? data.detail : msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  const cd = res.headers.get('Content-Disposition') || ''
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i)
  const plain = cd.match(/filename="([^"]+)"/i)
  const filename = decodeURIComponent(star?.[1] || plain?.[1] || `批次板码_${shipmentId}.xlsx`)
  return { blob: await res.blob(), filename }
}

/** 扫满/封箱后弹窗，让操作员重填下一箱数量。取消则停在批次记录。 */
export async function promptNextBoxQty(sealedNo: string, defaultQty: number): Promise<number | null> {
  try {
    const { ElMessageBox } = await import('element-plus')
    const { value } = await ElMessageBox.prompt(
      `本箱 ${sealedNo} 已封好。请设置下一箱数量后继续扫。`,
      '下一箱装多少？',
      {
        confirmButtonText: '确认下一箱数量',
        cancelButtonText: '先停一下',
        inputValue: String(Math.max(1, Number(defaultQty) || 60)),
        inputPattern: /^[1-9]\d{0,4}$/,
        inputErrorMessage: '请输入大于 0 的整数',
      },
    )
    const n = Number(value)
    return n > 0 ? n : null
  } catch {
    return null
  }
}
