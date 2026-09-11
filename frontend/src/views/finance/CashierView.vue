<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">出纳</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            账户余额、手工录入、报销、账户调拨；收付款流水自动入账
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button @click="load">刷新</el-button>
          <el-button @click="manualOpen = true">手工录入</el-button>
          <el-button @click="reimbOpen = true">报销</el-button>
          <el-button type="primary" @click="xferOpen = true">账户调拨</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table :data="accounts" border size="small" style="margin-bottom: 16px">
          <el-table-column prop="code" label="账户" width="120" />
          <el-table-column prop="name" label="名称" width="140" />
          <el-table-column prop="kind" label="类型" width="80" />
          <el-table-column prop="balance" label="余额" width="120" />
        </el-table>
        <el-table v-loading="loading" :data="ledgers" border stripe size="small" max-height="420">
          <el-table-column prop="created_at" label="时间" width="170" />
          <el-table-column prop="account_code" label="账户" width="100" />
          <el-table-column prop="movement_type" label="类型" width="120" />
          <el-table-column prop="amount" label="金额(+入/-出)" width="120" />
          <el-table-column prop="balance_after" label="余额后" width="100" />
          <el-table-column prop="ref_no" label="关联单" width="140" />
          <el-table-column prop="remark" label="备注" min-width="160" />
        </el-table>
      </div>
    </div>

    <el-dialog v-model="manualOpen" title="手工录入" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="账户">
          <el-select v-model="manual.account_id" style="width: 100%">
            <el-option v-for="a in accounts" :key="a.id" :label="`${a.code} ${a.name}`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="金额"><el-input-number v-model="manual.amount" /><span style="margin-left:8px;font-size:12px;color:#888">正入负出</span></el-form-item>
        <el-form-item label="备注"><el-input v-model="manual.remark" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onManual">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reimbOpen" title="报销" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="账户">
          <el-select v-model="reimb.account_id" style="width: 100%">
            <el-option v-for="a in accounts" :key="a.id" :label="`${a.code} ${a.name}`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="金额"><el-input-number v-model="reimb.amount" :min="0.01" /></el-form-item>
        <el-form-item label="领款人"><el-input v-model="reimb.payee" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reimbOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onReimb">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="xferOpen" title="账户调拨" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="从">
          <el-select v-model="xfer.from_account_id" style="width: 100%">
            <el-option v-for="a in accounts" :key="a.id" :label="`${a.code} ${a.name}`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="到">
          <el-select v-model="xfer.to_account_id" style="width: 100%">
            <el-option v-for="a in accounts" :key="a.id" :label="`${a.code} ${a.name}`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="金额"><el-input-number v-model="xfer.amount" :min="0.01" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="xferOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onXfer">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  cashierManual,
  cashierReimburse,
  cashierTransfer,
  fetchAccounts,
  fetchLedgers,
  type CashAccount,
} from '@/api/finance'

const loading = ref(false)
const saving = ref(false)
const accounts = ref<CashAccount[]>([])
const ledgers = ref<Array<Record<string, unknown>>>([])
const manualOpen = ref(false)
const reimbOpen = ref(false)
const xferOpen = ref(false)
const manual = reactive({ account_id: 0, amount: 0, remark: '' })
const reimb = reactive({ account_id: 0, amount: 100, payee: '' })
const xfer = reactive({ from_account_id: 0, to_account_id: 0, amount: 100 })

async function load() {
  loading.value = true
  try {
    accounts.value = (await fetchAccounts()).items || []
    ledgers.value = (await fetchLedgers()).items || []
    if (accounts.value.length) {
      manual.account_id = accounts.value[0].id
      reimb.account_id = accounts.value[0].id
      xfer.from_account_id = accounts.value.find((a) => a.code === 'BANK-MAIN')?.id || accounts.value[0].id
      xfer.to_account_id = accounts.value.find((a) => a.code === 'CASH')?.id || accounts.value[0].id
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onManual() {
  saving.value = true
  try {
    await cashierManual({ ...manual })
    ElMessage.success('已入账')
    manualOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onReimb() {
  saving.value = true
  try {
    await cashierReimburse({ ...reimb })
    ElMessage.success('报销已出账')
    reimbOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onXfer() {
  saving.value = true
  try {
    await cashierTransfer({ ...xfer })
    ElMessage.success('调拨完成')
    xferOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
