<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">MC 齐套运算</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            按销售订单行展开 BOM，对照库存计算齐套 / 缺料（不生成采购单）
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-input v-model="q" clearable placeholder="单号/客户/外部PO" style="width: 200px" @keyup.enter="run" />
          <el-button type="primary" :loading="loading" @click="run">开始运算</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <div v-if="result" class="summary">
          <el-tag>订单 {{ result.order_count }}</el-tag>
          <el-tag>行 {{ result.line_count }}</el-tag>
          <el-tag type="success">齐套 {{ result.ready_count }}</el-tag>
          <el-tag type="danger">需跟进 {{ result.shortage_count }}</el-tag>
          <span class="muted">运算时间 {{ formatTime(result.run_at) }}</span>
        </div>

        <el-table
          v-loading="loading"
          :data="result?.items || []"
          border
          stripe
          size="small"
          max-height="calc(100vh - 320px)"
          row-key="line_id"
        >
          <el-table-column type="expand">
            <template #default="{ row }">
              <el-table :data="row.components || []" size="small" border>
                <el-table-column prop="material_code" label="元件料号" width="140" />
                <el-table-column prop="material_name" label="名称" min-width="140" show-overflow-tooltip />
                <el-table-column prop="qty_per" label="单位用量" width="90" />
                <el-table-column prop="required_qty" label="需求" width="90" />
                <el-table-column prop="available_qty" label="可用库存" width="90" />
                <el-table-column prop="shortage_qty" label="缺口" width="90">
                  <template #default="{ row: c }">
                    <span :class="{ danger: c.shortage_qty > 0 }">{{ c.shortage_qty }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="process" label="工序" width="100" />
              </el-table>
              <div v-if="!(row.components || []).length" class="muted" style="padding: 8px">无 BOM 元件明细</div>
            </template>
          </el-table-column>
          <el-table-column prop="so_no" label="销售单号" width="140" />
          <el-table-column prop="customer_name" label="客户" width="120" show-overflow-tooltip />
          <el-table-column prop="material_code" label="成品料号" width="130" />
          <el-table-column prop="material_name" label="品名" min-width="120" show-overflow-tooltip />
          <el-table-column prop="qty" label="数量" width="80" />
          <el-table-column prop="due_date" label="交期" width="110" />
          <el-table-column label="齐套状态" width="100">
            <template #default="{ row }">
              <el-tag :type="kitTag(row.kitting_status)" size="small">
                {{ row.kitting_status_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="component_count" label="元件数" width="80" />
          <el-table-column prop="shortage_count" label="缺料项" width="80" />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="$router.push({ path: '/sales/flow', query: { so_id: String(row.so_id) } })">
                流程
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { runMcKitting, type McKittingResult } from '@/api/planning'

const loading = ref(false)
const q = ref('')
const result = ref<McKittingResult | null>(null)

function kitTag(st: string) {
  if (st === 'ready') return 'success'
  if (st === 'partial') return 'warning'
  if (st === 'shortage' || st === 'no_bom' || st === 'empty_bom') return 'danger'
  return 'info'
}

function formatTime(iso: string) {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 19)
}

async function run() {
  loading.value = true
  try {
    result.value = await runMcKitting({ q: q.value || undefined })
    ElMessage.success(`运算完成：${result.value.line_count} 行`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '运算失败')
  } finally {
    loading.value = false
  }
}

onMounted(run)
</script>

<style scoped>
.summary {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.muted {
  color: var(--erp-text-muted);
  font-size: 12px;
}
.danger {
  color: var(--el-color-danger);
  font-weight: 600;
}
</style>
