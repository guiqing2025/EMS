<template>
  <el-drawer
    v-model="visible"
    :title="title"
    size="780px"
    destroy-on-close
    @closed="emit('update:modelValue', false)"
  >
    <div v-loading="loading" class="mat-detail">
      <template v-if="detail">
        <div class="mat-detail-head">
          <div>
            <div class="mat-detail-code">{{ detail.material.material_code }}</div>
            <div class="mat-detail-name">{{ detail.material.material_name || '—' }}</div>
            <div v-if="detail.material.spec" class="cell-muted">{{ detail.material.spec }}</div>
          </div>
        </div>

        <el-row :gutter="12" class="mat-stats">
          <el-col :span="6">
            <div class="mat-stat">
              <span>当前库存</span>
              <strong :class="{ 'qty-negative': detail.summary.current_qty < 0 }">
                {{ fmtWhQty(detail.summary.current_qty) }}
              </strong>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="mat-stat">
              <span>盘点 + 来料</span>
              <strong>{{ fmtWhQty((detail.summary.excel_count_qty || 0) + (detail.summary.excel_in_qty || 0)) }}</strong>
              <div class="cell-muted">盘 {{ fmtWhQty(detail.summary.excel_count_qty) }} + 来 {{ fmtWhQty(detail.summary.excel_in_qty) }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="mat-stat">
              <span>可用</span>
              <strong>{{ fmtWhQty(detail.summary.available_qty) }}</strong>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="mat-stat">
              <span>库存状态</span>
              <strong :class="stockStatusClass">{{ stockStatusText }}</strong>
              <div v-if="detail.summary.excel_demand_qty != null" class="cell-muted">
                账本需求 {{ fmtWhQty(detail.summary.excel_demand_qty) }}
              </div>
            </div>
          </el-col>
        </el-row>

        <div class="mat-mini-stats cell-muted">
          累计进 {{ fmtWhQty(detail.summary.inbound_total) }} ·
          累计出 {{ fmtWhQty(detail.summary.outbound_total) }} ·
          关联订单 {{ detail.summary.order_count }} 个 ·
          明细 {{ detail.summary.movement_count }} 条
          <span v-if="detail.material.last_inbound_at">
            · 最近来料 {{ fmtDate(detail.material.last_inbound_at) }}
            {{ fmtWhQty(detail.material.last_inbound_qty) }}
          </span>
        </div>

        <WarehouseOperationForm :material-id="detail.material.id" @saved="reloadDetail" />

        <el-tabs v-model="innerTab">
          <el-tab-pane :label="`进出账 (${detail.movements.length})`" name="movements">
            <el-table v-if="detail.movements.length" :data="detail.movements" size="small" border stripe max-height="360">
              <el-table-column label="时间" width="155">
                <template #default="{ row }">{{ fmtDate(row.created_at) || row.doc_date || '—' }}</template>
              </el-table-column>
              <el-table-column label="类型" width="80">
                <template #default="{ row }">{{ row.movement_type_name || excelMovementLabel(row.movement_type) }}</template>
              </el-table-column>
              <el-table-column prop="order_no" label="订单号" min-width="110" show-overflow-tooltip />
              <el-table-column label="数量" width="72" align="right">
                <template #default="{ row }">{{ row.qty_delta > 0 ? '+' : '' }}{{ fmtWhQty(row.qty) }}</template>
              </el-table-column>
              <el-table-column label="给方" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.giver || '—' }}</template>
              </el-table-column>
              <el-table-column label="收方" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.receiver || '—' }}</template>
              </el-table-column>
              <el-table-column label="提交人" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.operator || '—' }}</template>
              </el-table-column>
              <el-table-column label="来源" width="64">
                <template #default="{ row }">{{ row.source === 'system' ? '系统' : '共享盘' }}</template>
              </el-table-column>
              <el-table-column prop="remark" label="备注" min-width="90" show-overflow-tooltip />
            </el-table>
            <el-empty v-else description="暂无进出账明细" :image-size="64" />
          </el-tab-pane>

          <el-tab-pane :label="`流水账 (${detail.ledger.length})`" name="ledger">
            <el-table v-if="detail.ledger.length" :data="detail.ledger" size="small" border stripe max-height="360">
              <el-table-column label="时间" width="155">
                <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="类型" width="90">
                <template #default="{ row }">{{ movementLabel(row.movement_type) }}</template>
              </el-table-column>
              <el-table-column label="变动" width="80" align="right">
                <template #default="{ row }">{{ row.qty_delta > 0 ? '+' : '' }}{{ fmtWhQty(row.qty_delta) }}</template>
              </el-table-column>
              <el-table-column label="结存" width="80" align="right">
                <template #default="{ row }">{{ fmtWhQty(row.qty_after) }}</template>
              </el-table-column>
              <el-table-column label="给方" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.giver || '—' }}</template>
              </el-table-column>
              <el-table-column label="收方" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.receiver || '—' }}</template>
              </el-table-column>
              <el-table-column prop="ref_no" label="单号" width="110" show-overflow-tooltip />
              <el-table-column label="提交人" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.operator || '—' }}</template>
              </el-table-column>
              <el-table-column prop="remark" label="备注" min-width="90" show-overflow-tooltip />
            </el-table>
            <el-empty v-else description="暂无流水账" :image-size="64" />
          </el-tab-pane>

          <el-tab-pane :label="`来料记录 (${detail.stock_ins.length})`" name="stock-ins">
            <el-table v-if="detail.stock_ins.length" :data="detail.stock_ins" size="small" border stripe max-height="360">
              <el-table-column label="时间" width="155">
                <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="数量" width="72" align="right">
                <template #default="{ row }">{{ fmtWhQty(row.qty) }}</template>
              </el-table-column>
              <el-table-column prop="source_name" label="来源" width="90" />
              <el-table-column label="给方" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.giver || '—' }}</template>
              </el-table-column>
              <el-table-column label="收方" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.receiver || '—' }}</template>
              </el-table-column>
              <el-table-column label="提交人" width="80" show-overflow-tooltip>
                <template #default="{ row }">{{ row.operator || '—' }}</template>
              </el-table-column>
              <el-table-column prop="receipt_no" label="单号" width="110" />
              <el-table-column prop="remark" label="备注" min-width="90" show-overflow-tooltip />
            </el-table>
            <el-empty v-else description="暂无来料记录" :image-size="64" />
          </el-tab-pane>

          <el-tab-pane :label="`关联订单 (${detail.orders.length})`" name="orders">
            <el-table v-if="detail.orders.length" :data="detail.orders" size="small" border stripe max-height="360">
              <el-table-column prop="order_no" label="订单号" min-width="140" />
              <el-table-column prop="product_model" label="机型" width="110" />
              <el-table-column label="已发料" width="88" align="right">
                <template #default="{ row }">{{ fmtWhQty(row.issued_qty) }}</template>
              </el-table-column>
              <el-table-column label="已退料" width="88" align="right">
                <template #default="{ row }">{{ fmtWhQty(row.returned_qty) }}</template>
              </el-table-column>
              <el-table-column prop="last_date" label="最近日期" width="100" />
            </el-table>
            <el-empty v-else description="暂无按订单发料记录" :image-size="64" />
          </el-tab-pane>
        </el-tabs>
      </template>
      <el-empty v-else-if="!loading" description="暂无数据或加载失败" :image-size="80" />
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchMaterialDetail } from '@/api/warehouse'
import WarehouseOperationForm from '@/components/warehouse/WarehouseOperationForm.vue'
import type { WarehouseMaterialDetail } from '@/types/warehouse'
import { fmtDate } from '@/utils/format'
import { excelMovementLabel, fmtWhQty, movementLabel } from '@/utils/warehouse'

const props = defineProps<{ modelValue: boolean; materialId?: number | null; reloadToken?: number }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; saved: [] }>()

const visible = ref(props.modelValue)
const loading = ref(false)
const detail = ref<WarehouseMaterialDetail | null>(null)
const innerTab = ref('movements')

const title = computed(() =>
  detail.value ? `${detail.value.material.customer_name} · 物料账` : '物料账',
)

const stockStatusText = computed(() => {
  const s = detail.value?.summary.stock_status
  if (s === 'enough') return '够用'
  if (s === 'short') {
    const gap = detail.value?.summary.stock_gap
    return gap != null ? `欠 ${fmtWhQty(Math.abs(gap))}` : '欠料'
  }
  return '—'
})

const stockStatusClass = computed(() => {
  const s = detail.value?.summary.stock_status
  if (s === 'enough') return 'text-ok'
  if (s === 'short') return 'qty-negative'
  return ''
})

async function loadDetail(id: number) {
  loading.value = true
  detail.value = null
  try {
    detail.value = await fetchMaterialDetail(id)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
    visible.value = false
  } finally {
    loading.value = false
  }
}

async function reloadDetail() {
  if (props.materialId) {
    await loadDetail(props.materialId)
    emit('saved')
  }
}

watch(
  () => [props.modelValue, props.materialId, props.reloadToken] as const,
  async ([v, id]) => {
    visible.value = v
    if (v && id) {
      innerTab.value = 'movements'
      await loadDetail(id)
    } else if (!v) {
      detail.value = null
    }
  },
  { immediate: true },
)
watch(visible, (v) => emit('update:modelValue', v))
</script>

<style scoped>
.mat-detail-head {
  margin-bottom: 16px;
}
.mat-detail-code {
  font-size: 18px;
  font-weight: 700;
}
.mat-detail-name {
  margin-top: 4px;
  font-size: 14px;
}
.mat-stats {
  margin-bottom: 8px;
}
.mat-stat {
  background: var(--erp-bg-muted, #f8fafc);
  border-radius: 8px;
  padding: 10px 12px;
  min-height: 72px;
}
.mat-stat span {
  display: block;
  font-size: 12px;
  color: var(--erp-text-muted, #64748b);
  margin-bottom: 4px;
}
.mat-stat strong {
  font-size: 18px;
}
.mat-mini-stats {
  font-size: 12px;
  margin-bottom: 12px;
}
.text-ok {
  color: #16a34a;
}
.cell-muted {
  font-size: 12px;
  color: var(--erp-text-muted, #64748b);
}
.qty-negative {
  color: #dc2626;
}
</style>
