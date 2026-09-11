<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">总账 / 月末</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            开账 → 业务自动凭证审核过账 → 成本/折旧 → 损益结转 → 关账
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="onBoot">开账/种子</el-button>
          <el-button @click="onCost">成本结转</el-button>
          <el-button @click="onAsset">登记固资</el-button>
          <el-button @click="onFx">调汇</el-button>
          <el-button type="warning" @click="onPnl">损益结转</el-button>
          <el-button type="danger" @click="onClose">月末关账</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table :data="periods" border size="small" style="margin-bottom: 12px" max-height="120">
          <el-table-column prop="period" label="期间" width="100" />
          <el-table-column prop="status" label="状态" width="100" />
        </el-table>
        <el-table :data="accounts" border size="small" style="margin-bottom: 16px" max-height="220">
          <el-table-column prop="code" label="科目" width="90" />
          <el-table-column prop="name" label="名称" width="140" />
          <el-table-column prop="category" label="类别" width="90" />
          <el-table-column prop="balance" label="余额" width="120" />
        </el-table>
        <el-table v-loading="loading" :data="vouchers" border stripe size="small" max-height="360">
          <el-table-column prop="voucher_no" label="凭证号" width="140" />
          <el-table-column prop="period" label="期间" width="80" />
          <el-table-column prop="source_type" label="来源" width="120" />
          <el-table-column prop="summary" label="摘要" min-width="160" />
          <el-table-column prop="total_debit" label="借方" width="100" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="primary" @click="onReview(row)">审核</el-button>
              <el-button v-if="row.status === 'reviewed'" link type="success" @click="onPost(row)">过账</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  closePeriod,
  closePnl,
  createCostAccrual,
  createFixedAsset,
  depreciateAsset,
  fetchAssets,
  fetchGlAccounts,
  fetchGlPeriods,
  fetchGlVouchers,
  fxAdjust,
  glBootstrap,
  postGlVoucher,
  reviewGlVoucher,
  type GlAccount,
  type GlPeriod,
  type GlVoucher,
} from '@/api/gl'

const loading = ref(false)
const accounts = ref<GlAccount[]>([])
const periods = ref<GlPeriod[]>([])
const vouchers = ref<GlVoucher[]>([])

async function load() {
  loading.value = true
  try {
    const [a, p, v] = await Promise.all([fetchGlAccounts(), fetchGlPeriods(), fetchGlVouchers()])
    accounts.value = a.items || []
    periods.value = p.items || []
    vouchers.value = v.items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onBoot() {
  try {
    const r = await glBootstrap()
    ElMessage.success(`已开账期间 ${r.period}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onReview(row: GlVoucher) {
  try {
    await reviewGlVoucher(row.id)
    ElMessage.success('已审核')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onPost(row: GlVoucher) {
  try {
    await postGlVoucher(row.id)
    ElMessage.success('已过账')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onCost() {
  try {
    const { value } = await ElMessageBox.prompt('生产成本结转金额', '成本结转', { inputValue: '100' })
    const v = await createCostAccrual(Number(value) || 0)
    ElMessage.success(`已建凭证 ${v.voucher_no}`)
    await load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onAsset() {
  try {
    const asset = (await createFixedAsset({ name: '演示设备', original_value: 12000, months: 36 })) as {
      id: number
      asset_no: string
    }
    await depreciateAsset(asset.id)
    ElMessage.success(`固资 ${asset.asset_no} + 折旧凭证`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onFx() {
  try {
    const r = await fxAdjust()
    ElMessage.info(r.skipped ? r.reason : '调汇完成')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onPnl() {
  try {
    const v = await closePnl()
    ElMessage.success(`损益结转 ${v.voucher_no}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onClose() {
  try {
    await ElMessageBox.confirm('确认关账？未过账凭证将阻止关账。', '月末关账')
    const p = await closePeriod()
    ElMessage.success(`期间 ${p.period} 已关账`)
    await load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(async () => {
  try {
    await glBootstrap()
  } catch {
    /* ignore */
  }
  await load()
  void fetchAssets
})
</script>
