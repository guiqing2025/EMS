/** PDA 会话状态（本地 sessionStorage） */

export type PdaStation =
  | 'smt'
  | 'plugin'
  | 'post_solder'
  | 'coating'
  | 'packing'
  | 'dip_fai'
  | 'smt_ipqc'

export interface PdaOrderPick {
  line_key: string
  purchase_no: string
  product_goods_no?: string
  customer_name?: string
  product_name?: string
  output_qty?: number
  packing_pending_qty?: number
  packing_shipped_qty?: number
}

export const PDA_STATION_LABELS: Record<PdaStation, string> = {
  smt: 'SMT',
  plugin: '插件',
  post_solder: '后焊',
  coating: '三防',
  packing: '包装入库',
  dip_fai: 'DIP首件',
  smt_ipqc: 'SMT巡检',
}

const K_STATION = 'ems_pda_station'
const K_ORDER = 'ems_pda_order'
const K_GUARD = 'ems_pda_guard'

export function getPdaStation(): PdaStation | '' {
  const v = (sessionStorage.getItem(K_STATION) || '').trim()
  return (v as PdaStation) || ''
}

export function setPdaStation(station: PdaStation | '') {
  if (!station) sessionStorage.removeItem(K_STATION)
  else sessionStorage.setItem(K_STATION, station)
}

export function getPdaOrder(): PdaOrderPick | null {
  try {
    const raw = sessionStorage.getItem(K_ORDER)
    if (!raw) return null
    return JSON.parse(raw) as PdaOrderPick
  } catch {
    return null
  }
}

export function setPdaOrder(order: PdaOrderPick | null) {
  if (!order) sessionStorage.removeItem(K_ORDER)
  else sessionStorage.setItem(K_ORDER, JSON.stringify(order))
}

export function clearPdaOrder() {
  sessionStorage.removeItem(K_ORDER)
}

export function getPdaGuard(): boolean {
  return sessionStorage.getItem(K_GUARD) === '1'
}

export function setPdaGuard(on: boolean) {
  if (on) sessionStorage.setItem(K_GUARD, '1')
  else sessionStorage.removeItem(K_GUARD)
}
