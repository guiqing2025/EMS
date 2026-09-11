<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">销售出库单</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            从销售订单下推 → 过账扣 GOOD 成品 → 打包条码 → 生成发货单
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-input v-model="q" clearable placeholder="单号/客户" style="width: 160px" @keyup.enter="load" />
          <el-button @click="load">查询</el-button>
          <el-button type="primary" @click="openFromSo">从销售订单下推</el-button>
          <el-button @click="openManual">手工建单</el-button>
          <el-button @click="$router.push('/sales/flow')">订单流程</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <FlowBacklink v-if="routeSoId" :so-id="routeSoId" />
        <el-table v-loading="loading" :data="rows" border stripe size="small" max-height="calc(100vh - 260px)">
          <el-table-column prop="issue_no" label="出库单号" width="150" />
          <el-table-column prop="so_no" label="销售订单" width="140" />
          <el-table-column prop="customer_name" label="客户" width="140" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="行摘要" min-width="180">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code}×${l.qty}`).join('；') || '—' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="360" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" :loading="acting === `post-${row.id}`" @click="onPost(row)">
                过账出库
              </el-button>
              <el-button v-if="row.status === 'draft' || row.status === 'posted'" link @click="openPack(row)">打包条码</el-button>
              <el-button
                v-if="row.status === 'posted'"
                link
                type="warning"
                :loading="acting === `del-${row.id}`"
                @click="onDelivery(row)"
              >
                生成发货单
              </el-button>
              <el-button v-if="row.status === 'draft'" link type="danger" @click="onVoid(row)">作废</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="soOpen" title="从销售订单下推出库" width="420px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="销售订单ID"><el-input-number v-model="soId" :min="1" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="soOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onFromSo">下推</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="manualOpen" title="手工销售出库" width="720px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="客户"><el-input v-model="form.customer_name" /></el-form-item>
        <el-form-item label="销售单号"><el-input v-model="form.so_no" placeholder="可选" /></el-form-item>
        <el-table :data="form.lines" border size="small">
          <el-table-column label="料号" min-width="120">
            <template #default="{ row }"><el-input v-model="row.material_code" size="small" /></template>
          </el-table-column>
          <el-table-column label="品名" min-width="120">
            <template #default="{ row }"><el-input v-model="row.material_name" size="small" /></template>
          </el-table-column>
          <el-table-column label="数量" width="110">
            <template #default="{ row }"><el-input-number v-model="row.qty" :min="0" size="small" controls-position="right" /></template>
          </el-table-column>
          <el-table-column label="单价" width="110">
            <template #default="{ row }"><el-input-number v-model="row.unit_price" :min="0" size="small" controls-position="right" /></template>
          </el-table-column>
        </el-table>
        <el-button style="margin-top: 8px" @click="form.lines.push({ material_code: '', material_name: '', qty: 1, unit_price: 0 })">加一行</el-button>
      </el-form>
      <template #footer>
        <el-button @click="manualOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onManual">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="packOpen" title="登记打包条码" width="480px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="出库单">{{ packRow?.issue_no }}</el-form-item>
        <el-form-item label="条码" required><el-input v-model="pack.barcode" /></el-form-item>
        <el-form-item label="箱号"><el-input v-model="pack.box_no" /></el-form-item>
        <el-form-item label="数量"><el-input-number v-model="pack.qty" :min="0.001" /></el-form-item>
      </el-form>
      <p style="font-size: 12px; color: var(--erp-text-muted); margin: 0 8px 8px">
        复杂合箱仍可用「成品发货(过渡)/打包批次」页；本处挂 ERP 出库单。
      </p>
      <template #footer>
        <el-button @click="packOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onPack">登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import FlowBacklink from '@/components/FlowBacklink.vue'
import {
  createDeliveryFromIssue,
  createIssueFromSo,
  createSalesIssue,
  fetchSalesIssues,
  postSalesIssue,
  registerPackBarcode,
  voidSalesIssue,
  type SalesIssue,
} from '@/api/shipping'

const router = useRouter()
const route = useRoute()
const routeSoId = computed(() => {
  const n = Number(route.query.so_id || 0)
  return n > 0 ? n : undefined
})
const loading = ref(false)
const saving = ref(false)
const acting = ref('')
const q = ref('')
const rows = ref<SalesIssue[]>([])
const soOpen = ref(false)
const soId = ref(1)
const manualOpen = ref(false)
const packOpen = ref(false)
const packRow = ref<SalesIssue | null>(null)
const pack = reactive({ barcode: '', box_no: '', qty: 1 })
const form = reactive({
  customer_name: '',
  so_no: '',
  lines: [{ material_code: '', material_name: '', qty: 1, unit_price: 0 }],
})

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchSalesIssues({ q: q.value || undefined })).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openFromSo() {
  soOpen.value = true
}

async function onFromSo() {
  saving.value = true
  try {
    const iss = await createIssueFromSo(soId.value)
    ElMessage.success(`已下推 ${iss.issue_no}`)
    soOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下推失败')
  } finally {
    saving.value = false
  }
}

function openManual() {
  form.customer_name = ''
  form.so_no = ''
  form.lines = [{ material_code: '', material_name: '', qty: 1, unit_price: 0 }]
  manualOpen.value = true
}

async function onManual() {
  saving.value = true
  try {
    await createSalesIssue({ ...form, lines: form.lines })
    ElMessage.success('已建出库单')
    manualOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onPost(row: SalesIssue) {
  acting.value = `post-${row.id}`
  try {
    await postSalesIssue(row.id)
    ElMessage.success('已过账扣成品库存')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '过账失败')
  } finally {
    acting.value = ''
  }
}

async function onVoid(row: SalesIssue) {
  try {
    await voidSalesIssue(row.id)
    ElMessage.success('已作废')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

function openPack(row: SalesIssue) {
  packRow.value = row
  pack.barcode = ''
  pack.box_no = ''
  pack.qty = 1
  packOpen.value = true
}

async function onPack() {
  if (!packRow.value) return
  saving.value = true
  try {
    await registerPackBarcode({
      issue_id: packRow.value.id,
      barcode: pack.barcode,
      box_no: pack.box_no,
      qty: pack.qty,
      material_code: packRow.value.lines?.[0]?.material_code,
    })
    ElMessage.success('打包条码已登记')
    packOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '登记失败')
  } finally {
    saving.value = false
  }
}

async function onDelivery(row: SalesIssue) {
  acting.value = `del-${row.id}`
  try {
    const d = await createDeliveryFromIssue(row.id)
    ElMessage.success(`已建发货单 ${d.delivery_no}`)
    await router.push('/shipping/delivery')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    acting.value = ''
  }
}

onMounted(load)
</script>
