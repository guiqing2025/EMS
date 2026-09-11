<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">领料 / 补料 / 退料</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">确认后扣减/退回内部库存</p>
        </div>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="doc_no" label="单号" width="150" />
          <el-table-column prop="kind" label="类型" width="100" />
          <el-table-column prop="mo_no" label="生产单" width="140" />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="行摘要" min-width="200">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code}×${l.qty}`).join('；') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" @click="onConfirm(row)">确认</el-button>
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
import { confirmMaterialDoc, fetchMaterialDocs, type MaterialDoc } from '@/api/production'

const loading = ref(false)
const rows = ref<MaterialDoc[]>([])

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchMaterialDocs()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onConfirm(row: MaterialDoc) {
  try {
    await confirmMaterialDoc(row.id)
    ElMessage.success('已确认')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
