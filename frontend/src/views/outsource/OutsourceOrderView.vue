<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">委外单</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            手工建单或从委外计划下推 → 确认 → 发料扣库存 → 条码 → 送检
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-input v-model="q" clearable placeholder="单号/供应商" style="width: 160px" @keyup.enter="load" />
          <el-button @click="load">查询</el-button>
          <el-button type="primary" @click="openEdit()">新建</el-button>
          <el-button @click="openFromPlan">从计划下推</el-button>
          <el-button @click="$router.push('/sales/flow')">订单流程</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <FlowBacklink v-if="routeSoId" :so-id="routeSoId" />
        <el-table v-loading="loading" :data="rows" border stripe size="small" max-height="calc(100vh - 260px)">
          <el-table-column prop="ww_no" label="委外单号" width="150" />
          <el-table-column prop="supplier_name" label="委外厂" width="140" />
          <el-table-column prop="process" label="工序" width="100" />
          <el-table-column prop="source_plan_no" label="来源计划" width="140" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="行摘要" min-width="180">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code}×${l.qty}`).join('；') || '—' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="360" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" @click="onStatus(row, 'confirmed')">确认</el-button>
              <el-button
                v-if="row.status === 'confirmed' || row.status === 'shipped' || row.status === 'partial'"
                link
                type="primary"
                :loading="acting === `ship-${row.id}`"
                @click="onShip(row)"
              >
                发料
              </el-button>
              <el-button
                v-if="row.status === 'confirmed' || row.status === 'shipped' || row.status === 'partial'"
                link
                @click="openBarcode(row)"
              >
                条码
              </el-button>
              <el-button
                v-if="row.status === 'confirmed' || row.status === 'shipped' || row.status === 'partial'"
                link
                type="warning"
                :loading="acting === `insp-${row.id}`"
                @click="onInspect(row)"
              >
                送检
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="open" title="新建委外单" width="720px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="委外厂"><el-input v-model="form.supplier_name" /></el-form-item>
        <el-form-item label="工序"><el-input v-model="form.process" placeholder="如：镀金/贴片" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item>
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
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bcOpen" title="登记委外条码" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="委外单">{{ bcRow?.ww_no }}</el-form-item>
        <el-form-item label="条码" required><el-input v-model="barcode" /></el-form-item>
        <el-form-item label="数量"><el-input-number v-model="bcQty" :min="0.001" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bcOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onBarcode">登记</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="planOpen" title="从委外计划下推" width="420px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="计划ID"><el-input-number v-model="planId" :min="1" /></el-form-item>
        <el-form-item label="委外厂"><el-input v-model="planSupplier" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onFromPlan">下推</el-button>
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
  confirmShip,
  createInspectFromWw,
  createOutsourceOrder,
  createShipFromWw,
  createWwFromPlan,
  fetchOutsourceOrders,
  registerBarcode,
  setOutsourceOrderStatus,
  type OutsourceOrder,
} from '@/api/outsource'

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
const rows = ref<OutsourceOrder[]>([])
const open = ref(false)
const bcOpen = ref(false)
const planOpen = ref(false)
const planId = ref(1)
const planSupplier = ref('')
const bcRow = ref<OutsourceOrder | null>(null)
const barcode = ref('')
const bcQty = ref(1)
const form = reactive({
  supplier_name: '',
  process: '',
  remark: '',
  lines: [{ material_code: '', material_name: '', qty: 1, unit_price: 0 }],
})

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchOutsourceOrders({ q: q.value || undefined })).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openEdit() {
  form.supplier_name = ''
  form.process = ''
  form.remark = ''
  form.lines = [{ material_code: '', material_name: '', qty: 1, unit_price: 0 }]
  open.value = true
}

async function onSave() {
  saving.value = true
  try {
    await createOutsourceOrder({ ...form, lines: form.lines })
    ElMessage.success('已建委外单')
    open.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onStatus(row: OutsourceOrder, status: string) {
  try {
    await setOutsourceOrderStatus(row.id, status)
    ElMessage.success(`已 → ${status}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onShip(row: OutsourceOrder) {
  acting.value = `ship-${row.id}`
  try {
    const ship = await createShipFromWw(row.id)
    await confirmShip(ship.id)
    ElMessage.success(`已发料 ${ship.ship_no}（扣内部库存）`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发料失败')
  } finally {
    acting.value = ''
  }
}

function openBarcode(row: OutsourceOrder) {
  bcRow.value = row
  barcode.value = ''
  bcQty.value = 1
  bcOpen.value = true
}

async function onBarcode() {
  if (!bcRow.value) return
  saving.value = true
  try {
    await registerBarcode({
      ww_id: bcRow.value.id,
      barcode: barcode.value,
      qty: bcQty.value,
      material_code: bcRow.value.lines?.[0]?.material_code,
    })
    ElMessage.success('条码已登记')
    bcOpen.value = false
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '登记失败')
  } finally {
    saving.value = false
  }
}

async function onInspect(row: OutsourceOrder) {
  acting.value = `insp-${row.id}`
  try {
    const insp = await createInspectFromWw(row.id)
    ElMessage.success(`已建送检 ${insp.inspect_no}`)
    await router.push('/outsource/inspect')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '送检失败')
  } finally {
    acting.value = ''
  }
}

function openFromPlan() {
  planOpen.value = true
}

async function onFromPlan() {
  saving.value = true
  try {
    const ww = await createWwFromPlan(planId.value, { supplier_name: planSupplier.value })
    ElMessage.success(`已下推 ${ww.ww_no}`)
    planOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下推失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
