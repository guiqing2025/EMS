<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">销售订单</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            草稿→确认→计划中→执行…；可绑工程 BOM；可从历史客户 PO 导入
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-input v-model="q" clearable placeholder="单号/客户/外部PO" style="width: 180px" @keyup.enter="load" />
          <el-select v-model="status" clearable placeholder="状态" style="width: 120px" @change="load">
            <el-option v-for="s in statusOpts" :key="s" :label="s" :value="s" />
          </el-select>
          <el-button @click="load">查询</el-button>
          <el-button type="primary" @click="openEdit()">新建</el-button>
          <el-button @click="openImport">导入客户PO</el-button>
          <el-button type="success" @click="$router.push('/sales/flow')">订单流程</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small" max-height="calc(100vh - 260px)">
          <el-table-column prop="so_no" label="销售单号" width="150" />
          <el-table-column prop="customer_name" label="客户" width="130" />
          <el-table-column prop="external_po_no" label="外部PO" width="120" />
          <el-table-column prop="order_kind" label="类型" width="110" />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column label="行摘要" min-width="180">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code || l.material_name}×${l.qty}`).join('；') || '—' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="320" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEdit(row)">详情</el-button>
              <el-button link type="warning" @click="$router.push({ path: '/sales/flow', query: { so_id: String(row.id) } })">
                流程
              </el-button>
              <el-button
                v-for="n in nextStatuses(row.status)"
                :key="n"
                link
                type="success"
                :loading="acting === `${row.id}:${n}`"
                @click="onStatus(row, n)"
              >
                →{{ n }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="open" :title="form.id ? `销售订单 ${form.so_no || ''}` : '新建销售订单'" width="860px" destroy-on-close>
      <FlowBacklink v-if="form.id" :so-id="form.id" :so-no="form.so_no" />
      <el-form label-width="100px">
        <el-form-item label="客户" required>
          <el-input v-model="form.customer_name" :disabled="!editable" />
        </el-form-item>
        <el-form-item label="外部PO">
          <el-input v-model="form.external_po_no" :disabled="!editable" />
        </el-form-item>
        <el-form-item label="强制BOM">
          <el-switch v-model="form.require_bom" :disabled="!editable" />
          <span style="margin-left: 8px; color: var(--erp-text-muted); font-size: 12px">开启后进入「计划中」须行绑 BOM</span>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" :disabled="!editable" /></el-form-item>
        <div style="margin: 8px 0 12px; font-weight: 600">订单行</div>
        <el-table :data="form.lines" border size="small">
          <el-table-column label="料号" min-width="110">
            <template #default="{ row }"><el-input v-model="row.material_code" size="small" :disabled="!editable" /></template>
          </el-table-column>
          <el-table-column label="品名" min-width="110">
            <template #default="{ row }"><el-input v-model="row.material_name" size="small" :disabled="!editable" /></template>
          </el-table-column>
          <el-table-column label="数量" width="100">
            <template #default="{ row }">
              <el-input-number v-model="row.qty" :min="0" size="small" controls-position="right" :disabled="!editable" />
            </template>
          </el-table-column>
          <el-table-column label="单价" width="100">
            <template #default="{ row }">
              <el-input-number v-model="row.unit_price" :min="0" size="small" controls-position="right" :disabled="!editable" />
            </template>
          </el-table-column>
          <el-table-column label="交期" width="120">
            <template #default="{ row }"><el-input v-model="row.due_date" size="small" placeholder="YYYY-MM-DD" :disabled="!editable" /></template>
          </el-table-column>
          <el-table-column label="BOM ID" width="100">
            <template #default="{ row }">
              <el-input-number
                v-model="row.bom_model_id"
                :min="1"
                size="small"
                controls-position="right"
                :disabled="form.status === 'void' || form.status === 'closed' || form.status === 'done'"
                @change="() => onBindBom(row)"
              />
            </template>
          </el-table-column>
          <el-table-column v-if="editable" label="" width="60">
            <template #default="{ $index }">
              <el-button link type="danger" @click="form.lines.splice($index, 1)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button v-if="editable" style="margin-top: 8px" @click="form.lines.push(emptyLine())">加一行</el-button>
      </el-form>
      <template #footer>
        <el-button @click="open = false">关闭</el-button>
        <el-button v-if="editable" type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importOpen" title="从历史客户订单导入" width="480px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="line_key">
          <el-input v-model="importForm.line_key" placeholder="单行导入" />
        </el-form-item>
        <el-form-item label="purchase_no">
          <el-input v-model="importForm.purchase_no" placeholder="整单导入（多行）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importOpen = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="onImport">导入为草稿</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import FlowBacklink from '@/components/FlowBacklink.vue'
import {
  bindSalesLineBom,
  createSalesOrder,
  fetchSalesOrder,
  fetchSalesOrders,
  importSalesFromSrm,
  setSalesOrderStatus,
  updateSalesOrder,
  type SalesOrder,
  type SalesOrderLine,
} from '@/api/sales'

const SO_NEXT: Record<string, string[]> = {
  draft: ['confirmed', 'void'],
  confirmed: ['planning', 'void'],
  planning: ['executing', 'void'],
  executing: ['partial_shipped', 'done', 'closed'],
  partial_shipped: ['done', 'closed'],
  done: ['closed'],
}

const statusOpts = ['draft', 'confirmed', 'planning', 'executing', 'partial_shipped', 'done', 'closed', 'void']
const loading = ref(false)
const saving = ref(false)
const acting = ref('')
const importing = ref(false)
const q = ref('')
const status = ref('')
const rows = ref<SalesOrder[]>([])
const open = ref(false)
const importOpen = ref(false)
const importForm = reactive({ line_key: '', purchase_no: '' })

function emptyLine(): SalesOrderLine {
  return { material_code: '', material_name: '', qty: 1, unit: 'PCS', unit_price: 0, due_date: '' }
}

const form = reactive({
  id: 0,
  so_no: '',
  customer_name: '',
  external_po_no: '',
  require_bom: false,
  remark: '',
  status: 'draft',
  lines: [emptyLine()] as SalesOrderLine[],
})

const editable = computed(() => !form.id || form.status === 'draft')

function nextStatuses(s: string) {
  return SO_NEXT[s] || []
}

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchSalesOrders({ q: q.value || undefined, status: status.value || undefined })).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function openEdit(row?: SalesOrder) {
  if (!row) {
    Object.assign(form, {
      id: 0,
      so_no: '',
      customer_name: '',
      external_po_no: '',
      require_bom: false,
      remark: '',
      status: 'draft',
      lines: [emptyLine()],
    })
    open.value = true
    return
  }
  try {
    const d = await fetchSalesOrder(row.id)
    Object.assign(form, {
      id: d.id,
      so_no: d.so_no,
      customer_name: d.customer_name || '',
      external_po_no: d.external_po_no || '',
      require_bom: !!d.require_bom,
      remark: d.remark || '',
      status: d.status,
      lines: (d.lines || []).map((l) => ({ ...l })),
    })
    open.value = true
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载详情失败')
  }
}

async function onSave() {
  saving.value = true
  try {
    const body = {
      customer_name: form.customer_name,
      external_po_no: form.external_po_no,
      require_bom: form.require_bom,
      remark: form.remark,
      lines: form.lines,
    }
    if (form.id) await updateSalesOrder(form.id, body)
    else await createSalesOrder(body)
    ElMessage.success('已保存')
    open.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onStatus(row: SalesOrder, next: string) {
  acting.value = `${row.id}:${next}`
  try {
    await setSalesOrderStatus(row.id, next)
    ElMessage.success(`已 → ${next}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '状态变更失败')
  } finally {
    acting.value = ''
  }
}

async function onBindBom(row: SalesOrderLine) {
  if (!form.id || !row.id) return
  try {
    await bindSalesLineBom(form.id, row.id, row.bom_model_id ?? null)
    ElMessage.success('BOM 已绑定')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '绑定失败')
  }
}

function openImport() {
  importForm.line_key = ''
  importForm.purchase_no = ''
  importOpen.value = true
}

async function onImport() {
  importing.value = true
  try {
    const so = await importSalesFromSrm({
      line_key: importForm.line_key || undefined,
      purchase_no: importForm.purchase_no || undefined,
    })
    ElMessage.success(`已导入 ${so.so_no}`)
    importOpen.value = false
    await load()
    await openEdit(so)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导入失败')
  } finally {
    importing.value = false
  }
}

onMounted(load)
</script>
