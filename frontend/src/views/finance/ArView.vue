<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">应收统计 / 收款</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            发货/其他收入 → 勾选收款 → 过账入账户并核销应收
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button @click="load">刷新</el-button>
          <el-button @click="oiOpen = true">其他收入</el-button>
          <el-button type="primary" :disabled="!selected.length" @click="onReceipt">生成并过账收款</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table :data="summary" border size="small" style="margin-bottom: 16px" max-height="160">
          <el-table-column prop="customer_name" label="客户汇总" />
          <el-table-column prop="open_amount" label="未收" width="120" />
          <el-table-column prop="count" label="笔数" width="80" />
        </el-table>
        <el-table
          v-loading="loading"
          :data="items"
          border
          stripe
          size="small"
          @selection-change="(rows: ArItem[]) => (selected = rows)"
        >
          <el-table-column type="selection" width="42" :selectable="(r: ArItem) => r.open_amount > 0" />
          <el-table-column prop="source_no" label="来源单号" width="140" />
          <el-table-column prop="source_type" label="类型" width="130" />
          <el-table-column prop="customer_name" label="客户" width="140" />
          <el-table-column prop="amount" label="金额" width="100" />
          <el-table-column prop="open_amount" label="未收" width="100" />
          <el-table-column prop="status" label="状态" width="90" />
        </el-table>

        <h3 style="font-size: 14px; margin: 20px 0 8px">收款单</h3>
        <el-table :data="receipts" border size="small">
          <el-table-column prop="receipt_no" label="收款单号" width="140" />
          <el-table-column prop="customer_name" label="客户" width="140" />
          <el-table-column prop="amount" label="金额" width="100" />
          <el-table-column prop="status" label="状态" width="90" />
        </el-table>
      </div>
    </div>

    <el-dialog v-model="oiOpen" title="其他费用收入" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="客户"><el-input v-model="oi.customer_name" /></el-form-item>
        <el-form-item label="金额"><el-input-number v-model="oi.amount" :min="0.01" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="oi.remark" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="oiOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onOther">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createOtherIncome,
  createReceipt,
  fetchAccounts,
  fetchAr,
  fetchReceipts,
  postReceipt,
  type ArItem,
  type ReceiptDoc,
} from '@/api/finance'

const loading = ref(false)
const saving = ref(false)
const items = ref<ArItem[]>([])
const summary = ref<Array<{ customer_name: string; open_amount: number; count: number }>>([])
const selected = ref<ArItem[]>([])
const receipts = ref<ReceiptDoc[]>([])
const bankId = ref(0)
const oiOpen = ref(false)
const oi = reactive({ customer_name: '', amount: 100, remark: '' })

async function load() {
  loading.value = true
  try {
    const [ar, rc, acc] = await Promise.all([fetchAr(), fetchReceipts(), fetchAccounts()])
    items.value = ar.items || []
    summary.value = ar.summary || []
    receipts.value = rc.items || []
    bankId.value = acc.items?.find((a) => a.code === 'BANK-MAIN')?.id || acc.items?.[0]?.id || 0
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onReceipt() {
  try {
    const r = await createReceipt({
      account_id: bankId.value,
      ar_ids: selected.value.map((x) => x.id),
    })
    await postReceipt(r.id)
    ElMessage.success(`收款已过账 ${r.receipt_no}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onOther() {
  saving.value = true
  try {
    await createOtherIncome({ ...oi })
    ElMessage.success('已记其他收入应收')
    oiOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
