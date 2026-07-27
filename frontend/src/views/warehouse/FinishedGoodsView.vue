<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">仓库管理 · 成品库存</h2>
          <p class="wh-path-info">
            入库数 = 本系统包装扫码（不含旧站历史）；结存 = 订单数量 − 客户收货数 − 入库数；待出库
            = 已入库未发货；发货生成出库单
          </p>
        </div>
        <el-button :loading="loading" @click="loadRows">刷新</el-button>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" class="wh-filter" @submit.prevent="loadRows">
          <el-form-item label="客户">
            <el-select
              v-model="customerId"
              clearable
              placeholder="全部客户"
              style="width: 140px"
              @change="loadRows"
            >
              <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="keyword"
              placeholder="订单号 / 机型 / 品名"
              clearable
              style="width: 220px"
              @keyup.enter="loadRows"
              @clear="loadRows"
            />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="onlyWithInbound" @change="loadRows">仅有入库</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="includeCompleted" @change="loadRows">含已结案</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" @click="loadRows">查询</el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="loading" :data="rows" border stripe size="small" empty-text="暂无成品库存数据">
          <el-table-column prop="customer_name" label="客户" width="100" show-overflow-tooltip />
          <el-table-column prop="purchase_no" label="订单号" min-width="140" show-overflow-tooltip />
          <el-table-column prop="model_code" label="机型" min-width="130" show-overflow-tooltip />
          <el-table-column prop="model_name" label="品名" min-width="120" show-overflow-tooltip />
          <el-table-column label="订单数量" width="90" align="right">
            <template #default="{ row }">{{ fmtNum(row.order_qty) }}</template>
          </el-table-column>
          <el-table-column label="客户收货数" width="100" align="right">
            <template #default="{ row }">{{ fmtNum(row.receive_qty) }}</template>
          </el-table-column>
          <el-table-column label="入库数" width="80" align="right">
            <template #default="{ row }">
              <span :title="`本系统：待出库 ${row.pending_qty} + 已出库 ${row.shipped_qty}（不含旧站迁移）`">
                {{ row.inbound_qty }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="订单结存数" width="100" align="right">
            <template #default="{ row }">
              <span :class="{ 'fg-balance-neg': row.balance_qty < 0 }">{{ fmtNum(row.balance_qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="待出库" width="72" align="right">
            <template #default="{ row }">{{ row.pending_qty }}</template>
          </el-table-column>
          <el-table-column v-if="canShip" label="操作" width="88" fixed="right" align="center">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                size="small"
                :disabled="!(row.pending_qty > 0 && !row.is_completed)"
                @click="openShip(row)"
              >
                发货
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <ShipDialog
      v-model="shipOpen"
      :line-key="shipTarget.lineKey"
      :pending-qty="shipTarget.pendingQty"
      @shipped="loadRows"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ShipDialog from '@/components/orders/ShipDialog.vue'
import { fetchFinishedGoods, fetchWarehouseCustomers } from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import type { FinishedGoodsRow, WarehouseCustomer } from '@/types/warehouse'

const auth = useAuthStore()
const loading = ref(false)
const rows = ref<FinishedGoodsRow[]>([])
const customers = ref<WarehouseCustomer[]>([])
const customerId = ref('')
const keyword = ref('')
const onlyWithInbound = ref(false)
const includeCompleted = ref(false)
const shipOpen = ref(false)
const shipTarget = reactive({ lineKey: '', pendingQty: 0 })

const canShip = computed(() => {
  const role = auth.user?.role
  return role === 'admin' || role === 'planner' || role === 'warehouse'
})

function fmtNum(v: number) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '')
}

async function loadCustomers() {
  try {
    customers.value = await fetchWarehouseCustomers()
  } catch {
    customers.value = []
  }
}

async function loadRows() {
  loading.value = true
  try {
    rows.value = await fetchFinishedGoods({
      customerId: customerId.value,
      keyword: keyword.value.trim(),
      includeCompleted: includeCompleted.value,
      onlyWithInbound: onlyWithInbound.value,
    })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
    rows.value = []
  } finally {
    loading.value = false
  }
}

function openShip(row: FinishedGoodsRow) {
  shipTarget.lineKey = row.line_key
  shipTarget.pendingQty = row.pending_qty || 0
  shipOpen.value = true
}

onMounted(async () => {
  await loadCustomers()
  await loadRows()
})
</script>

<style scoped>
.wh-path-info {
  margin: 4px 0 0;
  color: var(--erp-text-muted);
  font-size: 13px;
}
.wh-filter {
  margin-bottom: 12px;
}
.fg-balance-neg {
  color: var(--el-color-danger);
  font-weight: 600;
}
</style>
