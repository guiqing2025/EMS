<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">成品入库单</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            仅 QA 合格数量可过账入 GOOD；可勾选「入库直接出库」标记
          </p>
        </div>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="receipt_no" label="入库单号" width="150" />
          <el-table-column prop="mo_no" label="生产单" width="140" />
          <el-table-column prop="material_code" label="成品" width="130" />
          <el-table-column prop="qty" label="数量" width="90" align="right" />
          <el-table-column prop="direct_outbound" label="直接出库" width="90">
            <template #default="{ row }">{{ row.direct_outbound ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" @click="onPost(row)">过账</el-button>
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
import { fetchFgReceipts, postFg, type FgDoc } from '@/api/production'

const loading = ref(false)
const rows = ref<FgDoc[]>([])

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchFgReceipts()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onPost(row: FgDoc) {
  try {
    await postFg(row.id)
    ElMessage.success('已过账入 GOOD')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
