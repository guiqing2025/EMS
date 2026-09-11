<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">借样还入 / 转销售</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            借出中可还入回库，或转销售生成销售订单
          </p>
        </div>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="loan_no" label="借样单号" width="140" />
          <el-table-column prop="customer_name" label="客户" width="120" />
          <el-table-column prop="product_code" label="料号" width="120" />
          <el-table-column prop="qty" label="数量" width="80" />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column prop="converted_so_id" label="转SO" width="90" />
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'lent'" link type="success" @click="onReturn(row)">还入</el-button>
              <el-button
                v-if="row.status === 'lent' || row.status === 'returned'"
                link
                type="primary"
                @click="onConvert(row)"
              >
                转销售
              </el-button>
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
import { convertSampleLoan, fetchSampleLoans, returnSampleLoan, type SampleLoan } from '@/api/aftersales'

const loading = ref(false)
const rows = ref<SampleLoan[]>([])

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchSampleLoans()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onReturn(row: SampleLoan) {
  try {
    await returnSampleLoan(row.id, true)
    ElMessage.success('已还入回库')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onConvert(row: SampleLoan) {
  try {
    const r = await convertSampleLoan(row.id, 0)
    ElMessage.success(`已转销售 ${r.sales_order.so_no}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
