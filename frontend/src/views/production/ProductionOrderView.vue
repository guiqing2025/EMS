<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">生产单</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            计划下推/手工建单 → 下达 → 条码 → 领料 → QA → 成品入库
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-input v-model="q" clearable placeholder="单号/料号" style="width: 150px" @keyup.enter="load" />
          <el-button @click="load">查询</el-button>
          <el-button type="primary" @click="open = true">新建</el-button>
          <el-button @click="planOpen = true">从计划下推</el-button>
          <el-button @click="$router.push('/sales/flow')">订单流程</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <FlowBacklink v-if="routeSoId" :so-id="routeSoId" />
        <el-table v-loading="loading" :data="rows" border stripe size="small" max-height="360">
          <el-table-column prop="mo_no" label="生产单号" width="150" />
          <el-table-column prop="material_code" label="成品料号" width="130" />
          <el-table-column prop="qty" label="数量" width="80" align="right" />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column prop="issued_sets" label="发料套" width="80" />
          <el-table-column prop="qa_pass_qty" label="QA合" width="80" />
          <el-table-column prop="fg_qty" label="入库" width="80" />
          <el-table-column label="操作" width="360" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" @click="onStatus(row, 'released')">下达</el-button>
              <el-button v-if="row.status !== 'draft' && row.status !== 'void'" link @click="openBc(row)">条码</el-button>
              <el-button
                v-if="['released', 'issuing', 'in_process'].includes(row.status)"
                link
                type="warning"
                @click="onIssue(row)"
              >
                BOM领料
              </el-button>
              <el-button
                v-if="['in_process', 'issuing', 'qa'].includes(row.status)"
                link
                type="primary"
                @click="onQa(row)"
              >
                建QA
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <h3 style="font-size: 14px; margin: 16px 0 8px">PMC 进度</h3>
        <el-table :data="board" border size="small" max-height="220">
          <el-table-column prop="mo_no" label="MO" width="140" />
          <el-table-column prop="progress" label="进度" min-width="280" />
        </el-table>
      </div>
    </div>

    <el-dialog v-model="open" title="新建生产单" width="480px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="成品料号"><el-input v-model="form.material_code" /></el-form-item>
        <el-form-item label="品名"><el-input v-model="form.material_name" /></el-form-item>
        <el-form-item label="数量"><el-input-number v-model="form.qty" :min="1" /></el-form-item>
        <el-form-item label="BOM ID"><el-input-number v-model="form.bom_model_id" :min="1" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="planOpen" title="从生产计划下推" width="360px">
      <el-form-item label="计划ID"><el-input-number v-model="planId" :min="1" /></el-form-item>
      <template #footer>
        <el-button @click="planOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onFromPlan">下推</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bcOpen" title="挂生产条码" width="400px">
      <el-input v-model="barcode" placeholder="板码/镭雕码" />
      <template #footer>
        <el-button @click="bcOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onBc">登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FlowBacklink from '@/components/FlowBacklink.vue'
import { ElMessage } from 'element-plus'
import {
  createMaterialDoc,
  confirmMaterialDoc,
  createMo,
  createMoFromPlan,
  createQaFromMo,
  fetchMos,
  fetchPmcBoard,
  registerMoBarcode,
  setMoStatus,
  type Mo,
} from '@/api/production'

const router = useRouter()
const route = useRoute()
const routeSoId = computed(() => {
  const n = Number(route.query.so_id || 0)
  return n > 0 ? n : undefined
})
const loading = ref(false)
const saving = ref(false)
const q = ref('')
const rows = ref<Mo[]>([])
const board = ref<Array<Record<string, unknown>>>([])
const open = ref(false)
const planOpen = ref(false)
const planId = ref(1)
const bcOpen = ref(false)
const barcode = ref('')
const bcMo = ref<Mo | null>(null)
const form = reactive({ material_code: '', material_name: '', qty: 1, bom_model_id: undefined as number | undefined })

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchMos({ q: q.value || undefined })).items || []
    board.value = (await fetchPmcBoard()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onSave() {
  saving.value = true
  try {
    await createMo({ ...form })
    ElMessage.success('已建生产单')
    open.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onStatus(row: Mo, status: string) {
  try {
    await setMoStatus(row.id, status)
    ElMessage.success(`已 → ${status}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onFromPlan() {
  saving.value = true
  try {
    const r = await createMoFromPlan(planId.value)
    ElMessage.success(`下推 ${r.items?.length || 0} 张`)
    planOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

function openBc(row: Mo) {
  bcMo.value = row
  barcode.value = ''
  bcOpen.value = true
}

async function onBc() {
  if (!bcMo.value) return
  saving.value = true
  try {
    await registerMoBarcode(bcMo.value.id, barcode.value)
    ElMessage.success('条码已挂')
    bcOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onIssue(row: Mo) {
  try {
    const doc = await createMaterialDoc({ mo_id: row.id, kind: 'issue', from_bom: true })
    await confirmMaterialDoc(doc.id)
    ElMessage.success(`领料已确认 ${doc.doc_no}`)
    await router.push('/production/material')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '领料失败')
  }
}

async function onQa(row: Mo) {
  try {
    const qa = await createQaFromMo(row.id)
    ElMessage.success(`已建 QA ${qa.qa_no}`)
    await router.push('/production/qa')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
