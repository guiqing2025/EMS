<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">订单流程</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            以销售订单为主轴，按流程图顺序下推：确认 → MRP → 三线 → 出库发货 → 应收
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-select
            v-model="soId"
            filterable
            remote
            clearable
            placeholder="选择销售订单"
            style="width: 320px"
            :remote-method="searchSo"
            :loading="listLoading"
            @change="onSelectSo"
          >
            <el-option
              v-for="s in soOptions"
              :key="s.id"
              :label="`${s.so_no} · ${s.customer_name || '—'} · ${s.status}`"
              :value="s.id"
            />
          </el-select>
          <el-button :disabled="!soId" :loading="loading" @click="loadChain">刷新进度</el-button>
        </div>
      </div>

      <div v-if="chain" class="erp-page-body">
        <div class="flow-head">
          <div>
            <strong>{{ chain.so_no }}</strong>
            <span style="margin-left: 12px; color: var(--erp-text-muted)">{{ chain.customer_name }}</span>
            <el-tag size="small" style="margin-left: 8px">{{ chain.status }}</el-tag>
            <span style="margin-left: 12px; font-size: 13px">出货 {{ chain.shipped_qty }}/{{ chain.qty }}</span>
          </div>
          <div class="flow-actions">
            <template v-for="(a, idx) in chain.next_actions" :key="a.code + idx">
              <el-button
                v-if="a.code !== 'hint_bind_bom'"
                type="primary"
                :loading="pushing === a.code"
                @click="onPush(a)"
              >
                {{ a.label }}
              </el-button>
              <el-button v-else type="warning" @click="$router.push(a.navigate || '/sales/orders')">
                {{ a.label }}
              </el-button>
            </template>
            <span v-if="!chain.next_actions.length" style="color: var(--erp-text-muted); font-size: 13px">
              {{ chain.pmc_hint }}
            </span>
          </div>
        </div>

        <div class="flow-steps">
          <div
            v-for="(st, i) in chain.steps"
            :key="st.key"
            class="flow-step"
            :class="`is-${st.status}`"
          >
            <div class="flow-step-index">{{ i + 1 }}</div>
            <div class="flow-step-body">
              <div class="flow-step-title">
                {{ st.title }}
                <el-tag size="small" :type="tagType(st.status)">{{ statusLabel(st.status) }}</el-tag>
              </div>
              <div v-if="st.hint" class="flow-step-hint">{{ st.hint }}</div>
              <div v-if="st.docs.length" class="flow-docs">
                <el-tag
                  v-for="d in st.docs"
                  :key="d.kind + d.id"
                  size="small"
                  class="flow-doc"
                  @click="goDoc(d)"
                >
                  {{ d.no }} · {{ d.status }}
                </el-tag>
              </div>
              <div v-else class="flow-step-hint">暂无单据</div>
            </div>
            <div v-if="i < chain.steps.length - 1" class="flow-arrow">→</div>
          </div>
        </div>
      </div>
      <div v-else class="erp-page-body">
        <p style="color: var(--erp-text-muted)">请先选择一张销售订单，按流程图顺序推进。</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchFlowChain,
  fetchSalesOrders,
  pushFlowStep,
  type FlowAction,
  type FlowChain,
  type SalesOrder,
} from '@/api/sales'

const route = useRoute()
const router = useRouter()

const soId = ref<number | undefined>()
const soOptions = ref<SalesOrder[]>([])
const listLoading = ref(false)
const loading = ref(false)
const pushing = ref('')
const chain = ref<FlowChain | null>(null)

function tagType(s: string) {
  if (s === 'done') return 'success'
  if (s === 'active') return 'warning'
  if (s === 'skipped') return 'info'
  return ''
}

function statusLabel(s: string) {
  return ({ pending: '未开始', active: '进行中', done: '已完成', skipped: '可跳过' } as Record<string, string>)[s] || s
}

async function searchSo(q: string) {
  listLoading.value = true
  try {
    soOptions.value = (await fetchSalesOrders({ q: q || '' })).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    listLoading.value = false
  }
}

async function loadChain() {
  if (!soId.value) {
    chain.value = null
    return
  }
  loading.value = true
  try {
    chain.value = await fetchFlowChain(soId.value)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载流程失败')
  } finally {
    loading.value = false
  }
}

function onSelectSo() {
  if (soId.value) {
    router.replace({ query: { ...route.query, so_id: String(soId.value) } })
  }
  void loadChain()
}

async function onPush(a: FlowAction) {
  if (!soId.value || a.code === 'hint_bind_bom') return
  pushing.value = a.code
  try {
    const body: Record<string, number | string> = {}
    if (a.plan_id) body.plan_id = a.plan_id
    if (a.issue_id) body.issue_id = a.issue_id
    if (a.delivery_id) body.delivery_id = a.delivery_id
    const res = await pushFlowStep(soId.value, a.code, body)
    ElMessage.success(res.message || '已下推')
    chain.value = res.chain
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下推失败')
  } finally {
    pushing.value = ''
  }
}

function goDoc(d: { kind: string; id: number }) {
  const map: Record<string, string> = {
    sales_order: '/sales/orders',
    inquiry: '/sales/flow',
    quote: '/sales/flow',
    purchase_plan: '/planning',
    production_plan: '/planning',
    outsource_plan: '/planning',
    purchase_order: '/purchase/orders',
    production_order: '/production/orders',
    outsource_order: '/outsource/orders',
    sales_issue: '/shipping/sales-issue',
    delivery: '/shipping/delivery',
    ar: '/finance/ar',
  }
  const path = map[d.kind]
  if (path) router.push({ path, query: { id: String(d.id), so_id: String(soId.value || '') } })
}

onMounted(async () => {
  await searchSo('')
  const qid = Number(route.query.so_id || 0)
  if (qid) {
    soId.value = qid
    if (!soOptions.value.some((s) => s.id === qid)) {
      try {
        const one = (await fetchSalesOrders({})).items?.find((s) => s.id === qid)
        if (one) soOptions.value = [one, ...soOptions.value]
      } catch {
        /* ignore */
      }
    }
    await loadChain()
  }
})

watch(
  () => route.query.so_id,
  async (v) => {
    const id = Number(v || 0)
    if (id && id !== soId.value) {
      soId.value = id
      await loadChain()
    }
  },
)
</script>

<style scoped>
.flow-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.flow-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.flow-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: stretch;
}
.flow-step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 160px;
  max-width: 220px;
  flex: 1;
}
.flow-step-index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #334155;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
  flex-shrink: 0;
}
.flow-step.is-active .flow-step-index {
  background: #f59e0b;
  color: #fff;
}
.flow-step.is-done .flow-step-index {
  background: #059669;
  color: #fff;
}
.flow-step.is-skipped .flow-step-index {
  background: #94a3b8;
  color: #fff;
}
.flow-step-body {
  flex: 1;
  min-width: 0;
}
.flow-step-title {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.flow-step-hint {
  font-size: 12px;
  color: var(--erp-text-muted);
  margin-top: 4px;
}
.flow-docs {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
}
.flow-doc {
  cursor: pointer;
  justify-content: flex-start;
}
.flow-arrow {
  align-self: center;
  color: #94a3b8;
  font-size: 18px;
  padding: 0 2px;
}
@media (max-width: 900px) {
  .flow-arrow {
    display: none;
  }
  .flow-step {
    max-width: none;
    width: 100%;
  }
}
</style>
