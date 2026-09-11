<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">应付统计 / 付款申请</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            采购/委外/其他费用 → 勾选申请 → 审批 → 付款过账扣账户
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button @click="load">刷新</el-button>
          <el-button @click="oeOpen = true">其他费用</el-button>
          <el-button type="primary" :disabled="!selected.length" @click="onRequest">生成付款申请</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table :data="summary" border size="small" style="margin-bottom: 16px" max-height="160">
          <el-table-column prop="supplier_name" label="供应商汇总" />
          <el-table-column prop="open_amount" label="未付" width="120" />
          <el-table-column prop="count" label="笔数" width="80" />
        </el-table>
        <el-table
          v-loading="loading"
          :data="items"
          border
          stripe
          size="small"
          @selection-change="(rows: ApItem[]) => (selected = rows)"
        >
          <el-table-column type="selection" width="42" :selectable="(r: ApItem) => r.open_amount > 0" />
          <el-table-column prop="source_no" label="来源单号" width="140" />
          <el-table-column prop="source_type" label="类型" width="130" />
          <el-table-column prop="supplier_name" label="供应商" width="140" />
          <el-table-column prop="amount" label="金额" width="100" />
          <el-table-column prop="open_amount" label="未付" width="100" />
          <el-table-column prop="status" label="状态" width="90" />
        </el-table>

        <h3 style="font-size: 14px; margin: 20px 0 8px">付款申请</h3>
        <el-table :data="requests" border size="small">
          <el-table-column prop="request_no" label="申请单号" width="140" />
          <el-table-column prop="supplier_name" label="供应商" width="140" />
          <el-table-column prop="amount" label="金额" width="100" />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'submitted'" link type="success" @click="onApprove(row, true)">审批通过</el-button>
              <el-button v-if="row.status === 'submitted'" link type="danger" @click="onApprove(row, false)">驳回</el-button>
              <el-button v-if="row.status === 'approved'" link type="primary" @click="onPay(row)">生成并过账付款</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="oeOpen" title="其他费用支出" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="供应商"><el-input v-model="oe.supplier_name" /></el-form-item>
        <el-form-item label="金额"><el-input-number v-model="oe.amount" :min="0.01" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="oe.remark" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="oeOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onOther">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  approvePaymentRequest,
  createOtherExpense,
  createPaymentFromRequest,
  createPaymentRequest,
  fetchAccounts,
  fetchAp,
  fetchPaymentRequests,
  postPayment,
  type ApItem,
  type PaymentRequest,
} from '@/api/finance'

const loading = ref(false)
const saving = ref(false)
const items = ref<ApItem[]>([])
const summary = ref<Array<{ supplier_name: string; open_amount: number; count: number }>>([])
const selected = ref<ApItem[]>([])
const requests = ref<PaymentRequest[]>([])
const bankId = ref(0)
const oeOpen = ref(false)
const oe = reactive({ supplier_name: '', amount: 100, remark: '' })

async function load() {
  loading.value = true
  try {
    const [ap, pr, acc] = await Promise.all([fetchAp(), fetchPaymentRequests(), fetchAccounts()])
    items.value = ap.items || []
    summary.value = ap.summary || []
    requests.value = pr.items || []
    bankId.value = acc.items?.find((a) => a.code === 'BANK-MAIN')?.id || acc.items?.[0]?.id || 0
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onRequest() {
  try {
    const r = await createPaymentRequest(selected.value.map((x) => x.id))
    ElMessage.success(`已提交申请 ${r.request_no}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onApprove(row: PaymentRequest, approve: boolean) {
  try {
    await approvePaymentRequest(row.id, approve)
    ElMessage.success(approve ? '已审批' : '已驳回')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onPay(row: PaymentRequest) {
  try {
    const pay = await createPaymentFromRequest(row.id, bankId.value)
    await postPayment(pay.id)
    ElMessage.success(`付款已过账 ${pay.payment_no}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

async function onOther() {
  saving.value = true
  try {
    await createOtherExpense({ ...oe })
    ElMessage.success('已记其他费用应付')
    oeOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
