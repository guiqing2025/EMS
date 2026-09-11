<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">发货单</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            确认发货后挂应收 stub；可查看打印载荷（含打包条码）
          </p>
        </div>
        <el-button @click="load">刷新</el-button>
        <el-button @click="$router.push('/sales/flow')">订单流程</el-button>
      </div>
      <div class="erp-page-body">
        <FlowBacklink v-if="routeSoId" :so-id="routeSoId" />
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="delivery_no" label="发货单号" width="150" />
          <el-table-column prop="issue_no" label="出库单" width="140" />
          <el-table-column prop="so_no" label="销售订单" width="140" />
          <el-table-column prop="customer_name" label="客户" width="140" />
          <el-table-column prop="ship_date" label="发货日" width="110" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="行摘要" min-width="180">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code}×${l.qty}`).join('；') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" :loading="acting === row.id" @click="onConfirm(row)">
                确认发货
              </el-button>
              <el-button link type="primary" @click="onPrint(row)">打印预览</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="printOpen" title="发货单打印预览" width="640px" destroy-on-close>
      <pre v-if="printPayload" style="white-space: pre-wrap; font-size: 13px; margin: 0">{{ printText }}</pre>
      <template #footer>
        <el-button type="primary" @click="printOpen = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import FlowBacklink from '@/components/FlowBacklink.vue'
import { confirmDelivery, fetchDeliveries, fetchDeliveryPrint, type DeliveryNote } from '@/api/shipping'

const route = useRoute()
const routeSoId = computed(() => {
  const n = Number(route.query.so_id || 0)
  return n > 0 ? n : undefined
})
const loading = ref(false)
const acting = ref<number | ''>('')
const rows = ref<DeliveryNote[]>([])
const printOpen = ref(false)
const printPayload = ref<DeliveryNote | null>(null)
const printText = computed(() => {
  const p = printPayload.value
  if (!p) return ''
  const lines = (p.lines || []).map((l) => `  ${l.material_code} ${l.material_name} ×${l.qty}`).join('\n')
  const packs = (p.pack_barcodes || []).map((b) => `  ${b.barcode} 箱=${b.box_no || '-'} ×${b.qty}`).join('\n')
  return [
    `发货单：${p.delivery_no}`,
    `客户：${p.customer_name}`,
    `销售订单：${p.so_no || '-'}`,
    `出库单：${p.issue_no}`,
    `发货日：${p.ship_date || '-'}`,
    `承运/运单：${p.carrier || '-'} / ${p.tracking_no || '-'}`,
    `状态：${p.status}`,
    '',
    '明细：',
    lines || '  （无）',
    '',
    '打包条码：',
    packs || '  （无）',
  ].join('\n')
})

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchDeliveries()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onConfirm(row: DeliveryNote) {
  acting.value = row.id
  try {
    await confirmDelivery(row.id)
    ElMessage.success('发货已确认（应收 stub 已挂）')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    acting.value = ''
  }
}

async function onPrint(row: DeliveryNote) {
  try {
    printPayload.value = await fetchDeliveryPrint(row.id)
    printOpen.value = true
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载打印失败')
  }
}

onMounted(load)
</script>
