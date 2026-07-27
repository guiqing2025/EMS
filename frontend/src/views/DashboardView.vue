<template>
  <div class="erp-content exec-scroll">
  <div class="exec-page">
    <header class="exec-hero">
      <div class="exec-hero-copy">
        <p class="exec-eyebrow">鼎雄电子 · 经营数据看板</p>
        <h1>客户出货对照</h1>
        <p class="exec-sub">
          菲利斯、恩玖、永联、亿兰科 · 全年按月
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
        :class="'theme-' + c.customer_id"
      >
        <div class="customer-kpi-title">{{ c.customer_name }}</div>
        <div class="customer-kpi-row">
          <article class="kpi-card kpi-dark">
            <div class="kpi-label">全年累计出货</div>
            <div class="kpi-value">{{ formatQty(c.year_qty) }}</div>
            <div class="kpi-amount">{{ formatAmount(c.year_amount) }}</div>
            <div class="kpi-hint">PCS · 含税 · {{ yearStartLabel }} 起</div>
          </article>
          <article class="kpi-card kpi-accent">
            <div class="kpi-label">本月出货</div>
            <div class="kpi-value">{{ formatQty(c.this_month_qty) }}</div>
            <div class="kpi-amount">{{ formatAmount(c.this_month_amount) }}</div>
            <div class="kpi-hint">PCS · 含税 · {{ board?.this_month || '—' }} 截至今日</div>
          </article>
          <article class="kpi-card">
            <div class="kpi-label">金额环比</div>
            <div class="kpi-value" :class="c.momClass">{{ c.momText }}</div>
            <div class="kpi-hint">本月相对上月（按金额）</div>
          </article>
        </div>
      </div>
    </section>

    <section class="exec-charts">
      <div class="chart-panel chart-wide">
        <div class="panel-head">
          <h2>出货对比（分客户 · 全年按月）</h2>
          <p>四家客户各自按月出货数量，自 {{ yearStartLabel }} 起固定 1–12 月（未到月份为 0）</p>
        </div>
        <div ref="compareRef" class="chart-box chart-box-lg" />
      </div>
      <div class="model-top-grid">
        <div
          v-for="c in boardCustomers"
          :key="'top-' + c.customer_id"
          class="chart-panel"
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
      <div v-for="c in boardCustomers" :key="c.customer_id" class="table-panel">
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
      顶部 KPI 与对比图按全年月度累计（自 {{ yearStartLabel }}）；机型 TOP / 明细仍为上月 vs 本月。
      永联/亿兰科暂无日收货流水时，按订单累计收货挂采购月估算。
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

const compareRef = ref<HTMLDivElement | null>(null)
const modelChartEls = ref<Record<string, HTMLDivElement | null>>({})
let compareChart: echarts.ECharts | null = null
const modelCharts: Record<string, echarts.ECharts | null> = {}

const CUSTOMER_COLORS: Record<string, string> = {
  feilisi: '#0369a1',
  enjiu: '#0f766e',
  yonglian: '#b45309',
  yilanke: '#1d4ed8',
}

const DEFAULT_CUSTOMERS: ReceiveBoardCustomer[] = [
  { customer_id: 'feilisi', customer_name: '菲利斯', last_month_total: 0, this_month_total: 0, last_month_amount: 0, this_month_amount: 0, models: [] },
  { customer_id: 'enjiu', customer_name: '恩玖·鼎雄', last_month_total: 0, this_month_total: 0, last_month_amount: 0, this_month_amount: 0, models: [] },
  { customer_id: 'yonglian', customer_name: '永联', last_month_total: 0, this_month_total: 0, last_month_amount: 0, this_month_amount: 0, models: [] },
  { customer_id: 'yilanke', customer_name: '亿兰科', last_month_total: 0, this_month_total: 0, last_month_amount: 0, this_month_amount: 0, models: [] },
]

const boardCustomers = computed<ReceiveBoardCustomer[]>(
  () => board.value?.customers?.length ? board.value.customers : DEFAULT_CUSTOMERS,
)

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

function monthlySeriesFor(customerId: string) {
  const row = board.value?.monthly?.customers?.find((c) => c.customer_id === customerId)
  return row?.series ?? []
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

const yearCustomerKpis = computed(() =>
  boardCustomers.value.map((c) => {
    const series = monthlySeriesFor(c.customer_id)
    const yearQty = series.reduce((s, p) => s + (p.qty || 0), 0)
    const yearAmount = series.reduce((s, p) => s + (p.amount || 0), 0)
    const thisYm = board.value?.this_month || ''
    const lastYm = board.value?.last_month || ''
    const thisPt = series.find((p) => p.month === thisYm)
    const lastPt = series.find((p) => p.month === lastYm)
    const thisQty = thisPt?.qty ?? c.this_month_total ?? 0
    const thisAmount = thisPt?.amount ?? c.this_month_amount ?? 0
    const lastAmount = lastPt?.amount ?? c.last_month_amount ?? 0
    return {
      customer_id: c.customer_id,
      customer_name: c.customer_name,
      year_qty: yearQty,
      year_amount: yearAmount,
      this_month_qty: thisQty,
      this_month_amount: thisAmount,
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
    await nextTick()
    renderCharts()
  } catch (e) {
    boardError.value = e instanceof ApiError ? e.message : '加载收货看板失败'
  } finally {
    boardLoading.value = false
  }
}

function ensureCharts() {
  if (compareRef.value && !compareChart) compareChart = echarts.init(compareRef.value)
  for (const c of boardCustomers.value) {
    const el = modelChartEls.value[c.customer_id]
    if (el && !modelCharts[c.customer_id]) {
      modelCharts[c.customer_id] = echarts.init(el)
    }
  }
}

function customerById(id: string) {
  return boardCustomers.value.find((c) => c.customer_id === id)
}

function monthShort(ym: string) {
  const m = Number(String(ym).slice(5, 7))
  return Number.isFinite(m) && m > 0 ? `${m}月` : ym
}

function renderCharts() {
  ensureCharts()
  const months = monthLabels.value
  const labels = months.map(monthShort)
  const seriesList = boardCustomers.value.map((c, idx) => {
    const series = monthlySeriesFor(c.customer_id)
    const map = new Map(series.map((p) => [p.month, p]))
    const qty = months.map((ym) => map.get(ym)?.qty || 0)
    const amt = months.map((ym) => map.get(ym)?.amount || 0)
    const color = customerColor(c.customer_id)
    return {
      name: shortName(c.customer_name),
      customer_id: c.customer_id,
      qty,
      amt,
      color,
      idx,
    }
  })

  compareChart?.setOption(
    {
      color: seriesList.map((s) => s.color),
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'line' },
        formatter: (params: unknown) => {
          const rows = Array.isArray(params) ? params : []
          if (!rows.length) return ''
          const idx = Number((rows[0] as { dataIndex?: number }).dataIndex ?? 0)
          const ym = months[idx] || ''
          const head = `<div style="margin-bottom:4px;font-weight:600">${ym}</div>`
          const body = rows
            .map((r) => {
              const item = r as { seriesName?: string; color?: string; value?: number; seriesIndex?: number }
              const si = Number(item.seriesIndex ?? 0)
              const qty = Number(item.value || 0)
              const amt = seriesList[si]?.amt[idx] || 0
              return `<div style="display:flex;gap:10px;justify-content:space-between">
                <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${item.color};margin-right:6px"></span>${item.seriesName || ''}</span>
                <span>${formatQty(qty)} PCS · ${formatAmount(amt)}</span>
              </div>`
            })
            .join('')
          return head + body
        },
      },
      legend: {
        top: 0,
        right: 0,
        textStyle: { color: '#64748b' },
      },
      grid: { left: 52, right: 24, top: 40, bottom: 28 },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: labels.length ? labels : ['—'],
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#cbd5e1' } },
        axisLabel: { color: '#334155', fontWeight: 600, fontSize: 12 },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } },
        axisLabel: {
          color: '#94a3b8',
          formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(v)),
        },
      },
      series: seriesList.map((s) => ({
        name: s.name,
        type: 'line',
        smooth: false,
        symbol: 'circle',
        symbolSize: 7,
        showSymbol: true,
        lineStyle: { width: 2.5, color: s.color },
        itemStyle: { color: s.color, borderColor: '#fff', borderWidth: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: s.color + '33' },
            { offset: 1, color: s.color + '05' },
          ]),
        },
        data: s.qty,
      })),
    },
    true,
  )

  for (const c of boardCustomers.value) {
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
          itemStyle: { borderRadius: 4, color: '#cbd5e1' },
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

watch(boardCustomers, async () => {
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
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 16px;
}

/* 四列需足够宽，否则金额会被裁切；中等屏保持 2×2 */
@media (min-width: 1680px) {
  .exec-customer-kpis {
    grid-template-columns: repeat(4, 1fr);
  }
}

.customer-kpi-block {
  border-radius: 16px;
  padding: 12px;
  min-width: 0;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--exec-line);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.04);
}

.customer-kpi-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--exec-navy);
  margin-bottom: 10px;
  padding-left: 10px;
  border-left: 3px solid var(--exec-teal);
}

.theme-feilisi .customer-kpi-title {
  border-left-color: #0369a1;
}

.theme-enjiu .customer-kpi-title {
  border-left-color: #0f766e;
}

.theme-yonglian .customer-kpi-title {
  border-left-color: #b45309;
}

.theme-yilanke .customer-kpi-title {
  border-left-color: #1d4ed8;
}

.customer-kpi-row {
  display: grid;
  /* 累计/本月略宽，环比稍窄，保证金额一眼看全 */
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1.25fr) minmax(72px, 0.75fr);
  gap: 8px;
}

.kpi-card {
  position: relative;
  overflow: hidden;
  border-radius: 12px;
  padding: 10px 8px 8px;
  min-width: 0;
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

.kpi-accent {
  background: linear-gradient(145deg, #0f766e 0%, #115e59 100%);
  border-color: transparent;
  color: #fff;
}

.theme-feilisi .kpi-accent {
  background: linear-gradient(145deg, #0369a1 0%, #0c4a6e 100%);
}

.theme-yonglian .kpi-accent {
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

.kpi-label {
  font-size: 11px;
  color: var(--exec-muted);
  font-weight: 600;
  line-height: 1.3;
}

.kpi-value {
  margin-top: 6px;
  font-size: 17px;
  font-weight: 760;
  letter-spacing: -0.04em;
  line-height: 1.2;
  color: var(--exec-ink);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: clip;
  max-width: 100%;
}

.kpi-amount {
  margin-top: 4px;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: -0.03em;
  line-height: 1.3;
  font-variant-numeric: tabular-nums;
  color: var(--exec-ink);
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-all;
  max-width: 100%;
}

.kpi-value.up {
  color: #047857;
}

.kpi-value.down {
  color: #b45309;
}

.kpi-hint {
  margin-top: 5px;
  font-size: 11px;
  line-height: 1.35;
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

.panel-head {
  margin-bottom: 4px;
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

.chart-box {
  height: 280px;
  width: 100%;
}

.chart-box-lg {
  height: 340px;
}

.chart-box-model {
  height: 300px;
}

.exec-tables {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
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
    height: 380px;
  }
  .chart-box-model {
    height: 340px;
  }
}

@media (max-width: 1200px) {
  .exec-customer-kpis,
  .model-top-grid,
  .exec-tables,
  .customer-kpi-row {
    grid-template-columns: 1fr;
  }
  .chart-box-lg,
  .chart-box-model {
    height: 280px;
  }
}
</style>
