<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">考勤管理 · 请假登记</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            登记员工请假类型、日期与原因；可按姓名/工号筛选。打卡明细后续可对接考勤机。
          </p>
        </div>
        <el-button type="primary" @click="openCreate">登记请假</el-button>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" @submit.prevent="load">
          <el-form-item>
            <el-input
              v-model="filters.keyword"
              placeholder="工号 / 姓名 / 原因"
              clearable
              style="width: 200px"
              @clear="load"
            />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="filters.leave_type" clearable style="width: 120px" @change="load">
              <el-option v-for="t in leaveTypes" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="filters.status" style="width: 110px" @change="load">
              <el-option label="全部" value="all" />
              <el-option label="有效" value="approved" />
              <el-option label="已取消" value="cancelled" />
            </el-select>
          </el-form-item>
          <el-form-item label="区间">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始"
              end-placeholder="结束"
              style="width: 240px"
              @change="load"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="load">查询</el-button>
          </el-form-item>
        </el-form>

        <el-table
          v-loading="loading"
          :data="rows"
          border
          stripe
          size="small"
          max-height="calc(100vh - 300px)"
        >
          <el-table-column prop="employee_no" label="工号" width="90" />
          <el-table-column prop="employee_name" label="姓名" width="90" />
          <el-table-column prop="leave_type" label="类型" width="90" />
          <el-table-column prop="start_date" label="开始" width="110" />
          <el-table-column prop="end_date" label="结束" width="110" />
          <el-table-column label="天数" width="70" align="right">
            <template #default="{ row }">{{ Number(row.days).toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="reason" label="请假原因" min-width="160" show-overflow-tooltip />
          <el-table-column prop="created_by" label="登记人" width="100" />
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'approved' ? 'success' : 'info'" size="small">
                {{ row.status === 'approved' ? '有效' : '已取消' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'approved'"
                link
                type="warning"
                size="small"
                @click="onCancel(row)"
              >
                取消
              </el-button>
              <el-button link type="danger" size="small" @click="onDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top: 12px; display: flex; justify-content: flex-end">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            layout="total, prev, pager, next"
            @current-change="load"
            @size-change="load"
          />
        </div>
      </div>
    </div>

    <el-dialog v-model="formOpen" title="登记请假" width="520px" destroy-on-close>
      <el-form label-width="96px">
        <el-form-item label="员工" required>
          <el-select
            v-model="form.employee_id"
            filterable
            remote
            clearable
            :remote-method="searchEmployees"
            :loading="empLoading"
            placeholder="输入工号或姓名搜索"
            style="width: 100%"
          >
            <el-option
              v-for="e in employeeOptions"
              :key="e.id"
              :label="`${e.name}（${e.employee_no}）${e.department || ''}`"
              :value="e.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="请假类型" required>
          <el-select v-model="form.leave_type" style="width: 100%">
            <el-option v-for="t in leaveTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="请假日期" required>
          <el-date-picker
            v-model="leaveDates"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="结束"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="请假原因" required>
          <el-input v-model="form.reason" type="textarea" :rows="3" placeholder="请说明请假原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cancelHrLeave,
  createHrLeave,
  deleteHrLeave,
  fetchHrEmployees,
  fetchHrLeaves,
  fetchHrMeta,
  type HrEmployee,
  type HrLeaveRecord,
} from '@/api/hr'
import { ApiError } from '@/api/http'

const loading = ref(false)
const saving = ref(false)
const empLoading = ref(false)
const rows = ref<HrLeaveRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const leaveTypes = ref(['事假', '病假', '年假', '婚假', '产假', '丧假', '调休', '其他'])
const employeeOptions = ref<HrEmployee[]>([])
const dateRange = ref<[string, string] | null>(null)
const leaveDates = ref<[string, string] | null>(null)

const filters = reactive({
  keyword: '',
  leave_type: '',
  status: 'approved' as 'all' | 'approved' | 'cancelled',
})

const formOpen = ref(false)
const form = reactive({
  employee_id: null as number | null,
  leave_type: '事假',
  reason: '',
})

watch(leaveDates, (v) => {
  if (!v) return
})

async function loadMeta() {
  try {
    const meta = await fetchHrMeta()
    if (meta.leave_types?.length) leaveTypes.value = meta.leave_types
  } catch {
    /* ignore */
  }
}

async function searchEmployees(kw: string) {
  empLoading.value = true
  try {
    const data = await fetchHrEmployees({
      keyword: kw,
      active: 'active',
      page: 1,
      page_size: 30,
    })
    employeeOptions.value = data.items
  } catch {
    employeeOptions.value = []
  } finally {
    empLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const data = await fetchHrLeaves({
      keyword: filters.keyword,
      leave_type: filters.leave_type,
      status: filters.status,
      date_from: dateRange.value?.[0] || '',
      date_to: dateRange.value?.[1] || '',
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.employee_id = null
  form.leave_type = '事假'
  form.reason = ''
  leaveDates.value = null
  formOpen.value = true
  void searchEmployees('')
}

async function onSave() {
  if (!form.employee_id) {
    ElMessage.warning('请选择员工')
    return
  }
  if (!leaveDates.value?.[0]) {
    ElMessage.warning('请选择请假日期')
    return
  }
  if (!form.reason.trim()) {
    ElMessage.warning('请填写请假原因')
    return
  }
  saving.value = true
  try {
    await createHrLeave({
      employee_id: form.employee_id,
      leave_type: form.leave_type,
      start_date: leaveDates.value[0],
      end_date: leaveDates.value[1] || leaveDates.value[0],
      reason: form.reason.trim(),
    })
    ElMessage.success('已登记请假')
    formOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onCancel(row: HrLeaveRecord) {
  try {
    await ElMessageBox.confirm(`取消 ${row.employee_name} 的请假记录？`, '确认', { type: 'warning' })
    await cancelHrLeave(row.id)
    ElMessage.success('已取消')
    await load()
  } catch (e) {
    if (e instanceof ApiError) ElMessage.error(e.message)
  }
}

async function onDelete(row: HrLeaveRecord) {
  try {
    await ElMessageBox.confirm(`删除 ${row.employee_name} 的请假记录？不可恢复。`, '确认删除', {
      type: 'warning',
    })
    await deleteHrLeave(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e instanceof ApiError) ElMessage.error(e.message)
  }
}

onMounted(async () => {
  await loadMeta()
  await load()
})
</script>
