<template>
  <el-dialog v-model="visible" title="按订单批量发料" width="960px" destroy-on-close @open="onOpen">
    <el-form :inline="true" size="small" @submit.prevent="searchOrders">
      <el-form-item label="订单">
        <el-input v-model="orderKeyword" placeholder="订单号 / 机型" clearable style="width: 220px" @keyup.enter="searchOrders" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="searching" @click="searchOrders">查询订单</el-button>
      </el-form-item>
    </el-form>

    <el-table
      v-if="orderOptions.length"
      :data="orderOptions"
      size="small"
      border
      highlight-current-row
      max-height="160"
      style="margin-bottom: 12px"
      @row-click="onSelectOrder"
    >
      <el-table-column prop="purchase_no" label="订单号" min-width="140" />
      <el-table-column prop="product_goods_no" label="机型" min-width="120" />
      <el-table-column prop="product_goods_name" label="品名" min-width="120" show-overflow-tooltip />
      <el-table-column label="数量" width="80" align="right">
        <template #default="{ row }">{{ fmtWhQty(row.batch_pur_qty) }}</template>
      </el-table-column>
      <el-table-column prop="customer_name" label="客户" width="90" />
    </el-table>

    <div v-if="preview" v-loading="loadingPreview" class="issue-head">
      <div>
        <strong>{{ preview.purchase_no }}</strong>
        <span class="cell-muted"> · {{ preview.product_goods_no }} · 订单量 {{ fmtWhQty(preview.order_qty) }}</span>
        <div v-if="preview.message" class="warn-text">{{ preview.message }}</div>
      </div>
      <div class="issue-actions">
        <el-button size="small" type="primary" plain @click="downloadTemplate">下载发料模板</el-button>
        <el-upload
          :auto-upload="false"
          :show-file-list="false"
          accept=".xlsx,.xlsm"
          :disabled="parsing || !selectedLineKey"
          @change="onImportExcel"
        >
          <el-button size="small" :loading="parsing">导入 Excel</el-button>
        </el-upload>
        <el-button size="small" @click="fillSuggested">填入待发数量</el-button>
        <el-button size="small" @click="selectReady">勾选可发</el-button>
      </div>
    </div>
    <el-form v-if="preview" :inline="true" size="small" class="issue-party-form">
      <el-form-item label="发料人" required>
        <el-input v-model="giver" placeholder="谁发出的" style="width: 160px" />
      </el-form-item>
      <el-form-item label="领料人" required>
        <el-input v-model="receiver" placeholder="谁领的" style="width: 160px" />
      </el-form-item>
    </el-form>
    <div v-if="importInfo" class="import-info">{{ importInfo }}</div>

    <el-table v-if="preview?.lines.length" :data="preview.lines" border size="small" max-height="380">
      <el-table-column width="48" align="center">
        <template #default="{ row }">
          <el-checkbox v-model="row.selected" :disabled="!row.material_id || row.remain_qty <= 0" />
        </template>
      </el-table-column>
      <el-table-column prop="material_code" label="料号" min-width="130" show-overflow-tooltip />
      <el-table-column prop="material_name" label="品名" min-width="100" show-overflow-tooltip />
      <el-table-column label="需求" width="72" align="right">
        <template #default="{ row }">{{ fmtWhQty(row.required_qty) }}</template>
      </el-table-column>
      <el-table-column label="已发" width="72" align="right">
        <template #default="{ row }">{{ fmtWhQty(row.issued_qty) }}</template>
      </el-table-column>
      <el-table-column label="待发" width="72" align="right">
        <template #default="{ row }">{{ fmtWhQty(row.remain_qty) }}</template>
      </el-table-column>
      <el-table-column label="可用" width="72" align="right">
        <template #default="{ row }">{{ fmtWhQty(row.available_qty) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="72">
        <template #default="{ row }">
          <span :class="statusClass(row.status)">{{ issueLineStatusLabel(row.status) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="本次发料" width="110">
        <template #default="{ row }">
          <el-input-number
            v-model="row.issue_qty"
            :min="0"
            :precision="4"
            controls-position="right"
            size="small"
            style="width: 100%"
            :disabled="!row.material_id"
          />
        </template>
      </el-table-column>
      <el-table-column label="部门" width="90">
        <template #default="{ row }">
          <el-select v-model="row.department" size="small" style="width: 100%">
            <el-option label="SMT" value="smt" />
            <el-option label="DIP" value="dip" />
          </el-select>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else-if="selectedLineKey && !loadingPreview" description="无 BOM 物料清单或未绑定 BOM" :image-size="64" />

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="!preview" @click="onSubmit">确认发料扣账</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import type { UploadFile } from 'element-plus'
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchOrders } from '@/api/orders'
import { batchIssueOrder, downloadOrderIssueTemplate, fetchOrderIssuePreview, parseIssueExcel } from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import type { OrderIssuePreview } from '@/types/warehouse'
import type { SrmOrder } from '@/types/order'
import { fmtWhQty, issueLineStatusLabel } from '@/utils/warehouse'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; saved: [] }>()
const auth = useAuthStore()

const visible = ref(props.modelValue)
const saving = ref(false)
const searching = ref(false)
const parsing = ref(false)
const loadingPreview = ref(false)
const importInfo = ref('')
const orderKeyword = ref('')
const orderOptions = ref<SrmOrder[]>([])
const selectedLineKey = ref('')
const preview = ref<OrderIssuePreview | null>(null)
const giver = ref('')
const receiver = ref('')

watch(() => props.modelValue, (v) => { visible.value = v })
watch(visible, (v) => emit('update:modelValue', v))

function onOpen() {
  orderKeyword.value = ''
  orderOptions.value = []
  selectedLineKey.value = ''
  preview.value = null
  importInfo.value = ''
  giver.value = auth.user?.display_name || auth.user?.username || ''
  receiver.value = ''
}

function statusClass(status: string) {
  if (status === 'ready') return 'text-ok'
  if (status === 'shortage' || status === 'no_stock') return 'qty-negative'
  return ''
}

async function searchOrders() {
  searching.value = true
  try {
    orderOptions.value = await fetchOrders({
      keyword: orderKeyword.value.trim(),
      completed: 'incomplete',
      page: 1,
      page_size: 30,
    })
    if (!orderOptions.value.length) ElMessage.info('未找到订单')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '查询失败')
  } finally {
    searching.value = false
  }
}

async function onSelectOrder(row: SrmOrder) {
  selectedLineKey.value = row.line_key
  loadingPreview.value = true
  preview.value = null
  try {
    const data = await fetchOrderIssuePreview(row.line_key)
    preview.value = {
      ...data,
      lines: (data.lines || []).map((line) => ({
        ...line,
        issue_qty: line.suggested_qty > 0 ? line.suggested_qty : 0,
        selected: line.status === 'ready' && line.suggested_qty > 0,
        department: (line.process === 'dip' || line.process === 'assy') ? 'dip' : 'smt',
      })),
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载发料清单失败')
  } finally {
    loadingPreview.value = false
  }
}

function fillSuggested() {
  preview.value?.lines.forEach((line) => {
    if (line.material_id && line.remain_qty > 0) {
      line.issue_qty = line.suggested_qty
      line.selected = line.suggested_qty > 0
    }
  })
}

function selectReady() {
  preview.value?.lines.forEach((line) => {
    line.selected = line.status === 'ready' && (line.issue_qty || 0) > 0
  })
}

async function downloadTemplate() {
  if (!selectedLineKey.value || !preview.value) return
  const name = `发料_${preview.value.purchase_no}_${preview.value.product_goods_no}.xlsx`
  try {
    await downloadOrderIssueTemplate(selectedLineKey.value, name)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下载失败')
  }
}

async function onImportExcel(uploadFile: UploadFile) {
  if (!selectedLineKey.value || !preview.value) return
  const raw = uploadFile.raw
  if (!raw) return
  parsing.value = true
  importInfo.value = ''
  try {
    const res = await parseIssueExcel(selectedLineKey.value, raw)
    const map = new Map(res.lines.map((l) => [l.material_code.toLowerCase(), l]))
    let applied = 0
    preview.value.lines.forEach((line) => {
      const hit = map.get(line.material_code.toLowerCase())
      if (hit) {
        line.issue_qty = hit.qty
        line.department = hit.department === 'dip' ? 'dip' : 'smt'
        line.selected = hit.qty > 0
        applied += 1
      } else {
        line.selected = false
      }
    })
    const errCount = res.errors?.length || 0
    importInfo.value = `已从 Excel 导入 ${applied} 行发料数量${errCount ? `，${errCount} 行无法匹配已跳过` : ''}`
    ElMessage.success(`已导入 ${applied} 行`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导入失败')
  } finally {
    parsing.value = false
  }
}

async function onSubmit() {
  if (!preview.value || !selectedLineKey.value) return
  if (!giver.value.trim()) {
    ElMessage.error('请填写发料人')
    return
  }
  if (!receiver.value.trim()) {
    ElMessage.error('请填写领料人')
    return
  }
  const lines = (preview.value.lines || [])
    .filter((line) => line.selected && line.material_id && (line.issue_qty || 0) > 0)
    .map((line) => ({
      material_id: line.material_id!,
      qty: Number(line.issue_qty),
      process: line.process || undefined,
      department: line.department || 'smt',
    }))
  if (!lines.length) {
    ElMessage.error('请勾选并填写至少一行发料数量')
    return
  }
  saving.value = true
  try {
    const res = await batchIssueOrder(selectedLineKey.value, lines, {
      giver: giver.value.trim(),
      receiver: receiver.value.trim(),
    })
    const skipCount = res.skipped?.length || 0
    ElMessage.success(`发料扣账 ${res.success_count} 条，批次号 ${res.ref_no}${skipCount ? `，跳过 ${skipCount} 条` : ''}`)
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发料失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.issue-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}
.issue-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.issue-party-form {
  margin-bottom: 8px;
}
.import-info {
  font-size: 12px;
  color: #16a34a;
  margin-bottom: 8px;
}
.cell-muted {
  font-size: 12px;
  color: var(--erp-text-muted);
}
.warn-text {
  color: #d97706;
  font-size: 12px;
  margin-top: 4px;
}
.text-ok {
  color: #16a34a;
}
.qty-negative {
  color: #dc2626;
}
</style>
