import { apiFetch } from './http'

export type ApItem = {
  id: number
  source_type: string
  source_no: string
  supplier_name: string
  amount: number
  settled_amount: number
  open_amount: number
  status: string
}

export type ArItem = {
  id: number
  source_type: string
  source_no: string
  customer_name: string
  amount: number
  settled_amount: number
  open_amount: number
  status: string
}

export type CashAccount = { id: number; code: string; name: string; kind: string; balance: number }
export type PaymentRequest = {
  id: number
  request_no: string
  supplier_name: string
  amount: number
  status: string
  lines?: Array<{ ap_id: number; ap_source_no: string; amount: number }>
}
export type PaymentDoc = { id: number; payment_no: string; request_no: string; amount: number; status: string }
export type ReceiptDoc = {
  id: number
  receipt_no: string
  customer_name: string
  amount: number
  status: string
}

export function fetchAp(status = '') {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiFetch<{ items: ApItem[]; summary: Array<{ supplier_name: string; open_amount: number; count: number }> }>(
    `/finance/ap${qs}`,
  )
}

export function fetchAr(status = '') {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiFetch<{ items: ArItem[]; summary: Array<{ customer_name: string; open_amount: number; count: number }> }>(
    `/finance/ar${qs}`,
  )
}

export function createOtherExpense(body: { amount: number; supplier_name?: string; remark?: string }) {
  return apiFetch<ApItem>('/finance/ap/other-expense', { method: 'POST', body: JSON.stringify(body) })
}

export function createOtherIncome(body: { amount: number; customer_name?: string; remark?: string }) {
  return apiFetch<ArItem>('/finance/ar/other-income', { method: 'POST', body: JSON.stringify(body) })
}

export function fetchPaymentRequests() {
  return apiFetch<{ items: PaymentRequest[] }>('/finance/payment-requests')
}

export function createPaymentRequest(ap_ids: number[], remark = '') {
  return apiFetch<PaymentRequest>('/finance/payment-requests', {
    method: 'POST',
    body: JSON.stringify({ ap_ids, remark }),
  })
}

export function approvePaymentRequest(id: number, approve = true) {
  return apiFetch<PaymentRequest>(`/finance/payment-requests/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approve }),
  })
}

export function createPaymentFromRequest(requestId: number, account_id: number) {
  return apiFetch<PaymentDoc>(`/finance/payments/from-request/${requestId}`, {
    method: 'POST',
    body: JSON.stringify({ account_id }),
  })
}

export function postPayment(id: number) {
  return apiFetch<PaymentDoc>(`/finance/payments/${id}/post`, { method: 'POST' })
}

export function fetchPayments() {
  return apiFetch<{ items: PaymentDoc[] }>('/finance/payments')
}

export function createReceipt(body: { account_id: number; ar_ids: number[]; remark?: string }) {
  return apiFetch<ReceiptDoc>('/finance/receipts', { method: 'POST', body: JSON.stringify(body) })
}

export function postReceipt(id: number) {
  return apiFetch<ReceiptDoc>(`/finance/receipts/${id}/post`, { method: 'POST' })
}

export function fetchReceipts() {
  return apiFetch<{ items: ReceiptDoc[] }>('/finance/receipts')
}

export function fetchAccounts() {
  return apiFetch<{ items: CashAccount[] }>('/finance/accounts')
}

export function fetchLedgers(account_id?: number) {
  const qs = account_id != null ? `?account_id=${account_id}` : ''
  return apiFetch<{ items: Array<Record<string, unknown>> }>(`/finance/ledgers${qs}`)
}

export function cashierManual(body: { account_id: number; amount: number; remark?: string }) {
  return apiFetch('/finance/cashier/manual', { method: 'POST', body: JSON.stringify(body) })
}

export function cashierReimburse(body: { account_id: number; amount: number; payee?: string; remark?: string }) {
  return apiFetch('/finance/cashier/reimbursement', { method: 'POST', body: JSON.stringify(body) })
}

export function cashierTransfer(body: {
  from_account_id: number
  to_account_id: number
  amount: number
  remark?: string
}) {
  return apiFetch('/finance/cashier/transfer', { method: 'POST', body: JSON.stringify(body) })
}

export function createInvoice(body: Record<string, unknown>) {
  return apiFetch('/finance/invoices', { method: 'POST', body: JSON.stringify(body) })
}

export function createBill(body: Record<string, unknown>) {
  return apiFetch('/finance/bills', { method: 'POST', body: JSON.stringify(body) })
}
