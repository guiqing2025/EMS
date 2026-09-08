<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">仓库管理 · 物料明细</h2>
          <p class="wh-path-info">
            选择客户可查看在制订单齐料；也可输入机型号 / 料号 / 品名查询物料明细
          </p>
          <p class="wh-path-info">{{ shareInfo }}</p>
        </div>
        <div class="wh-toolbar-actions">
          <el-button type="primary" @click="batchInboundOpen = true">批量来料</el-button>
          <el-button type="primary" plain @click="batchIssueOpen = true">按订单发料</el-button>
          <el-button @click="downloadWarehouseTemplate">下载模板</el-button>
          <el-button @click="exportWarehouseInventory">导出库存</el-button>
        </div>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" class="wh-filter" @submit.prevent="onSearch">
          <el-form-item label="客户">
            <el-select v-model="customerId" clearable placeholder="全部客户" style="width: 140px" @change="onCustomerChange">
              <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="keyword"
              placeholder="机型号 / 料号 / 品名（查询后显示明细）"
              clearable
              style="width: 280px"
              @keyup.enter="onSearch"
              @clear="onClearKeyword"
            />
          </el-form-item>
          <el-form-item v-if="listRevealed && viewMode === 'model'" label="套数">
            <el-input-number v-model="orderQty" :min="0" :step="1" controls-position="right" style="width: 110px" @change="reloadModel" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="onSearch">查询</el-button>
            <el-button v-if="viewMode === 'model' && customerId" @click="backToOpenOrders">返回在制订单</el-button>
            <el-button v-if="listRevealed" @click="clearList">清除</el-button>
          </el-form-item>
        </el-form>

        <el-empty
          v-if="!listRevealed"
          description="请先选择客户查看在制订单齐料，或输入机型号/料号后点「查询」"
          :image-size="72"
          style="padding: 48px 0"
        />

        <template v-else>
        <p v-if="viewMode === 'list' && materials.length >= 500" class="wh-hint">
          当前仅显示前 500 条库存，请缩小「料号/机型号」关键词后查看。
        </p>

        <div v-if="modelInfo" class="wh-model-banner">
          <span>
            机型 <strong>{{ modelInfo.model_code }}</strong>
            <template v-if="modelInfo.purchase_no">
              · <span class="wh-order-chip">订单 {{ modelInfo.purchase_no }}</span>
            </template>
            <template v-else>
              · <span class="wh-order-missing">未关联订单号</span>
            </template>
            <template v-if="modelInfo.model_name"> · {{ modelInfo.model_name }}</template>
            · {{ modelInfo.customer_name }} · BOM {{ modelInfo.total_lines }} 项
            · 齐套
            <el-tag size="small" :type="statusTagType(modelInfo.material_status)" effect="plain">
              {{ statusLabel(modelInfo.material_status) }}
            </el-tag>
            （齐 {{ modelInfo.ready_count }} / 缺 {{ modelInfo.shortage_count }} / 部分 {{ modelInfo.partial_count }}）
          </span>
        </div>

        <div v-if="candidates.length" class="wh-candidates">
          <span class="wh-candidates-label">在制订单（共 {{ candidates.length }}）：</span>
          <el-button
            v-for="c in candidates"
            :key="(c.purchase_no || '') + '-' + (c.id || 0)"
            size="small"
            :type="isSelectedCandidate(c) ? 'success' : (c.bom_status === 'pending' ? 'info' : 'primary')"
            :plain="!isSelectedCandidate(c)"
            @click="selectCandidate(c)"
          >
            {{ c.purchase_no || '—' }}
            <template v-if="c.bom_status === 'pending'"> · 待确认 BOM</template>
            <template v-else> · 已确认（{{ c.line_count }} 项）</template>
            <template v-if="isSelectedCandidate(c)"> · 当前</template>
          </el-button>
        </div>

        <p class="wh-hint">
          <template v-if="viewMode === 'orders'">
            下表为该客户在制订单；点击一行可展开 BOM 用料与当前库存齐料明细。
          </template>
          <template v-else-if="viewMode === 'model'">
            下表为该订单已确认 BOM 的用料及当前库存；点击料号行可查看单物料明细（无库存账时自动建零库存档案）。
          </template>
          <template v-else>
            输入机型号可按在制订单展开 BOM 用料（同机型不同订单需分开选）；也可按料号/品名查询。
          </template>
        </p>

        <!-- 客户在制订单列表 -->
        <el-table
          v-if="viewMode === 'orders'"
          v-loading="loading"
          :data="openOrders"
          stripe
          border
          size="small"
          class="wh-table-click wh-materials-table"
          max-height="calc(100vh - 300px)"
          @row-click="onOpenOrderClick"
        >
          <el-table-column prop="purchase_no" label="订单号" width="150" show-overflow-tooltip />
          <el-table-column prop="model_code" label="机型" width="140" show-overflow-tooltip />
          <el-table-column prop="model_name" label="品名" min-width="140" show-overflow-tooltip />
          <el-table-column label="订单数量" width="88" align="right">
            <template #default="{ row }">{{ fmtWhQty(row.order_qty) }}</template>
          </el-table-column>
          <el-table-column label="BOM" width="110" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.bom_status === 'imported'" size="small" type="success" effect="plain">
                已确认 {{ row.line_count }} 项
              </el-tag>
              <el-tag v-else size="small" type="info" effect="plain">待导入</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="齐料状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.material_status)" effect="plain">
                {{ row.material_status_label || statusLabel(row.material_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="客户齐套" width="100" align="center">
            <template #default="{ row }">
              <span v-if="row.customer_kit_status === 'na'" class="cell-muted">—</span>
              <el-tag v-else size="small" :type="kitTagType(row.customer_kit_status)" effect="plain">
                {{ row.customer_kit_status_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="88" align="center" fixed="right">
            <template #default>
              <el-button link type="primary" size="small">查看 BOM</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 机型 BOM 物料表 -->
        <el-table
          v-else-if="viewMode === 'model'"
          v-loading="loading"
          :data="modelLines"
          stripe
          border
          size="small"
          class="wh-table-click wh-materials-table"
          max-height="calc(100vh - 320px)"
          @row-click="onModelRowClick"
        >
          <el-table-column prop="material_code" label="料号" width="128" show-overflow-tooltip />
          <el-table-column prop="material_name" label="品名" width="90" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" min-width="140" show-overflow-tooltip />
          <el-table-column label="位号" min-width="180">
            <template #default="{ row }">
              <span class="wh-refdes">{{ row.position || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="单位用量" width="72" align="right">
            <template #default="{ row }">{{ fmtWhQty(row.qty_per) }}</template>
          </el-table-column>
          <el-table-column label="需求" width="64" align="right">
            <template #default="{ row }">{{ fmtWhQty(row.required_qty) }}</template>
          </el-table-column>
          <el-table-column label="库存" width="56" align="right">
            <template #default="{ row }">
              <span :class="{ 'qty-negative': row.stock_qty < 0 }">{{ fmtWhQty(row.stock_qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="可用" width="64" align="right">
            <template #default="{ row }">
              <strong>{{ fmtWhQty(row.available_qty) }}</strong>
              <span v-if="row.substitute_codes?.length" class="cell-muted"> ·{{ row.substitute_codes.length }}关联</span>
            </template>
          </el-table-column>
          <el-table-column label="缺料" width="56" align="right">
            <template #default="{ row }">
              <span :class="{ 'qty-negative': row.shortage_qty > 0 }">{{ fmtWhQty(row.shortage_qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="64" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <!-- 普通库存列表 -->
        <el-table
          v-else
          v-loading="loading"
          :data="materials"
          stripe
          border
          size="small"
          class="wh-table-click wh-materials-table"
          max-height="calc(100vh - 300px)"
          @row-click="onMaterialRowClick"
        >
          <el-table-column prop="customer_name" label="客户" width="64" show-overflow-tooltip />
          <el-table-column label="料号" width="128" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.is_substitute_alias" class="cell-muted">[替] </span>{{ row.material_code }}
            </template>
          </el-table-column>
          <el-table-column prop="material_name" label="品名" width="80" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" min-width="140" show-overflow-tooltip />
          <el-table-column label="库存" width="56" align="right">
            <template #default="{ row }">
              <span :class="{ 'qty-negative': row.qty < 0 }">{{ fmtWhQty(row.qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="盘点+来料" width="72" align="right">
            <template #default="{ row }">
              {{ fmtWhQty((row.excel_count_qty ?? 0) + (row.excel_in_qty ?? 0)) }}
            </template>
          </el-table-column>
          <el-table-column label="可用" width="64" align="right" show-overflow-tooltip>
            <template #default="{ row }">
              <strong>{{ fmtWhQty(row.available_qty) }}</strong>
              <span v-if="row.substitute_codes?.length" class="cell-muted"> ·{{ row.substitute_codes.length }}关联</span>
            </template>
          </el-table-column>
          <el-table-column label="来料数" width="56" align="right">
            <template #default="{ row }">{{ fmtWhQty(row.excel_in_qty) }}</template>
          </el-table-column>
          <el-table-column label="需求数" width="56" align="right">
            <template #default="{ row }">{{ fmtWhQty(row.excel_demand_qty) }}</template>
          </el-table-column>
          <el-table-column label="最近操作" width="168" show-overflow-tooltip>
            <template #default="{ row }">
              <template v-if="row.last_op_at">
                {{ row.last_op_type_name || '操作' }} {{ fmtDate(row.last_op_at) }}
                · {{ compactParty(row) }}
              </template>
              <span v-else class="cell-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="同步时间" width="136">
            <template #default="{ row }">{{ fmtDate(row.excel_synced_at) }}</template>
          </el-table-column>
        </el-table>
        </template>
      </div>
    </div>

    <MaterialDetailDrawer
      v-model="detailOpen"
      :material-id="detailMaterialId"
      :reload-token="detailReloadTick"
      @saved="onDetailSaved"
    />
    <BatchInboundDialog v-model="batchInboundOpen" :default-customer-id="customerId" @saved="onBatchSaved" />
    <BatchIssueDialog v-model="batchIssueOpen" @saved="onBatchSaved" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  downloadWarehouseTemplate,
  ensureWarehouseMaterial,
  exportWarehouseInventory,
  fetchMaterials,
  fetchMaterialsByModel,
  fetchOpenOrders,
  fetchWarehouseConfig,
  fetchWarehouseCustomers,
  syncWarehouseShare,
} from '@/api/warehouse'
import BatchInboundDialog from '@/components/warehouse/BatchInboundDialog.vue'
import BatchIssueDialog from '@/components/warehouse/BatchIssueDialog.vue'
import MaterialDetailDrawer from '@/components/warehouse/MaterialDetailDrawer.vue'
import type {
  WarehouseBomModelCandidate,
  WarehouseCustomer,
  WarehouseMaterial,
  WarehouseModelMaterialLine,
  WarehouseModelMaterials,
  WarehouseOpenOrder,
} from '@/types/warehouse'
import { fmtDate } from '@/utils/format'
import { fmtWhQty } from '@/utils/warehouse'

function compactParty(row: WarehouseMaterial) {
  const giver = row.last_op_giver || '—'
  const receiver = row.last_op_receiver || '—'
  return `${giver}→${receiver}`
}

function statusLabel(status: string) {
  if (status === 'ready') return '齐'
  if (status === 'partial') return '部分'
  if (status === 'shortage') return '缺'
  if (status === 'unbound') return '未绑 BOM'
  return status || '—'
}

function statusTagType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ready') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'shortage') return 'danger'
  return 'info'
}

function kitTagType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ready') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'unkit') return 'danger'
  return 'info'
}

const customerId = ref('')
const keyword = ref('')
const orderQty = ref(1)
const shareInfo = ref('')
const loading = ref(false)
const syncing = ref(false)
const listRevealed = ref(false)
const detailOpen = ref(false)
const detailMaterialId = ref<number | null>(null)
const detailReloadTick = ref(0)
const batchInboundOpen = ref(false)
const batchIssueOpen = ref(false)

const customers = ref<WarehouseCustomer[]>([])
const materials = ref<WarehouseMaterial[]>([])
const openOrders = ref<WarehouseOpenOrder[]>([])
const viewMode = ref<'list' | 'model' | 'orders'>('list')
const modelInfo = ref<WarehouseModelMaterials | null>(null)
const modelLines = ref<WarehouseModelMaterialLine[]>([])
const candidates = ref<WarehouseBomModelCandidate[]>([])
const selectedBomModelId = ref<number | null>(null)
let searchSeq = 0

function clearList() {
  listRevealed.value = false
  keyword.value = ''
  materials.value = []
  openOrders.value = []
  modelInfo.value = null
  modelLines.value = []
  candidates.value = []
  selectedBomModelId.value = null
  viewMode.value = 'list'
  loading.value = false
}

async function loadConfig() {
  const cfg = await fetchWarehouseConfig()
  shareInfo.value = cfg.share_accessible
    ? `共享盘已连接：${cfg.share_resolved}`
    : `共享盘未挂载（配置路径：${cfg.share_path}），请先在 Mac 上挂载后再导入`
}

async function loadCustomers() {
  customers.value = await fetchWarehouseCustomers()
}

async function loadOpenOrders() {
  if (!customerId.value) {
    clearList()
    return
  }
  const seq = ++searchSeq
  listRevealed.value = true
  loading.value = true
  viewMode.value = 'orders'
  materials.value = []
  modelInfo.value = null
  modelLines.value = []
  candidates.value = []
  selectedBomModelId.value = null
  try {
    const rows = await fetchOpenOrders(customerId.value)
    if (seq !== searchSeq) return
    openOrders.value = rows
    if (!rows.length) {
      ElMessage.info('该客户暂无在制订单')
    }
  } catch (e) {
    if (seq !== searchSeq) return
    openOrders.value = []
    ElMessage.error(e instanceof Error ? e.message : '加载在制订单失败')
  } finally {
    if (seq === searchSeq) loading.value = false
  }
}

async function loadMaterials() {
  if (!listRevealed.value) return
  const seq = ++searchSeq
  loading.value = true
  viewMode.value = 'list'
  modelInfo.value = null
  modelLines.value = []
  candidates.value = []
  openOrders.value = []
  selectedBomModelId.value = null
  try {
    const rows = await fetchMaterials(customerId.value, keyword.value.trim())
    if (seq !== searchSeq) return
    materials.value = rows
  } catch (e) {
    if (seq !== searchSeq) return
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    if (seq === searchSeq) loading.value = false
  }
}

async function loadByModel(bomModelId?: number | null, purchaseNo?: string, modelCode?: string) {
  if (!listRevealed.value) return
  const code = (modelCode || keyword.value.trim() || modelInfo.value?.model_code || '').trim()
  if (!code && !bomModelId) {
    if (customerId.value) {
      await loadOpenOrders()
    } else {
      await loadMaterials()
    }
    return
  }
  const seq = ++searchSeq
  loading.value = true
  try {
    const res = await fetchMaterialsByModel({
      modelCode: code || undefined,
      orderQty: orderQty.value || 1,
      customerId: customerId.value || undefined,
      bomModelId: bomModelId ?? selectedBomModelId.value,
      purchaseNo: purchaseNo || undefined,
    })
    if (seq !== searchSeq) return
    if (res.matched) {
      viewMode.value = 'model'
      modelInfo.value = res
      modelLines.value = res.lines || []
      candidates.value = res.candidates || []
      selectedBomModelId.value = res.bom_model_id ?? bomModelId ?? null
      materials.value = []
      openOrders.value = []
      if (!modelLines.value.length) {
        ElMessage.warning('该订单 BOM 暂无物料行')
      }
      return
    }
    if (res.candidates?.length) {
      viewMode.value = 'list'
      materials.value = []
      openOrders.value = []
      modelInfo.value = null
      modelLines.value = []
      candidates.value = res.candidates
      ElMessage.info(res.message || '请选择在制订单')
      return
    }
    // 未命中 → 回退料号/品名搜索
    candidates.value = []
    modelInfo.value = null
    modelLines.value = []
    selectedBomModelId.value = null
    openOrders.value = []
    viewMode.value = 'list'
    materials.value = await fetchMaterials(customerId.value, code)
    if (seq !== searchSeq) return
    if (!materials.value.length) {
      ElMessage.warning(res.message || `未找到机型或物料「${code}」`)
    }
  } catch (e) {
    if (seq !== searchSeq) return
    try {
      materials.value = await fetchMaterials(customerId.value, code)
      viewMode.value = 'list'
      openOrders.value = []
      if (!materials.value.length) {
        ElMessage.error(e instanceof Error ? e.message : '机型查询失败')
      }
    } catch (e2) {
      ElMessage.error(e2 instanceof Error ? e2.message : '查询失败')
    }
  } finally {
    if (seq === searchSeq) loading.value = false
  }
}

async function onSearch() {
  const kw = keyword.value.trim()
  if (!kw) {
    if (customerId.value) {
      await loadOpenOrders()
      return
    }
    ElMessage.warning('请先选择客户，或输入机型号/料号/品名后再查询')
    return
  }
  listRevealed.value = true
  selectedBomModelId.value = null
  await loadByModel()
}

function onCustomerChange() {
  keyword.value = ''
  if (!customerId.value) {
    clearList()
    return
  }
  loadOpenOrders()
}

function backToOpenOrders() {
  keyword.value = ''
  loadOpenOrders()
}

async function reloadModel() {
  if (!listRevealed.value || viewMode.value !== 'model') return
  await loadByModel(
    selectedBomModelId.value,
    modelInfo.value?.purchase_no || undefined,
    modelInfo.value?.model_code || undefined,
  )
}

function selectCandidate(c: WarehouseBomModelCandidate) {
  if (!c.id || c.bom_status === 'pending') {
    ElMessage.warning(
      `订单 ${c.purchase_no || ''} 尚未确认 BOM，请先到「工程管理 → 工程资料」按该订单导入后再查询用料`,
    )
    return
  }
  selectedBomModelId.value = c.id
  if (c.order_qty && c.order_qty > 0) {
    orderQty.value = c.order_qty
  }
  loadByModel(c.id, c.purchase_no, c.model_code)
}

function onOpenOrderClick(row: WarehouseOpenOrder) {
  if (!row.bom_model_id || row.bom_status !== 'imported') {
    ElMessage.warning(
      `订单 ${row.purchase_no || ''} 尚未确认 BOM，请先到「工程管理 → 工程资料」按该订单导入后再查看用料`,
    )
    return
  }
  selectedBomModelId.value = row.bom_model_id
  if (row.order_qty && row.order_qty > 0) {
    orderQty.value = row.order_qty
  }
  listRevealed.value = true
  loadByModel(row.bom_model_id, row.purchase_no, row.model_code)
}

function isSelectedCandidate(c: WarehouseBomModelCandidate) {
  if (selectedBomModelId.value && c.id) {
    return Number(c.id) === Number(selectedBomModelId.value)
  }
  const pn = (modelInfo.value?.purchase_no || '').trim()
  return !!pn && pn === (c.purchase_no || '').trim()
}

function onClearKeyword() {
  if (customerId.value) {
    loadOpenOrders()
    return
  }
  clearList()
}

function onMaterialRowClick(row: WarehouseMaterial) {
  detailMaterialId.value = row.id
  detailOpen.value = true
}

async function onModelRowClick(row: WarehouseModelMaterialLine) {
  let mid = row.material_id
  if (!mid) {
    const cid = (modelInfo.value?.customer_id || customerId.value || '').trim()
    if (!cid) {
      ElMessage.warning('请先选择客户后再打开明细')
      return
    }
    const code = (row.material_code || '').trim()
    if (!code) {
      ElMessage.warning('料号为空，无法建档')
      return
    }
    try {
      const mat = await ensureWarehouseMaterial({
        customer_id: cid,
        material_code: code,
        material_name: row.material_name || undefined,
        spec: row.spec || undefined,
        unit: row.unit || 'PCS',
      })
      mid = mat.id
      row.material_id = mat.id
      ElMessage.success(`已为 ${code} 建立零库存档案`)
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '建档失败')
      return
    }
  }
  detailMaterialId.value = mid
  detailOpen.value = true
}

async function onSyncShare() {
  syncing.value = true
  try {
    const res = await syncWarehouseShare()
    const ok = (res.files || []).filter((f) => f.status === 'success').length
    ElMessage.success(res.message || `已同步 ${ok} 个客户`)
    if (listRevealed.value) {
      if (viewMode.value === 'model') {
        await reloadModel()
      } else if (viewMode.value === 'orders') {
        await loadOpenOrders()
      } else {
        await loadMaterials()
      }
    }
    if (detailOpen.value && detailMaterialId.value) {
      detailReloadTick.value += 1
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '同步失败')
  } finally {
    syncing.value = false
  }
}

function onDetailSaved() {
  if (!listRevealed.value) return
  if (viewMode.value === 'model') reloadModel()
  else if (viewMode.value === 'orders') loadOpenOrders()
  else loadMaterials()
}

function onBatchSaved() {
  if (listRevealed.value) {
    if (viewMode.value === 'model') reloadModel()
    else if (viewMode.value === 'orders') loadOpenOrders()
    else loadMaterials()
  }
  if (detailOpen.value && detailMaterialId.value) {
    detailReloadTick.value += 1
  }
}

onMounted(() => {
  loadConfig().catch(() => {
    shareInfo.value = '共享盘状态暂时不可用'
  })
  loadCustomers().catch((e) => {
    ElMessage.error(e instanceof Error ? e.message : '客户列表加载失败')
  })
})
</script>

<style scoped>
.wh-path-info {
  margin: 4px 0 0;
  color: var(--erp-text-muted);
  font-size: 12px;
  max-width: 520px;
}
.wh-toolbar-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.wh-filter {
  margin-bottom: 4px;
}
.wh-filter :deep(.el-form-item) {
  margin-bottom: 8px;
}
.wh-hint {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--erp-text-muted);
}
.wh-model-banner {
  margin: 0 0 8px;
  padding: 8px 12px;
  background: #f0f7ff;
  border: 1px solid #d6e8ff;
  border-radius: 6px;
  font-size: 13px;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.wh-order-chip {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 700;
}
.wh-order-missing {
  color: #b45309;
  font-weight: 600;
}
.wh-candidates {
  margin: 0 0 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.wh-candidates-label {
  font-size: 13px;
  color: var(--erp-text-muted);
}
.cell-muted {
  color: var(--erp-text-muted);
  font-size: 11px;
}
.wh-refdes {
  display: block;
  white-space: normal;
  word-break: break-word;
  line-height: 1.4;
  font-size: 12px;
}
:deep(.wh-materials-table .wh-refdes) {
  padding: 2px 0;
}
.qty-negative {
  color: #dc2626;
  font-weight: 600;
}
:deep(.wh-table-click .el-table__row) {
  cursor: pointer;
}
:deep(.wh-materials-table.el-table--small .el-table__cell) {
  padding: 2px 0;
}
:deep(.wh-materials-table.el-table--small .cell) {
  padding: 0 3px;
  line-height: 1.25;
  font-size: 12px;
}
:deep(.wh-materials-table .el-table__header .cell) {
  padding: 0 3px;
}
</style>
