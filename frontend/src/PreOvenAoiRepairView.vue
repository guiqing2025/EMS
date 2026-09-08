<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">炉前AOI维修改判</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            列出后焊产线已确认真不良的板；维修完成后可改判 PASS，后焊扫码即可通过。
          </p>
        </div>
        <el-button :loading="failLoading" @click="loadFails">刷新不良列表</el-button>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" @submit.prevent="onSearchFails">
          <el-form-item label="条码">
            <el-input
              v-model="filters.keyword"
              placeholder="扫描或输入条码筛选"
              clearable
              style="width: 240px"
              @keyup.enter="onSearchFails"
            />
          </el-form-item>
          <el-form-item label="采购单">
            <el-input v-model="filters.purchase_no" clearable style="width: 160px" @keyup.enter="onSearchFails" />
          </el-form-item>
          <el-form-item label="机型">
            <el-input v-model="filters.model_code" clearable style="width: 140px" @keyup.enter="onSearchFails" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="failLoading" @click="onSearchFails">查询</el-button>
            <el-button @click="onResetFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <div style="margin-bottom: 8px; font-size: 13px; color: var(--erp-text-muted)">
          待维修改判共 <strong style="color: var(--el-color-danger)">{{ failTotal }}</strong> 条
        </div>

        <el-table
          v-loading="failLoading"
          :data="failRows"
          border
          stripe
          size="small"
          max-height="calc(100vh - 360px)"
        >
          <el-table-column prop="barcode" label="条码" min-width="180" fixed show-overflow-tooltip />
          <el-table-column prop="result" label="结果" width="72" align="center">
            <template #default="{ row }">
              <el-tag type="danger" size="small">{{ row.result || 'FAIL' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="fail_reason" label="不良现象" min-width="200" show-overflow-tooltip />
          <el-table-column prop="purchase_no" label="采购单" width="140" show-overflow-tooltip />
          <el-table-column prop="model_code" label="机型" width="120" show-overflow-tooltip />
          <el-table-column prop="machine" label="机台" width="110" show-overflow-tooltip />
          <el-table-column label="测试时间" width="160">
            <template #default="{ row }">{{ formatTs(row.tested_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right" align="center">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openOverride(row)">改判 PASS</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top: 12px; display: flex; justify-content: flex-end">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="failTotal"
            :page-sizes="[50, 100, 200]"
            layout="total, sizes, prev, pager, next"
            background
            small
            @current-change="loadFails"
            @size-change="onPageSizeChange"
          />
        </div>

        <el-divider content-position="left">复判 / 改判记录</el-divider>
        <div style="display: flex; justify-content: flex-end; margin-bottom: 8px">
          <el-button size="small" :loading="histLoading" @click="loadHistory">刷新</el-button>
        </div>
        <el-table v-loading="histLoading" :data="histRows" border stripe size="small" max-height="280">
          <el-table-column prop="created_at" label="时间" width="160" />
          <el-table-column prop="barcode" label="条码" min-width="180" show-overflow-tooltip />
          <el-table-column prop="action" label="类型" width="88" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.action === 'qc_pass' ? 'success' : row.action === 'line_pass' ? 'warning' : 'danger'">
                {{ actionLabel(row.action) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="fail_reason" label="不良现象" min-width="160" show-overflow-tooltip />
          <el-table-column prop="reason" label="说明" min-width="140" show-overflow-tooltip />
          <el-table-column prop="operator" label="操作人" width="100" />
          <el-table-column prop="purchase_no" label="采购单" width="120" show-overflow-tooltip />
        </el-table>
      </div>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="step === 1 ? '填写改判信息' : '品质确认改判'"
      width="520px"
      destroy-on-close
      @closed="resetDialog"
    >
      <div v-if="pending" style="margin-bottom: 12px; font-size: 13px; line-height: 1.7">
        <div><strong>条码</strong> {{ pending.barcode }}</div>
        <div><strong>不良</strong> {{ pending.fail_reason || '—' }}</div>
        <div v-if="pending.purchase_no"><strong>采购单</strong> {{ pending.purchase_no }}</div>
        <div v-if="pending.model_code"><strong>机型</strong> {{ pending.model_code }}</div>
      </div>

      <template v-if="step === 1">
        <el-form label-width="88px" @submit.prevent="submitDraft">
          <el-form-item label="改判原因" required>
            <el-input
              v-model="reason"
              type="textarea"
              :rows="3"
              maxlength="256"
              show-word-limit
              placeholder="例如：缺件已补 / 虚焊已修"
            />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="remark" maxlength="512" show-word-limit placeholder="可选" />
          </el-form-item>
        </el-form>
      </template>

      <template v-else>
        <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px">
          <template #title>请品质人员输入确认密码完成改判</template>
        </el-alert>
        <el-form label-width="88px" @submit.prevent="confirmOverride">
          <el-form-item label="确认密码" required>
            <el-input
              v-model="confirmPassword"
              type="password"
              show-password
              placeholder="品质确认密码"
              autocomplete="off"
              @keyup.enter="confirmOverride"
            />
          </el-form-item>
          <el-form-item label="改判人">
            <el-input :model-value="confirmOperator || '输入密码后自动显示'" disabled />
          </el-form-item>
        </el-form>
      </template>

      <template #footer>
        <template v-if="step === 1">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="submitDraft">提交改判</el-button>
        </template>
        <template v-else>
          <el-button @click="step = 1">返回修改</el-button>
          <el-button type="primary" :loading="saving" @click="confirmOverride">确认改判</el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchPreOvenAoiFails,
  fetchPreOvenAoiQcRecords,
  overridePreOvenAoiPass,
  type PreOvenAoiFailRow,
} from '@/api/quality'
import { ApiError } from '@/api/http'

const QC_PASSWORD_NAMES: Record<string, string> = {
  dxpz888: '胡椒',
}

const filters = reactive({
  keyword: '',
  purchase_no: '',
  model_code: '',
})
const page = ref(1)
const pageSize = ref(50)
const failLoading = ref(false)
const failRows = ref<PreOvenAoiFailRow[]>([])
const failTotal = ref(0)
const histLoading = ref(false)
const histRows = ref<
  Array<{
    id: number
    barcode: string
    action: string
    fail_reason?: string
    reason?: string
    operator: string
    purchase_no?: string | null
    created_at?: string | null
  }>
>([])
const dialogVisible = ref(false)
const step = ref<1 | 2>(1)
const pending = ref<PreOvenAoiFailRow | null>(null)
const reason = ref('')
const remark = ref('')
const confirmPassword = ref('')
const saving = ref(false)

const confirmOperator = computed(() => QC_PASSWORD_NAMES[confirmPassword.value.trim()] || '')

function formatTs(v?: string | null) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

function actionLabel(action: string) {
  if (action === 'line_pass') return '产线PASS'
  if (action === 'line_fail') return '产线FALL'
  if (action === 'qc_pass') return '品质PASS'
  return action
}

function onSearchFails() {
  page.value = 1
  loadFails()
}

function onResetFilters() {
  filters.keyword = ''
  filters.purchase_no = ''
  filters.model_code = ''
  page.value = 1
  loadFails()
}

function onPageSizeChange() {
  page.value = 1
  loadFails()
}

async function loadFails() {
  failLoading.value = true
  try {
    const data = await fetchPreOvenAoiFails({
      keyword: filters.keyword.trim() || undefined,
      purchase_no: filters.purchase_no.trim() || undefined,
      model_code: filters.model_code.trim() || undefined,
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value,
    })
    failRows.value = data.items
    failTotal.value = data.total
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : '加载失败'
    ElMessage.error(msg)
  } finally {
    failLoading.value = false
  }
}

async function loadHistory() {
  histLoading.value = true
  try {
    const pageData = await fetchPreOvenAoiQcRecords({ limit: 80 })
    histRows.value = pageData.items
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : '加载失败'
    ElMessage.error(msg)
  } finally {
    histLoading.value = false
  }
}

function resetDialog() {
  step.value = 1
  pending.value = null
  reason.value = ''
  remark.value = ''
  confirmPassword.value = ''
  saving.value = false
}

function openOverride(row: PreOvenAoiFailRow) {
  pending.value = row
  reason.value = ''
  remark.value = ''
  confirmPassword.value = ''
  step.value = 1
  dialogVisible.value = true
}

function submitDraft() {
  if (!pending.value) return
  if (reason.value.trim().length < 2) {
    ElMessage.warning('请填写改判原因')
    return
  }
  confirmPassword.value = ''
  step.value = 2
}

async function confirmOverride() {
  if (!pending.value) return
  const code = pending.value.barcode
  const why = reason.value.trim()
  const pwd = confirmPassword.value.trim()
  if (why.length < 2) {
    ElMessage.warning('请填写改判原因')
    step.value = 1
    return
  }
  if (!pwd) {
    ElMessage.warning('请输入品质确认密码')
    return
  }
  if (!confirmOperator.value) {
    ElMessage.error('确认密码错误')
    return
  }
  saving.value = true
  try {
    const out = await overridePreOvenAoiPass({
      barcode: code,
      reason: why,
      remark: remark.value.trim(),
      confirm_password: pwd,
    })
    ElMessage.success(
      `已由 ${out.operator} 确认改判 PASS${out.gate_ok ? '，后焊卡控可通过' : ''}`,
    )
    dialogVisible.value = false
    await Promise.all([loadFails(), loadHistory()])
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : '改判失败'
    ElMessage.error(msg)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadFails()
  void loadHistory()
})
</script>
