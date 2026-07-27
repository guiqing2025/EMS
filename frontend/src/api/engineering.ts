import { apiFetch } from '@/api/http'

export async function fetchEngReviewPendingCount() {
  return apiFetch<{ unread: number; pending: number; todo_kind?: string; title?: string }>(
    '/engineering/review-inbox/count',
  )
}

export async function fetchMyTodos() {
  return apiFetch<{
    role: string
    todo_kind: string
    title: string
    hint: string
    count: number
    items: Array<Record<string, unknown>>
  }>('/engineering/todos')
}
