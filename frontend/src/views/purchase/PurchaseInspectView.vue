<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">采购入库送检</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            IQC 判定合格/不合格 → 合格生成入库单，不合格生成退货单
          </p>
        </div>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="inspect_no" label="送检单号" width="150" />
          <el-table-column prop="po_no" label="采购单" width="140" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="result" label="结果" width="90" />
          <el-table-column label="行摘要" min-width="200">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code} 送${l.qty}/合${l.pass_qty}/不${l.fail_qty}`).join('；') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="primary" @click="openJudge(row)">IQC判定</el-button>
              <el-button
                v-if="row.status === 'judged' && (row.result === 'pass' || row.result === 'partial')"
                link
                type="success"
                @click="onReceipt(row)"
              >
                生成入库
              </el-button>
              <el-button
                v-if="row.status === 'judged' && (row.result === 'fail' || row.result === 'partial')"
                link
                type="danger"
                @click="onReturn(row)"
              >
                生成退货
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="judgeOpen" title="IQC 判定" width="640px" destroy-on-close>
      <el-table :data="judgeLines" border size="small">
        <el-table-column prop="material_code" label="料号" width="120" />
        <el-table-column prop="qty" label="送检量" width="90" />
        <el-table-column label="合格" width="120">
          <template #default="{ row }"><el-input-number v-model="row.pass_qty" :min="0" :max="row.qty" size="small" /></template>
        </el-table-column>
        <el-table-column label="不合格" width="120">
          <template #default="{ row }"><el-input-number v-model="row.fail_qty" :min="0" :max="row.qty" size="small" /></template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="judgeOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onJudge">提交判定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createReceiptFromInspect,
  createReturnFromInspect,
  fetchInspects,
  judgeInspect,
  type InspectDoc,
} from '@/api/purchase'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const rows = ref<InspectDoc[]>([])
const judgeOpen = ref(false)
const currentId = ref(0)
const judgeLines = ref<Array<{ line_id: number; material_code: string; qty: number; pass_qty: number; fail_qty: number }>>([])

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchInspects()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openJudge(row: InspectDoc) {
  currentId.value = row.id
  judgeLines.value = (row.lines || []).map((l) => ({
    line_id: l.id,
    material_code: l.material_code,
    qty: l.qty,
    pass_qty: l.qty,
    fail_qty: 0,
  }))
  judgeOpen.value = true
}

async function onJudge() {
  saving.value = true
  try {
    await judgeInspect(
      currentId.value,
      judgeLines.value.map((l) => ({ line_id: l.line_id, pass_qty: l.pass_qty, fail_qty: l.fail_qty })),
    )
    ElMessage.success('已判定')
    judgeOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '判定失败')
  } finally {
    saving.value = false
  }
}

async function onReceipt(row: InspectDoc) {
  try {
    const r = await createReceiptFromInspect(row.id)
    ElMessage.success(`已建入库单 ${r.receipt_no}`)
    await router.push('/purchase/receipt')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onReturn(row: InspectDoc) {
  try {
    const r = await createReturnFromInspect(row.id)
    ElMessage.success(`已建退货单 ${r.return_no}`)
    await router.push('/purchase/return')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
