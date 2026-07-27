<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">订单报价</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            独立模块：导入 BOM 按鼎雄习惯算法自动核算，可导出 Excel（与系统订单无联动）
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button v-if="detail" @click="backToList">返回列表</el-button>
          <el-button type="primary" @click="onCreate">新建报价单</el-button>
        </div>
      </div>

      <div class="erp-page-body">
        <!-- 列表 -->
        <template v-if="!detail">
          <el-form :inline="true" @submit.prevent="loadList">
            <el-form-item label="状态">
              <el-select v-model="status" clearable placeholder="全部" style="width: 120px" @change="loadList">
                <el-option label="草稿" value="draft" />
                <el-option label="已核算" value="calculated" />
                <el-option label="已确认" value="confirmed" />
                <el-option label="已作废" value="void" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-input v-model="keyword" placeholder="单号 / 客户 / 料号" clearable style="width: 220px" @keyup.enter="loadList" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="loadList">查询</el-button>
            </el-form-item>
          </el-form>

          <el-table v-loading="loading" :data="rows" stripe border size="small" max-height="calc(100vh - 260px)">
            <el-table-column prop="quote_no" label="报价单号" width="150" />
            <el-table-column prop="customer_name" label="客户" min-width="140" show-overflow-tooltip />
            <el-table-column prop="product_code" label="产品料号" min-width="140" show-overflow-tooltip />
            <el-table-column prop="product_name" label="产品名称" min-width="120" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="unit_price" label="加工单价" width="100" align="right">
              <template #default="{ row }">{{ fmt(row.unit_price) }}</template>
            </el-table-column>
            <el-table-column prop="tooling_total" label="治具" width="90" align="right">
              <template #default="{ row }">{{ fmt(row.tooling_total) }}</template>
            </el-table-column>
            <el-table-column prop="grand_total" label="合计" width="100" align="right">
              <template #default="{ row }">{{ fmt(row.grand_total) }}</template>
            </el-table-column>
            <el-table-column prop="created_by" label="制单" width="90" />
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openDetail(row.id)">打开</el-button>
                <el-button size="small" type="success" plain :disabled="row.status === 'draft'" @click="onExport(row.id)">导出</el-button>
                <el-button
                  v-if="row.status === 'draft' || row.status === 'void'"
                  size="small"
                  type="danger"
                  plain
                  @click="onDelete(row)"
                >删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <!-- 详情 -->
        <template v-else>
          <el-form label-width="88px" class="q-form">
            <el-row :gutter="12">
              <el-col :span="6">
                <el-form-item label="报价单号">
                  <el-input :model-value="detail.quote_no" disabled />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="客户">
                  <el-input v-model="form.customer_name" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="产品料号">
                  <el-input v-model="form.product_code" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="产品名称">
                  <el-input v-model="form.product_name" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="批量">
                  <el-input-number v-model="form.batch_qty" :min="0" :controls="false" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="工程费">
                  <el-input-number v-model="form.engineering_fee" :min="0" :controls="false" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="备注">
                  <el-input v-model="form.remark" />
                </el-form-item>
              </el-col>
            </el-row>
            <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px">
              <el-button @click="saveHeader" :loading="saving">保存头信息</el-button>
              <el-button type="primary" :loading="importing" @click="fileInput?.click()">导入 BOM 并核算</el-button>
              <el-button :disabled="!detail.cost_lines?.length" @click="onExport(detail.id)">导出 Excel</el-button>
              <el-button
                v-if="detail.status === 'calculated'"
                type="success"
                @click="onConfirm"
              >确认报价</el-button>
              <el-button v-if="detail.status !== 'void'" type="danger" plain @click="onVoid">作废</el-button>
              <el-button
                v-if="detail.status === 'draft' || detail.status === 'void'"
                type="danger"
                @click="onDelete(detail)"
              >删除</el-button>
              <input ref="fileInput" type="file" accept=".xls,.xlsx,.xlsm" style="display: none" @change="onImportFile" />
              <span style="color: var(--erp-text-muted); font-size: 13px; line-height: 32px">
                状态：{{ statusLabel(detail.status) }}
                <template v-if="detail.source_filename"> · 源文件 {{ detail.source_filename }}</template>
              </span>
            </div>
          </el-form>

          <el-row :gutter="16">
            <el-col :span="10">
              <h3 class="q-sec">费用明细</h3>
              <el-table :data="detail.cost_lines" size="small" border stripe max-height="420">
                <el-table-column prop="section" label="大类" width="70" />
                <el-table-column prop="item_name" label="项目" min-width="120" />
                <el-table-column prop="points" label="点数" width="70" align="right">
                  <template #default="{ row }">{{ fmt(row.points) }}</template>
                </el-table-column>
                <el-table-column prop="unit_price" label="单价" width="70" align="right">
                  <template #default="{ row }">{{ fmt(row.unit_price) }}</template>
                </el-table-column>
                <el-table-column label="金额" width="100" align="right">
                  <template #default="{ row }">
                    <el-input-number
                      v-if="row.editable"
                      v-model="row.amount"
                      size="small"
                      :controls="false"
                      style="width: 90px"
                      @change="() => onCostChange(row)"
                    />
                    <span v-else>{{ fmt(row.amount) }}</span>
                  </template>
                </el-table-column>
              </el-table>
              <div class="q-sum">
                加工单价 <b>{{ fmt(detail.unit_price) }}</b>
                · 治具 <b>{{ fmt(detail.tooling_total) }}</b>
                · 合计 <b>{{ fmt(detail.grand_total) }}</b>
              </div>
            </el-col>
            <el-col :span="14">
              <h3 class="q-sec">BOM 归类预览（{{ detail.bom_lines?.length || 0 }} 行）</h3>
              <el-table :data="detail.bom_lines" size="small" border stripe max-height="420">
                <el-table-column prop="bucket" label="归类" width="72" />
                <el-table-column prop="package" label="封装" width="80" />
                <el-table-column prop="material_code" label="料号" width="120" show-overflow-tooltip />
                <el-table-column prop="material_name" label="品名" width="100" show-overflow-tooltip />
                <el-table-column prop="qty_per" label="用量" width="60" align="right" />
                <el-table-column prop="ic_amount" label="P" width="60" align="right" />
                <el-table-column prop="dip_points" label="Q" width="50" align="right" />
                <el-table-column prop="calc_amount" label="金额" width="70" align="right">
                  <template #default="{ row }">{{ fmt(row.calc_amount as number) }}</template>
                </el-table-column>
                <el-table-column prop="spec" label="规格" min-width="140" show-overflow-tooltip />
              </el-table>
            </el-col>
          </el-row>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createQuote,
  deleteQuote,
  exportQuoteExcel,
  fetchQuote,
  fetchQuotes,
  importQuoteBom,
  patchQuoteCosts,
  setQuoteStatus,
  updateQuote,
  type QuoteDetail,
  type QuoteListItem,
} from '@/api/quotation'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const rows = ref<QuoteListItem[]>([])
const keyword = ref('')
const status = ref('')
const detail = ref<QuoteDetail | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const form = reactive({
  customer_name: '',
  product_name: '',
  product_code: '',
  remark: '',
  batch_qty: 0,
  engineering_fee: 0,
})

function fmt(n: number | undefined | null) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toFixed(4).replace(/\.?0+$/, (m) => (m.includes('.') ? m.replace(/0+$/, '').replace(/\.$/, '') : m))
}

function statusLabel(s: string) {
  return ({ draft: '草稿', calculated: '已核算', confirmed: '已确认', void: '已作废' } as Record<string, string>)[s] || s
}
function statusTag(s: string) {
  return ({ draft: 'info', calculated: 'warning', confirmed: 'success', void: 'danger' } as Record<string, string>)[s] || 'info'
}

function syncForm(d: QuoteDetail) {
  form.customer_name = d.customer_name || ''
  form.product_name = d.product_name || ''
  form.product_code = d.product_code || ''
  form.remark = d.remark || ''
  form.batch_qty = Number(d.batch_qty || 0)
  form.engineering_fee = Number(d.engineering_fee || 0)
}

async function loadList() {
  loading.value = true
  try {
    rows.value = await fetchQuotes({ keyword: keyword.value, status: status.value })
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function openDetail(id: number) {
  loading.value = true
  try {
    detail.value = await fetchQuote(id)
    syncForm(detail.value)
    router.replace(`/quotation/${id}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '打开失败')
  } finally {
    loading.value = false
  }
}

function backToList() {
  detail.value = null
  router.replace('/quotation')
  loadList()
}

async function onCreate() {
  try {
    const d = await createQuote({ customer_name: '', product_name: '', product_code: '' })
    ElMessage.success(`已创建 ${d.quote_no}`)
    await openDetail(d.id)
  } catch (e: any) {
    ElMessage.error(e?.message || '创建失败')
  }
}

async function saveHeader() {
  if (!detail.value) return
  saving.value = true
  try {
    detail.value = await updateQuote(detail.value.id, { ...form })
    syncForm(detail.value)
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onImportFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !detail.value) return
  importing.value = true
  try {
    // 与示例单接近：有 DIP 时可选手填波峰治具数量，默认 0；塘锡用引擎默认 1.5
    detail.value = await importQuoteBom(detail.value.id, file, { stencil_qty: 1, wave_fixture_qty: 0 })
    syncForm(detail.value)
    ElMessage.success(`核算完成：加工单价 ${fmt(detail.value.unit_price)}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '导入失败')
  } finally {
    importing.value = false
  }
}

async function onCostChange(row: { item_key: string; amount: number }) {
  if (!detail.value) return
  try {
    detail.value = await patchQuoteCosts(detail.value.id, [{ item_key: row.item_key, amount: row.amount }])
    syncForm(detail.value)
  } catch (e: any) {
    ElMessage.error(e?.message || '更新失败')
  }
}

async function onExport(id: number) {
  try {
    const { blob, filename } = await exportQuoteExcel(id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(e?.message || '导出失败')
  }
}

async function onConfirm() {
  if (!detail.value) return
  await ElMessageBox.confirm('确认后作为正式报价存档，是否继续？', '确认报价')
  detail.value = await setQuoteStatus(detail.value.id, 'confirmed')
  ElMessage.success('已确认')
}

async function onVoid() {
  if (!detail.value) return
  await ElMessageBox.confirm('确定作废该报价单？', '作废', { type: 'warning' })
  detail.value = await setQuoteStatus(detail.value.id, 'void')
  ElMessage.success('已作废')
}

async function onDelete(row: QuoteListItem) {
  await ElMessageBox.confirm(`确定删除报价单 ${row.quote_no}？删除后不可恢复。`, '删除', { type: 'warning' })
  try {
    await deleteQuote(row.id)
    ElMessage.success('已删除')
    if (detail.value?.id === row.id) backToList()
    else await loadList()
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

watch(
  () => route.params.id,
  (id) => {
    if (id) openDetail(Number(id))
    else {
      detail.value = null
      loadList()
    }
  },
)

onMounted(() => {
  const id = route.params.id
  if (id) openDetail(Number(id))
  else loadList()
})
</script>

<style scoped>
.q-form {
  margin-bottom: 8px;
}
.q-sec {
  margin: 0 0 8px;
  font-size: 14px;
}
.q-sum {
  margin-top: 10px;
  font-size: 14px;
}
.q-sum b {
  color: var(--erp-primary, #2563eb);
}
</style>
