<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">仓库管理 · 批次记录</h2>
          <p class="hint">
            扫或输入板码 / 批次号 SH-xxx，可查何时出库、与哪些编码同批、共多少片、谁操作的。
            扫错了且尚未出库：可删除该板码入库记录。
          </p>
        </div>
        <el-button :loading="loading" @click="loadRows">刷新</el-button>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" class="filter" @submit.prevent="onSearch">
          <el-form-item>
            <el-input
              ref="keywordInput"
              v-model="keyword"
              placeholder="板码 / 批次号 SH- / 订单号 / 品号"
              clearable
              style="width: 360px"
              @keyup.enter="onSearch"
              @clear="onSearch"
            />
          </el-form-item>
          <el-form-item>
            <el-select v-model="status" style="width: 140px" @change="loadRows">
              <el-option label="全部状态" value="" />
              <el-option label="待审核" value="pending" />
              <el-option label="已出库" value="approved" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading || lookupBusy" @click="onSearch">查询</el-button>
            <el-button
              type="danger"
              plain
              :loading="deletingScan"
              :disabled="!canDeleteScan"
              @click="onDeleteScan"
            >
              删除该板码
            </el-button>
          </el-form-item>
        </el-form>

        <el-alert
          v-if="barcodeHint"
          :title="barcodeHint"
          :type="lookupDetail?.shipment ? 'success' : 'warning'"
          show-icon
          :closable="false"
          style="margin-bottom: 12px"
        />

        <el-card v-if="lookupDetail?.shipment" class="detail-card" shadow="never">
          <template #header>
            <div class="detail-head">
              <span>批次 {{ lookupDetail.shipment.shipment_no }}</span>
              <el-tag size="small" :type="statusType(lookupDetail.shipment.approval_status)">
                {{ lookupDetail.shipment.status_label }}
              </el-tag>
            </div>
          </template>
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="订单号">{{ lookupDetail.shipment.purchase_no || '—' }}</el-descriptions-item>
            <el-descriptions-item label="品号">{{ lookupDetail.shipment.product_goods_no || '—' }}</el-descriptions-item>
            <el-descriptions-item label="客户">{{ lookupDetail.shipment.customer_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="本批数量">{{ lookupDetail.batch_total }} 片</el-descriptions-item>
            <el-descriptions-item label="出库日期">{{ lookupDetail.shipment.ship_date || '—' }}</el-descriptions-item>
            <el-descriptions-item label="箱数">{{ lookupDetail.shipment.box_count || '—' }}</el-descriptions-item>
            <el-descriptions-item label="登记人">{{ lookupDetail.shipment.operator || '—' }}</el-descriptions-item>
            <el-descriptions-item label="审核人">{{ lookupDetail.shipment.approved_by || '—' }}</el-descriptions-item>
            <el-descriptions-item label="审核时间">{{ lookupDetail.shipment.approved_at || '—' }}</el-descriptions-item>
            <el-descriptions-item v-if="lookupDetail.scan?.barcode" label="当前板码" :span="3">
              {{ lookupDetail.scan.barcode }}
              <span class="muted">（入库 {{ lookupDetail.scan.scanned_at || '—' }} · {{ lookupDetail.scan.operator || '—' }}）</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="lookupDetail.shipment.remark" label="备注" :span="3">
              {{ lookupDetail.shipment.remark }}
            </el-descriptions-item>
          </el-descriptions>
          <div class="detail-actions">
            <el-button type="primary" link @click="openDetail(lookupDetail.shipment!)">查看同批板码</el-button>
            <el-button type="primary" link :loading="exportingId === lookupDetail.shipment.id" @click="onExport(lookupDetail.shipment!)">
              导出板码 Excel
            </el-button>
          </div>
        </el-card>

        <el-table
          :data="rows"
          border
          stripe
          v-loading="loading"
          :row-class-name="rowClassName"
          empty-text="还没有出库批次记录"
        >
          <el-table-column prop="shipment_no" label="批次号" min-width="170" />
          <el-table-column prop="purchase_no" label="订单号" min-width="140" show-overflow-tooltip />
          <el-table-column prop="product_goods_no" label="品号" min-width="130" show-overflow-tooltip />
          <el-table-column prop="product_goods_name" label="品名" min-width="120" show-overflow-tooltip />
          <el-table-column prop="customer_name" label="客户" min-width="100" show-overflow-tooltip />
          <el-table-column prop="qty" label="数量" width="80" align="right" />
          <el-table-column prop="ship_date" label="出库日期" width="110" />
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.approval_status)">{{ row.status_label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="operator" label="登记人" width="100" show-overflow-tooltip />
          <el-table-column prop="approved_by" label="审核人" width="100" show-overflow-tooltip />
          <el-table-column prop="created_at" label="创建时间" width="170" show-overflow-tooltip />
          <el-table-column label="操作" width="200" align="center" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openDetail(row)">同批板码</el-button>
              <el-button link type="primary" size="small" :loading="exportingId === row.id" @click="onExport(row)">
                导出
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-drawer v-model="drawerOpen" :title="drawerTitle" size="520px" destroy-on-close>
      <div v-loading="drawerLoading">
        <p v-if="drawerShipment" class="drawer-meta">
          {{ drawerShipment.purchase_no }} · {{ drawerShipment.product_goods_no }} · 共 {{ drawerTotal }} 片
        </p>
        <el-table :data="drawerBarcodes" border stripe max-height="70vh" size="small">
          <el-table-column type="index" label="#" width="50" />
          <el-table-column prop="barcode" label="板码" min-width="180" show-overflow-tooltip />
          <el-table-column prop="operator" label="入库人" width="90" show-overflow-tooltip />
          <el-table-column prop="scanned_at" label="入库时间" width="150" show-overflow-tooltip />
          <el-table-column prop="shipped_at" label="出库时间" width="150" show-overflow-tooltip />
        </el-table>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteInboundScan,
  exportShipmentRecordBlob,
  fetchShipmentRecordBarcodes,
  fetchShipmentRecords,
  lookupShipmentRecord,
  type ShipmentRecordLookup,
  type ShipmentRecordRow,
} from '@/api/packing'

const loading = ref(false)
const lookupBusy = ref(false)
const deletingScan = ref(false)
const exportingId = ref<number | null>(null)
const keyword = ref('')
const status = ref('')
const rows = ref<ShipmentRecordRow[]>([])
const highlightId = ref<number | null>(null)
const barcodeHint = ref('')
const matchedBarcode = ref('')
const lookupDetail = ref<ShipmentRecordLookup | null>(null)

const drawerOpen = ref(false)
const drawerLoading = ref(false)
const drawerTitle = ref('')
const drawerShipment = ref<ShipmentRecordRow | null>(null)
const drawerBarcodes = ref<ShipmentRecordLookup['batch_barcodes']>([])
const drawerTotal = ref(0)

const canDeleteScan = computed(() => {
  const code = matchedBarcode.value.trim() || keyword.value.trim()
  if (!code || code.toUpperCase().startsWith('SH-')) return false
  return !lookupDetail.value?.shipment
})

function statusType(st?: string) {
  const v = (st || '').trim()
  if (v === 'pending') return 'warning'
  return 'success'
}

function rowClassName({ row }: { row: ShipmentRecordRow }) {
  return highlightId.value && row.id === highlightId.value ? 'hit-row' : ''
}

async function loadRows() {
  loading.value = true
  try {
    const data = await fetchShipmentRecords({
      keyword: keyword.value.trim(),
      status: status.value,
      limit: 300,
    })
    rows.value = data.items || []
    highlightId.value = data.highlight_id ?? null
    barcodeHint.value = data.barcode_hint || ''
    matchedBarcode.value = data.matched_barcode || ''
    if (data.barcode_hint && !lookupDetail.value) {
      lookupDetail.value = null
    }
  } catch (e) {
    rows.value = []
    ElMessage.error(e instanceof Error ? e.message : '加载批次记录失败')
  } finally {
    loading.value = false
  }
}

async function onSearch() {
  const q = keyword.value.trim()
  lookupDetail.value = null
  if (q && !q.toUpperCase().startsWith('SH-') && q.length >= 5) {
    lookupBusy.value = true
    try {
      lookupDetail.value = await lookupShipmentRecord(q)
      matchedBarcode.value = lookupDetail.value.scan?.barcode || q
      barcodeHint.value =
        lookupDetail.value.message ||
        (lookupDetail.value.shipment
          ? `板码 ${matchedBarcode.value} 在批次 ${lookupDetail.value.shipment.shipment_no}`
          : `板码 ${matchedBarcode.value} 已入库，尚未出库`)
      if (lookupDetail.value.shipment) {
        highlightId.value = lookupDetail.value.shipment.id
      }
    } catch {
      /* 按列表关键词继续查 */
    } finally {
      lookupBusy.value = false
    }
  }
  await loadRows()
}

async function openDetail(row: ShipmentRecordRow) {
  drawerOpen.value = true
  drawerTitle.value = `批次 ${row.shipment_no} · 同批板码`
  drawerShipment.value = row
  drawerLoading.value = true
  drawerBarcodes.value = []
  drawerTotal.value = 0
  try {
    const data = await fetchShipmentRecordBarcodes(row.id)
    drawerShipment.value = data.shipment
    drawerBarcodes.value = data.items || []
    drawerTotal.value = data.total || 0
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载板码失败')
  } finally {
    drawerLoading.value = false
  }
}

async function onExport(row: ShipmentRecordRow) {
  exportingId.value = row.id
  try {
    const { blob, filename } = await exportShipmentRecordBlob(row.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导出失败')
  } finally {
    exportingId.value = null
  }
}

async function onDeleteScan() {
  const code = matchedBarcode.value.trim() || keyword.value.trim()
  if (!code) {
    ElMessage.warning('请先在搜索框填入或扫入要删的板码')
    return
  }
  try {
    await ElMessageBox.confirm(
      `删除板码 ${code} 的入库记录？仅适用于尚未出库的板码。产线过站记录不动。`,
      '删除该板码',
      { type: 'warning', confirmButtonText: '删除入库', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  deletingScan.value = true
  try {
    const data = await deleteInboundScan(code)
    ElMessage.success(`已删除 ${data.barcode}`)
    keyword.value = ''
    lookupDetail.value = null
    matchedBarcode.value = ''
    barcodeHint.value = ''
    await loadRows()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  } finally {
    deletingScan.value = false
  }
}

onMounted(() => {
  void loadRows()
})
</script>

<style scoped>
.hint {
  margin: 4px 0 0;
  color: var(--erp-text-muted);
  font-size: 13px;
}
.filter {
  margin-bottom: 12px;
}
.muted {
  color: var(--erp-text-muted);
  font-size: 12px;
}
.detail-card {
  margin-bottom: 12px;
}
.detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.detail-actions {
  margin-top: 12px;
}
.drawer-meta {
  margin: 0 0 12px;
  color: var(--erp-text-muted);
  font-size: 13px;
}
:deep(.hit-row) {
  --el-table-tr-bg-color: #f0f9eb;
}
</style>
