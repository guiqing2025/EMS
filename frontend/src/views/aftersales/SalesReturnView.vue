<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">销售退货 / 补发补货</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            从出库/发货下推 → 确认回库 → 补发发货 或 补货回生产
          </p>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="fromOpen = true">从出库单退货</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="return_no" label="退货单号" width="140" />
          <el-table-column prop="so_no" label="销售订单" width="130" />
          <el-table-column prop="issue_no" label="出库单" width="130" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="branch" label="分支" width="100" />
          <el-table-column label="行摘要" min-width="160">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code}×${l.qty}`).join('；') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" @click="onConfirm(row)">确认退货</el-button>
              <el-button
                v-if="row.status === 'confirmed' && row.branch === 'none'"
                link
                type="warning"
                @click="onReissue(row)"
              >
                补发
              </el-button>
              <el-button
                v-if="row.status === 'confirmed' && row.branch === 'none'"
                link
                type="primary"
                @click="onReplenish(row)"
              >
                补货生产
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
    <el-dialog v-model="fromOpen" title="从销售出库单退货" width="400px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="出库单ID"><el-input-number v-model="issueId" :min="1" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="fromOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onFromIssue">下推</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  confirmSalesReturn,
  createReturnFromIssue,
  fetchSalesReturns,
  reissueReturn,
  replenishReturn,
  type SalesReturn,
} from '@/api/aftersales'

const loading = ref(false)
const saving = ref(false)
const fromOpen = ref(false)
const issueId = ref(1)
const rows = ref<SalesReturn[]>([])

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchSalesReturns()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onFromIssue() {
  saving.value = true
  try {
    const r = await createReturnFromIssue(issueId.value)
    ElMessage.success(`已建 ${r.return_no}`)
    fromOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onConfirm(row: SalesReturn) {
  try {
    await confirmSalesReturn(row.id)
    ElMessage.success('退货已确认回库')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onReissue(row: SalesReturn) {
  try {
    const r = await reissueReturn(row.id)
    ElMessage.success(`已补发 出库#${r.reissue_issue_id} 发货#${r.reissue_delivery_id}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onReplenish(row: SalesReturn) {
  try {
    const r = await replenishReturn(row.id)
    ElMessage.success(`已建补货生产单 #${r.replenish_mo_id}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
