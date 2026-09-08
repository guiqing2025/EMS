<template>
  <div class="erp-content exec-scroll">
  <div class="exec-page">
    <header class="exec-hero">
      <div class="exec-hero-copy">
        <p class="exec-eyebrow">鼎雄电子 · 经营数据看板</p>
        <h1>客户出货对照</h1>
        <p class="exec-sub">
          菲利斯、恩玖为主 · 永联·亿兰科合并 · 全年按月
          <template v-if="board">
            · 截止 {{ board.as_of }}
            · 自 {{ yearStartLabel }} 至 {{ yearEndLabel }}
          </template>
        </p>
      </div>
      <div class="exec-hero-actions">
        <el-button :loading="boardLoading" @click="loadBoard">刷新数据</el-button>
        <el-button type="primary" @click="router.push('/orders')">订单列表</el-button>
      </div>
    </header>

    <el-alert
      v-if="boardError"
      :title="boardError"
      type="error"
      show-icon
      :closable="false"
      class="exec-alert"
    />

    <section v-loading="boardLoading" class="exec-customer-kpis">
      <div
        v-for="c in yearCustomerKpis"
        :key="c.customer_id"
        class="customer-kpi-block"
        :class="['theme-' + c.customer_id, { 'customer-kpi-block--merged': c.customer_id === MERGED_ID }]"
      >
        <div class="customer-kpi-title">{{ c.customer_name }}</div>
        <div class="customer-kpi-row">
          <article class="kpi-card kpi-dark">
            <div class="kpi-label">全年累计出货</div>
            <div class="kpi-value">{{ formatQty(c.year_qty) }}</div>
            <div class="kpi-amount">{{ formatAmount(c.year_amount) }}</div>
            <div class="kpi-hint">PCS · 含税 · {{ yearStartLabel }} 起</div>
          </article>
          <article class="kpi-card kpi-last">
            <div class="kpi-label">上月出货</div>
            <div class="kpi-value">{{ formatQty(c.last_month_qty) }}</div>
            <div class="kpi-amount">{{ formatAmount(c.last_month_amount) }}</div>
            <div class="kpi-hint">PCS · 含税 · {{ board?.last_month || '—' }} 整月</div>
          </article>
          <article class="kpi-card kpi-accent">
            <div class="kpi-label">本月出货</div>
            <div class="kpi-value">{{ formatQty(c.this_month_qty) }}</div>
            <div class="kpi-amount">{{ formatAmount(c.this_month_amount) }}</div>
            <div class="kpi-hint">PCS · 含税 · {{ board?.this_month || '—' }} 截至今日</div>
          </article>
          <article class="kpi-card kpi-order">
            <div class="kpi-label">当月接单</div>
            <div class="kpi-value">{{ formatAmount(c.this_month_order_amount) }}</div>
            <div class="kpi-amount">{{ formatQty(c.this_month_order_qty) }} PCS</div>
            <div class="kpi-hint">含税 · 采购日在 {{ board?.this_month || '—' }}</div>
          </article>
          <article class="kpi-card kpi-mom">
            <div class="kpi-label">金额环比</div>
            <div class="kpi-value" :class="c.momClass">{{ c.momText }}</div>
            <div class="kpi-hint">本月相对上月（按出货金额）</div>
          </article>
        </div>
      </div>
    </section>

    <section class="exec-charts">
      <div class="chart-panel chart-wide chart-trend-dark">
        <div class="panel-head panel-head-row">
          <div>
            <h2>出货对照月趋势图</h2>
            <p>分客户折线 + 月合计柱 · 按出货金额 · 自 {{ yearStartLabel }} 起按月（未到月份为 0）</p>
          </div>
          <el-button class="ai-insight-btn" size="small" @click="openAiInsight">
            AI 解读
            <span class="ai-beta">本地</span>
          </el-button>
        </div>
        <div ref="compareRef" class="chart-box chart-box-lg" />
      </div>

      <el-dialog
        v-model="aiVisible"
        title="AI 解读 · 出货月趋势"
        width="520px"
        append-to-body
        destroy-on-close
      >
        <div class="ai-insight-body">
          <p v-for="(line, i) in aiLines" :key="i">{{ line }}</p>
          <p v-if="aiNote" class="ai-note">{{ aiNote }}</p>
        </div>
        <template #footer>
          <el-button type="primary" @click="aiVisible = false">知道了</el-button>
        </template>
      </el-dialog>
      <div class="model-top-grid">
        <div
          v-for="c in displayCustomers"
          :key="'top-' + c.customer_id"
          class="chart-panel"
          :class="{ 'chart-panel--merged': c.customer_id === MERGED_ID }"
        >
          <div class="panel-head">
            <h2>{{ shortName(c.customer_name) }} · 机型 TOP</h2>
            <p>上月 vs 本月 · 按本月出货量排序</p>
          </div>
          <div :ref="(el) => setModelChartRef(c.customer_id, el)" class="chart-box chart-box-model" />
        </div>
      </div>
    </section>

    <section class="exec-tables">
      <div
        v-for="c in displayCustomers"
        :key="c.customer_id"
        class="table-panel"
        :class="{ 'table-panel--merged': c.customer_id === MERGED_ID }"
      >
        <div class="panel-head">
          <h2>{{ c.customer_name }} · 机型明细</h2>
          <p>
            上月出货 {{ formatQty(c.last_month_total) }}
            · {{ formatAmount(c.last_month_amount) }}
            · 本月出货 {{ formatQty(c.this_month_total) }}
            · {{ formatAmount(c.this_month_amount) }}
          </p>
        </div>
        <el-table
          :data="c.models"
          size="small"
          stripe
          empty-text="暂无出货数据"
          style="width: 100%"
          max-height="420"
        >
          <el-table-column prop="model_code" label="机型料号" min-width="130" show-overflow-tooltip />
          <el-table-column prop="model_name" label="品名" min-width="100" show-overflow-tooltip />
          <el-table-column label="上月数量" width="100" align="right">
            <template #default="{ row }">{{ formatQty(row.last_month_qty) }}</template>
          </el-table-column>
          <el-table-column label="上月金额" width="110" align="right">
            <template #default="{ row }">{{ formatAmount(row.last_month_amount) }}</template>
          </el-table-column>
          <el-table-column label="本月数量" width="100" align="right">
            <template #default="{ row }">{{ formatQty(row.this_month_qty) }}</template>
          </el-table-column>
          <el-table-column label="本月金额" width="110" align="right">
            <template #default="{ row }">{{ formatAmount(row.this_month_amount) }}</template>
          </el-table-column>
          <el-table-column label="环比" width="90" align="right">
            <template #default="{ row }">
              <span :class="deltaClass(row.last_month_qty, row.this_month_qty)">
                {{ deltaText(row.last_month_qty, row.this_month_qty) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <p class="exec-footnote">
      口径：客户 SRM 确认收货记为我方出货；金额按订单行含税单价（tax_amount÷订单量）×出货数量；
      当月接单按采购日落在本月的订单含税金额汇总；
      顶部 KPI 与对比图按全年月度累计（自 {{ yearStartLabel }}）；机型 TOP / 明细仍为上月 vs 本月。
      永联与亿兰科在看板中合并展示；暂无日收货流水时，按订单累计收货挂采购月估算。
    </p>
  </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fetchReceiveBoard, type ReceiveBoard, type ReceiveBoardCustomer } from '@/api/dashboard'
import { ApiError } from '@/api/http'

echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const router = useRouter()
const board = ref<ReceiveBoard | null>(null)
const boardLoading = ref(false)
const boardError = ref('')
const aiVisible = ref(false)
const aiLines = ref<string[]>([])
const aiNote = ref('')

const compareRef = ref<HTMLDivElement | null>(null)
const modelChartEls = ref<Record<string, HTMLDivElement | null>>({})
let compareChart: echarts.ECharts | null = null
const modelCharts: Record<string, echarts.ECharts | null> = {}

/** KPI / 机型 TOP 用客户色 */
const CUSTOMER_COLORS: Record<string, string> = {
  feilisi: '#0369a1',
  enjiu: '#0f766e',
  yonglian: '#b45309',
  yilanke: '#1d4ed8',
  yonglian_yilanke: '#b45309',
}
/** 月趋势图：浅色高对比（侧栏主色底上拉开色相） */
const CHART_SERIES_COLORS: Record<string, string> = {
  feilisi: '#ffffff',
  enjiu: '#bbf7d0',
  yonglian: '#fb923c',
  yilanke: '#e879f9',
  yonglian_yilanke: '#fde68a',
}
/** 月合计柱：琥珀，与折线明显区分 */
// 实色淡金：半透明叠蓝底会发灰，勿用低透明度 rgba
const TOTAL_BAR_COLOR = '#fcd34d'
const TOTAL_BAR_COLOR_DIM = '#f59e0b'

/** 看板展示：永联 + 亿兰科合并为一组 */
const MERGED_ID = 'yonglian_yilanke'
const MERGED_NAME = '永联·亿兰科'
const MERGE_SOURCE_IDS = ['yonglian', 'yilanke'] as const

const DEFAULT_CUSTOMERS: ReceiveBoardCustomer[] = [
  { customer_id: 'feilisi', customer_name: '菲利斯', last_month_total: 0, this_month_total: 0, last_month_amount: 0, this_month_amount: 0, this_month_order_qty: 0, this_month_order_amount: 0, models: [] },
  { customer_id: 'enjiu', customer_name: '恩玖·鼎雄', last_month_total: 0, this_month_total: 0, last_month_amount: 0, this_month_amount: 0, this_month_order_qty: 0, this_month_order_amount: 0, models: [] },
  { customer_id: 'yonglian', customer_name: '永联', last_month_total: 0, this_month_total: 0, last_month_amount: 0, this_month_amount: 0, this_month_order_qty: 0, this_month_order_amount: 0, models: [] },
  { customer_id: 'yilanke', customer_name: '亿兰科', last_month_total: 0, this_month_total: 0, last_month_amount: 0, this_month_amount: 0, this_month_order_qty: 0, this_month_order_amount: 0, models: [] },
]

const boardCustomers = computed<ReceiveBoardCustomer[]>(
  () => board.value?.customers?.length ? board.value.customers : DEFAULT_CUSTOMERS,
)

function mergeModels(lists: ReceiveBoardCustomer['models'][]): ReceiveBoardCustomer['models'] {
  const map = new Map<string, ReceiveBoardCustomer['models'][number]>()
  for (const list of lists) {
    for (const m of list || []) {
      const key = String(m.model_code || m.model_name || '').trim() || `_anon_${map.size}`
      const prev = map.get(key)
      if (!prev) {
        map.set(key, { ...m })
        continue
      }
      map.set(key, {
        model_code: prev.model_code || m.model_code,
        model_name: prev.model_name || m.model_name,
        last_month_qty: (prev.last_month_qty || 0) + (m.last_month_qty || 0),
        this_month_qty: (prev.this_month_qty || 0) + (m.this_month_qty || 0),
        last_month_amount: (prev.last_month_amount || 0) + (m.last_month_amount || 0),
        this_month_amount: (prev.this_month_amount || 0) + (m.this_month_amount || 0),
      })
    }
  }
  return [...map.values()].sort((a, b) => (b.this_month_qty || 0) - (a.this_month_qty || 0))
}

/** 看板展示用客户列表：菲利斯、恩玖单独；永联+亿兰科合并 */
const displayCustomers = computed<ReceiveBoardCustomer[]>(() => {
  const byId = new Map(boardCustomers.value.map((c) => [c.customer_id, c]))
  const out: ReceiveBoardCustomer[] = []
  for (const id of ['feilisi', 'enjiu'] as const) {
    const c = byId.get(id)
    out.push(
      c || {
        customer_id: id,
        customer_name: id === 'feilisi' ? '菲利斯' : '恩玖·鼎雄',
        last_month_total: 0,
        this_month_total: 0,
        last_month_amount: 0,
        this_month_amount: 0,
        this_month_order_qty: 0,
        this_month_order_amount: 0,
        models: [],
      },
    )
  }
  const parts = MERGE_SOURCE_IDS.map((id) => byId.get(id)).filter(Boolean) as ReceiveBoardCustomer[]
  out.push({
    customer_id: MERGED_ID,
    customer_name: MERGED_NAME,
    last_month_total: parts.reduce((s, c) => s + (c.last_month_total || 0), 0),
    this_month_total: parts.reduce((s, c) => s + (c.this_month_total || 0), 0),
    last_month_amount: parts.reduce((s, c) => s + (c.last_month_amount || 0), 0),
    this_month_amount: parts.reduce((s, c) => s + (c.this_month_amount || 0), 0),
    this_month_order_qty: parts.reduce((s, c) => s + (c.this_month_order_qty || 0), 0),
    this_month_order_amount: parts.reduce((s, c) => s + (c.this_month_order_amount || 0), 0),
    models: mergeModels(parts.map((c) => c.models || [])),
  })
  return out
})

function setModelChartRef(customerId: string, el: unknown) {
  modelChartEls.value[customerId] = (el as HTMLDivElement | null) || null
}

const yearStartLabel = computed(() => {
  const start = board.value?.monthly?.history_start || board.value?.monthly?.months?.[0] || '2026-01'
  return String(start).slice(0, 7)
})

/** 全年 X 轴：自 history_start 铺满至当年 12 月（API 缺月时前端补齐） */
const monthLabels = computed(() => {
  const raw = board.value?.monthly?.months ?? []
  const start = String(board.value?.monthly?.history_start || raw[0] || '2026-01').slice(0, 7)
  const y = Number(start.slice(0, 4))
  if (!Number.isFinite(y) || y < 2000) return raw
  const endY = Math.max(
    y,
    ...raw.map((ym) => Number(String(ym).slice(0, 4))).filter((n) => Number.isFinite(n)),
  )
  const out: string[] = []
  for (let year = y; year <= endY; year += 1) {
    for (let m = 1; m <= 12; m += 1) {
      const ym = `${year}-${String(m).padStart(2, '0')}`
      if (ym >= start) out.push(ym)
    }
  }
  return out.length ? out : raw
})

const yearEndLabel = computed(() => {
  const months = monthLabels.value
  if (months.length) return months[months.length - 1]
  const y = Number(String(yearStartLabel.value).slice(0, 4))
  return Number.isFinite(y) ? `${y}-12` : '—'
})

function monthlySeriesForRaw(customerId: string) {
  const row = board.value?.monthly?.customers?.find((c) => c.customer_id === customerId)
  return row?.series ?? []
}

function mergeMonthlySeries(
  a: { month: string; qty: number; amount: number }[],
  b: { month: string; qty: number; amount: number }[],
) {
  const map = new Map<string, { month: string; qty: number; amount: number }>()
  for (const p of [...a, ...b]) {
    const ym = String(p.month || '')
    if (!ym) continue
    const prev = map.get(ym)
    if (!prev) {
      map.set(ym, { month: ym, qty: p.qty || 0, amount: p.amount || 0 })
    } else {
      prev.qty += p.qty || 0
      prev.amount += p.amount || 0
    }
  }
  return [...map.values()].sort((x, y) => x.month.localeCompare(y.month))
}

function monthlySeriesFor(customerId: string) {
  if (customerId === MERGED_ID) {
    return mergeMonthlySeries(
      monthlySeriesForRaw('yonglian'),
      monthlySeriesForRaw('yilanke'),
    )
  }
  return monthlySeriesForRaw(customerId)
}

function momAmountText(last: number, cur: number) {
  if (!last) return cur > 0 ? '—' : '0%'
  const pct = ((cur - last) / last) * 100
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(1)}%`
}

function momAmountClass(last: number, cur: number) {
  if (!last) return ''
  const ratio = (cur - last) / last
  if (ratio > 0.001) return 'up'
  if (ratio < -0.001) return 'down'
  return ''
}

/** 顶部 KPI：四家客户各自一卡横排（与趋势图合并展示无关） */
const yearCustomerKpis = computed(() =>
  boardCustomers.value.map((c) => {
    const series = monthlySeriesForRaw(c.customer_id)
    const yearQty = series.reduce((s, p) => s + (p.qty || 0), 0)
    const yearAmount = series.reduce((s, p) => s + (p.amount || 0), 0)
    const thisYm = board.value?.this_month || ''
    const lastYm = board.value?.last_month || ''
    const thisPt = series.find((p) => p.month === thisYm)
    const lastPt = series.find((p) => p.month === lastYm)
    const thisQty = thisPt?.qty ?? c.this_month_total ?? 0
    const thisAmount = thisPt?.amount ?? c.this_month_amount ?? 0
    const lastQty = lastPt?.qty ?? c.last_month_total ?? 0
    const lastAmount = lastPt?.amount ?? c.last_month_amount ?? 0
    return {
      customer_id: c.customer_id,
      customer_name: c.customer_name,
      year_qty: yearQty,
      year_amount: yearAmount,
      last_month_qty: lastQty,
      last_month_amount: lastAmount,
      this_month_qty: thisQty,
      this_month_amount: thisAmount,
      this_month_order_qty: c.this_month_order_qty || 0,
      this_month_order_amount: c.this_month_order_amount || 0,
      momText: momAmountText(lastAmount, thisAmount),
      momClass: momAmountClass(lastAmount, thisAmount),
    }
  }),
)

function formatQty(n: number) {
  if (n == null || Number.isNaN(n)) return '0'
  return Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

function formatAmount(n: number) {
  if (n == null || Number.isNaN(n)) return '¥0'
  return `¥${Number(n).toLocaleString('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}`
}

function shortName(name: string) {
  return name.replace('·鼎雄', '')
}

function customerColor(id: string) {
  return CUSTOMER_COLORS[id] || '#64748b'
}

function chartSeriesColor(id: string) {
  return CHART_SERIES_COLORS[id] || CUSTOMER_COLORS[id] || '#94a3b8'
}

function deltaText(last: number, cur: number) {
  if (!last) return cur ? '新增' : '—'
  const pct = ((cur - last) / last) * 100
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(0)}%`
}

function deltaClass(last: number, cur: number) {
  if (!last) return cur ? 'up' : ''
  if (cur > last) return 'up'
  if (cur < last) return 'down'
  return ''
}

async function loadBoard() {
  boardLoading.value = true
  boardError.value = ''
  try {
    board.value = await fetchReceiveBoard()
    // 先出 KPI，图表放到下一帧，避免挡首屏
    boardLoading.value = false
    await nextTick()
    requestAnimationFrame(() => renderCharts())
  } catch (e) {
    boardError.value = e instanceof ApiError ? e.message : '加载收货看板失败'
    boardLoading.value = false
  }
}

function ensureCharts() {
  if (compareRef.value && !compareChart) compareChart = echarts.init(compareRef.value)
  for (const c of displayCustomers.value) {
    const el = modelChartEls.value[c.customer_id]
    if (el && !modelCharts[c.customer_id]) {
      modelCharts[c.customer_id] = echarts.init(el)
    }
  }
}

function customerById(id: string) {
  return displayCustomers.value.find((c) => c.customer_id === id)
}

function monthShort(ym: string) {
  return String(ym || '').slice(0, 7) || ym
}

function formatLabelQty(n: number) {
  if (!n) return '0'
  if (n >= 10000) return `${(n / 10000).toFixed(n % 10000 === 0 ? 0 : 1)}万`
  return formatQty(n)
}

function formatLabelAmount(n: number) {
  if (!n) return '¥0'
  if (n >= 10000) return `¥${(n / 10000).toFixed(n >= 100000 ? 1 : 2)}万`
  return formatAmount(n)
}

function buildAiInsight() {
  const months = monthLabels.value
  const thisYm = board.value?.this_month || months[months.length - 1] || ''
  const lastYm = board.value?.last_month || ''
  const idx = months.indexOf(thisYm)
  const lastIdx = lastYm ? months.indexOf(lastYm) : idx - 1
  if (idx < 0) {
    aiLines.value = ['暂无足够月度数据可解读。']
    aiNote.value = ''
    return
  }

  const lines: string[] = []
  let thisTotal = 0
  let lastTotal = 0
  const movers: { name: string; cur: number; prev: number; delta: number }[] = []

  for (const c of displayCustomers.value) {
    const series = monthlySeriesFor(c.customer_id)
    const map = new Map(series.map((p) => [p.month, p.amount || 0]))
    const cur = map.get(thisYm) || 0
    const prev = lastIdx >= 0 ? map.get(months[lastIdx]) || 0 : 0
    thisTotal += cur
    lastTotal += prev
    movers.push({ name: shortName(c.customer_name), cur, prev, delta: cur - prev })
  }

  const mom =
    lastTotal > 0
      ? `${(((thisTotal - lastTotal) / lastTotal) * 100).toFixed(1)}%`
      : thisTotal > 0
        ? '新增'
        : '持平'
  const momDir = thisTotal > lastTotal ? '上升' : thisTotal < lastTotal ? '回落' : '持平'
  lines.push(
    `${thisYm} 合计出货金额 ${formatAmount(thisTotal)}（菲利斯、恩玖、永联·亿兰科），相对上月（${lastYm || '—'}）${momDir}（${mom}）。`,
  )

  const ranked = [...movers].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
  const topUp = ranked.find((m) => m.delta > 0)
  const topDown = ranked.find((m) => m.delta < 0)
  if (topUp) {
    lines.push(`拉动最大：${topUp.name} 本月 ${formatAmount(topUp.cur)}，较上月 +${formatAmount(topUp.delta)}。`)
  }
  if (topDown) {
    lines.push(`回落最大：${topDown.name} 本月 ${formatAmount(topDown.cur)}，较上月 ${formatAmount(topDown.delta)}。`)
  }

  const zeros = movers.filter((m) => m.cur === 0)
  if (zeros.length) {
    lines.push(`本月尚无出货金额：${zeros.map((z) => z.name).join('、')}。`)
  }

  aiLines.value = lines
  aiNote.value = '说明：解读由看板本地根据出货金额生成，不调用外部模型，不影响产线扫码。'
}

function openAiInsight() {
  buildAiInsight()
  aiVisible.value = true
}

function renderCharts() {
  ensureCharts()
  const months = monthLabels.value
  const labels = months.map(monthShort)
  const seriesList = displayCustomers.value.map((c) => {
    const series = monthlySeriesFor(c.customer_id)
    const map = new Map(series.map((p) => [p.month, p]))
    const qty = months.map((ym) => map.get(ym)?.qty || 0)
    const amt = months.map((ym) => map.get(ym)?.amount || 0)
    const color = chartSeriesColor(c.customer_id)
    return {
      name: shortName(c.customer_name),
      customer_id: c.customer_id,
      qty,
      amt,
      color,
    }
  })
  const totalQty = months.map((_, i) => seriesList.reduce((s, row) => s + (row.qty[i] || 0), 0))
  const totalAmt = months.map((_, i) => seriesList.reduce((s, row) => s + (row.amt[i] || 0), 0))
  const palette = [...seriesList.map((s) => s.color), TOTAL_BAR_COLOR]

  compareChart?.setOption(
    {
      color: palette,
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255, 255, 255, 0.96)',
        borderColor: 'rgba(37, 99, 235, 0.25)',
        textStyle: { color: '#1e293b', fontSize: 12 },
        formatter: (params: unknown) => {
          const rows = Array.isArray(params) ? params : []
          if (!rows.length) return ''
          const idx = Number((rows[0] as { dataIndex?: number }).dataIndex ?? 0)
          const ym = months[idx] || ''
          const head = `<div style="margin-bottom:6px;font-weight:600">${ym}</div>`
          const body = rows
            .map((r) => {
              const item = r as {
                seriesName?: string
                color?: string
                value?: number
                seriesType?: string
              }
              const amt = Number(item.value || 0)
              const isBar = item.seriesType === 'bar' || item.seriesName === '月合计'
              const qty = isBar
                ? totalQty[idx] || 0
                : seriesList.find((s) => s.name === item.seriesName)?.qty[idx] || 0
              return `<div style="display:flex;gap:12px;justify-content:space-between;margin:2px 0">
                <span><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${item.color};margin-right:6px"></span>${item.seriesName || ''}</span>
                <span>${formatAmount(amt)} · ${formatQty(qty)} PCS</span>
              </div>`
            })
            .join('')
          return head + body
        },
      },
      legend: {
        top: 4,
        left: 'center',
        icon: 'roundRect',
        itemWidth: 12,
        itemHeight: 8,
        itemGap: 16,
        textStyle: { color: '#eff6ff', fontSize: 12 },
      },
      grid: { left: 64, right: 28, top: 48, bottom: 36 },
      xAxis: {
        type: 'category',
        boundaryGap: true,
        data: labels.length ? labels : ['—'],
        axisTick: { show: false },
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.35)' } },
        axisLabel: { color: '#eff6ff', fontWeight: 600, fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.2)', type: 'solid', width: 1 } },
        axisLabel: {
          color: 'rgba(239, 246, 255, 0.85)',
          formatter: (v: number) =>
            v >= 10000 ? `¥${(v / 10000).toFixed(1)}万` : v ? `¥${v}` : '¥0',
        },
      },
      series: [
        ...seriesList.map((s) => ({
          name: s.name,
          type: 'line' as const,
          smooth: false,
          symbol: 'circle',
          symbolSize: 8,
          showSymbol: true,
          z: 3,
          lineStyle: { width: 2.5, color: s.color },
          itemStyle: { color: s.color, borderColor: '#ffffff', borderWidth: 2 },
          label: {
            show: true,
            position: 'top',
            distance: 6,
            color: '#ffffff',
            fontSize: 10,
            fontWeight: 600,
            formatter: (p: { value?: number; seriesName?: string }) => {
              const v = Number(p.value || 0)
              if (!v) return ''
              return `${p.seriesName}: ${formatLabelAmount(v)}`
            },
          },
          labelLayout: { hideOverlap: true },
          data: s.amt,
        })),
        {
          name: '月合计',
          type: 'bar' as const,
          barMaxWidth: 36,
          z: 1,
          itemStyle: {
            borderRadius: [6, 6, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: TOTAL_BAR_COLOR },
              { offset: 1, color: TOTAL_BAR_COLOR_DIM },
            ]),
          },
          label: {
            show: true,
            position: 'top',
            distance: 4,
            color: '#fef3c7',
            fontSize: 10,
            fontWeight: 600,
            formatter: (p: { value?: number }) => {
              const v = Number(p.value || 0)
              if (!v) return ''
              return `月合计: ${formatLabelAmount(v)}`
            },
          },
          labelLayout: { hideOverlap: true },
          data: totalAmt,
        },
      ],
    },
    true,
  )

  for (const c of displayCustomers.value) {
    renderModelChart(modelCharts[c.customer_id] || null, customerById(c.customer_id), customerColor(c.customer_id))
  }
}

function renderModelChart(
  chart: echarts.ECharts | null,
  customer: ReceiveBoardCustomer | undefined,
  accent: string,
) {
  if (!chart) return
  const models = (customer?.models || []).slice(0, 8)
  const labels = models.map((m) => m.model_code).reverse()
  const last = models.map((m) => m.last_month_qty || 0).reverse()
  const cur = models.map((m) => m.this_month_qty || 0).reverse()

  chart.setOption(
    {
      color: ['#94a3b8', accent],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => formatQty(Number(v)),
      },
      legend: { top: 0, right: 0, textStyle: { color: '#64748b', fontSize: 11 } },
      grid: { left: 110, right: 28, top: 36, bottom: 16 },
      xAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } },
        axisLabel: {
          color: '#94a3b8',
          formatter: (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)),
        },
      },
      yAxis: {
        type: 'category',
        data: labels,
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { color: '#475569', fontSize: 11 },
      },
      series: [
        {
          name: '上月',
          type: 'bar',
          data: last,
          barWidth: 10,
          itemStyle: { borderRadius: 4, color: '#fcd34d' },
        },
        {
          name: '本月',
          type: 'bar',
          data: cur,
          barWidth: 10,
          itemStyle: {
            borderRadius: 4,
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: accent },
              { offset: 1, color: accent === '#0369a1' ? '#38bdf8' : '#2dd4bf' },
            ]),
          },
        },
      ],
    },
    true,
  )
}

function onResize() {
  compareChart?.resize()
  Object.values(modelCharts).forEach((c) => c?.resize())
}

watch(displayCustomers, async () => {
  await nextTick()
  renderCharts()
})

onMounted(async () => {
  window.addEventListener('resize', onResize)
  await loadBoard()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  compareChart?.dispose()
  Object.values(modelCharts).forEach((c) => c?.dispose())
  compareChart = null
  for (const k of Object.keys(modelCharts)) modelCharts[k] = null
})
</script>

<style scoped>
.exec-scroll.erp-content {
  height: calc(100vh - 52px);
  overflow: auto;
  padding: 0;
}

.exec-page {
  --exec-ink: #0f172a;
  --exec-muted: #64748b;
  --exec-line: rgba(15, 23, 42, 0.08);
  --exec-teal: #0f766e;
  --exec-navy: #0b1f33;
  min-height: 100%;
  padding: 20px 22px 40px;
  background:
    radial-gradient(1200px 480px at 8% -10%, rgba(20, 184, 166, 0.16), transparent 55%),
    radial-gradient(900px 420px at 100% 0%, rgba(14, 116, 144, 0.12), transparent 50%),
    linear-gradient(180deg, #eef3f7 0%, #f7f9fb 42%, #f3f5f7 100%);
}

.exec-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.exec-eyebrow {
  margin: 0 0 6px;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--exec-teal);
  font-weight: 700;
}

.exec-hero h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.15;
  font-weight: 760;
  color: var(--exec-navy);
  letter-spacing: -0.02em;
}

.exec-sub {
  margin: 8px 0 0;
  color: var(--exec-muted);
  font-size: 13px;
}

.exec-hero-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.exec-alert {
  margin-bottom: 14px;
}

.exec-customer-kpis {
  display: grid;
  /* 四家 2×2，避免一行挤十六格 */
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}

/* 顶部 KPI 已拆四家；合并样式仅保留兼容，不再占满整行 */
.customer-kpi-block--merged {
  grid-column: auto;
}

.customer-kpi-block {
  border-radius: 18px;
  padding: 16px 16px 14px;
  min-width: 0;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid var(--exec-line);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.05);
}

.customer-kpi-title {
  font-size: 16px;
  font-weight: 740;
  color: var(--exec-navy);
  margin-bottom: 12px;
  padding-left: 12px;
  border-left: 4px solid var(--exec-teal);
  letter-spacing: 0.01em;
}

.theme-feilisi .customer-kpi-title {
  border-left-color: #0369a1;
}

.theme-enjiu .customer-kpi-title {
  border-left-color: #0f766e;
}

.theme-yonglian .customer-kpi-title,
.theme-yonglian_yilanke .customer-kpi-title {
  border-left-color: #b45309;
}

.theme-yilanke .customer-kpi-title {
  border-left-color: #1d4ed8;
}

.customer-kpi-row {
  display: grid;
  /* 全年 · 上月 · 本月出货 · 当月接单 · 环比 */
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  align-items: stretch;
}

.kpi-card {
  position: relative;
  overflow: hidden;
  border-radius: 14px;
  padding: 14px 12px 12px;
  min-width: 0;
  min-height: 108px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--exec-line);
}

.kpi-dark {
  background: linear-gradient(145deg, #1e3a5f 0%, #0b1f33 100%);
  border-color: transparent;
  color: #fff;
}

.kpi-dark .kpi-label,
.kpi-dark .kpi-hint,
.kpi-dark .kpi-amount {
  color: rgba(255, 255, 255, 0.72);
}

.kpi-dark .kpi-value {
  color: #fff;
}

.kpi-dark .kpi-amount {
  color: rgba(255, 255, 255, 0.92);
}

/* 上月：中性灰蓝，夹在「全年深色」与「本月品牌色」之间，时间轴更清晰 */
.kpi-last {
  background: linear-gradient(145deg, #64748b 0%, #475569 100%);
  border-color: transparent;
  color: #fff;
}

.kpi-last .kpi-label,
.kpi-last .kpi-hint,
.kpi-last .kpi-amount {
  color: rgba(255, 255, 255, 0.78);
}

.kpi-last .kpi-value {
  color: #fff;
}

.kpi-last .kpi-amount {
  color: rgba(255, 255, 255, 0.95);
}

.kpi-accent {
  background: linear-gradient(145deg, #0f766e 0%, #115e59 100%);
  border-color: transparent;
  color: #fff;
}

.theme-feilisi .kpi-accent {
  background: linear-gradient(145deg, #0369a1 0%, #0c4a6e 100%);
}

.theme-yonglian .kpi-accent,
.theme-yonglian_yilanke .kpi-accent {
  background: linear-gradient(145deg, #b45309 0%, #92400e 100%);
}

.theme-yilanke .kpi-accent {
  background: linear-gradient(145deg, #1d4ed8 0%, #1e3a8a 100%);
}

.kpi-accent .kpi-label,
.kpi-accent .kpi-hint,
.kpi-accent .kpi-amount {
  color: rgba(255, 255, 255, 0.75);
}

.kpi-accent .kpi-value {
  color: #fff;
}

.kpi-accent .kpi-amount {
  color: rgba(255, 255, 255, 0.95);
}

.kpi-order {
  background: linear-gradient(145deg, #14532d 0%, #166534 55%, #15803d 100%);
  border-color: transparent;
  color: #fff;
}

.theme-feilisi .kpi-order {
  background: linear-gradient(145deg, #0f766e 0%, #0e7490 100%);
}

.theme-yonglian .kpi-order,
.theme-yonglian_yilanke .kpi-order {
  background: linear-gradient(145deg, #3f6212 0%, #4d7c0f 100%);
}

.theme-yilanke .kpi-order {
  background: linear-gradient(145deg, #1e3a8a 0%, #1d4ed8 100%);
}

.kpi-order .kpi-label,
.kpi-order .kpi-hint,
.kpi-order .kpi-amount {
  color: rgba(255, 255, 255, 0.78);
}

.kpi-order .kpi-value {
  color: #fff;
}

.kpi-order .kpi-amount {
  color: rgba(255, 255, 255, 0.95);
}

.kpi-mom {
  background: rgba(248, 250, 252, 0.95);
  border: 1px dashed rgba(15, 23, 42, 0.12);
  box-shadow: none;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.kpi-label {
  font-size: 12px;
  color: var(--exec-muted);
  font-weight: 650;
  line-height: 1.35;
}

.kpi-value {
  margin-top: 8px;
  font-size: 20px;
  font-weight: 760;
  letter-spacing: -0.03em;
  line-height: 1.15;
  color: var(--exec-ink);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.kpi-amount {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.3;
  font-variant-numeric: tabular-nums;
  color: var(--exec-ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.kpi-value.up {
  color: #047857;
}

.kpi-value.down {
  color: #b45309;
}

.kpi-hint {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.4;
  color: var(--exec-muted);
}

.exec-charts {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 14px;
}

.model-top-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.chart-panel--merged {
  grid-column: 1 / -1;
}

.chart-panel,
.table-panel {
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--exec-line);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.04);
  padding: 16px 16px 10px;
  min-width: 0;
}

.chart-wide {
  width: 100%;
}

.chart-trend-dark {
  /* 与系统侧栏同色（Element Plus 主色） */
  background: var(--el-color-primary);
  border-color: rgba(255, 255, 255, 0.22);
  box-shadow: 0 16px 40px rgba(64, 158, 255, 0.28);
}

.chart-trend-dark .panel-head h2 {
  color: #ffffff;
}

.chart-trend-dark .panel-head p {
  color: rgba(239, 246, 255, 0.88);
}

.panel-head {
  margin-bottom: 4px;
}

.panel-head-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.panel-head h2 {
  margin: 0;
  font-size: 15px;
  color: var(--exec-ink);
}

.panel-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--exec-muted);
}

.ai-insight-btn {
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.45) !important;
  background: rgba(255, 255, 255, 0.18) !important;
  color: #eff6ff !important;
  font-weight: 600;
}

.ai-insight-btn:hover {
  background: rgba(255, 255, 255, 0.28) !important;
  color: #ffffff !important;
  border-color: rgba(255, 255, 255, 0.65) !important;
}

.ai-beta {
  margin-left: 6px;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
  background: rgba(255, 255, 255, 0.28);
  color: #eff6ff;
}

.ai-insight-body {
  font-size: 14px;
  line-height: 1.7;
  color: #1f2937;
}

.ai-insight-body p {
  margin: 0 0 10px;
}

.ai-insight-body .ai-note {
  margin-top: 14px;
  font-size: 12px;
  color: #6b7280;
}

.chart-box {
  height: 280px;
  width: 100%;
}

.chart-box-lg {
  height: 400px;
}

.chart-box-model {
  height: 300px;
}

.exec-tables {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.table-panel--merged {
  grid-column: 1 / -1;
}

.up {
  color: #047857;
  font-weight: 600;
}

.down {
  color: #b45309;
  font-weight: 600;
}

.exec-footnote {
  margin: 16px 0 0;
  font-size: 12px;
  color: var(--exec-muted);
  line-height: 1.5;
}

@media (min-width: 1400px) {
  .chart-box-lg {
    height: 440px;
  }
  .chart-box-model {
    height: 340px;
  }
}

@media (max-width: 1200px) {
  .exec-customer-kpis {
    grid-template-columns: 1fr;
  }
  .customer-kpi-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .kpi-value {
    font-size: 18px;
  }
  .model-top-grid,
  .exec-tables {
    grid-template-columns: 1fr;
  }
  .chart-box-lg,
  .chart-box-model {
    height: 320px;
  }
  .panel-head-row {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (max-width: 720px) {
  .exec-customer-kpis {
    grid-template-columns: 1fr;
  }
  .customer-kpi-row {
    grid-template-columns: 1fr 1fr;
  }
  .kpi-card {
    min-height: 96px;
    padding: 12px 10px 10px;
  }
  .kpi-value {
    font-size: 17px;
  }
}
</style>
