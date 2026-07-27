<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">员工档案</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            共享盘花名册可同步基础信息与「宿舍人员明细」；入职评审、离职原因等由系统维护。
            <template v-if="meta">
              · 在职 {{ meta.active_count }} / 共 {{ meta.total_count }}
              <template v-if="meta.dorm_count != null"> · 住宿 {{ meta.dorm_count }}</template>
              <template v-if="meta.last_synced_at">
                · 上次同步 {{ formatTime(meta.last_synced_at) }}
              </template>
            </template>
          </p>
        </div>
        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">
          <el-tag :type="meta?.accessible ? 'success' : 'danger'" size="small">
            {{ meta?.accessible ? '共享盘已连接' : '共享盘未挂载' }}
          </el-tag>
          <el-button :loading="syncing" @click="onSync">从共享盘同步</el-button>
          <el-button type="primary" @click="openCreate">新增入职</el-button>
        </div>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" @submit.prevent="load">
          <el-form-item>
            <el-input
              v-model="filters.keyword"
              placeholder="工号 / 姓名 / 电话 / 宿舍"
              clearable
              style="width: 220px"
              @clear="load"
            />
          </el-form-item>
          <el-form-item label="部门">
            <el-select v-model="filters.department" clearable style="width: 160px" @change="load">
              <el-option v-for="d in departments" :key="d" :label="d" :value="d" />
            </el-select>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="filters.active" style="width: 110px" @change="load">
              <el-option label="全部" value="all" />
              <el-option label="在职" value="active" />
              <el-option label="离职" value="inactive" />
            </el-select>
          </el-form-item>
          <el-form-item label="宿舍">
            <el-select v-model="filters.dorm" style="width: 110px" @change="load">
              <el-option label="全部" value="all" />
              <el-option label="住宿" value="yes" />
              <el-option label="不住宿" value="no" />
            </el-select>
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
          <el-table-column prop="employee_no" label="工号" width="90" fixed />
          <el-table-column prop="name" label="姓名" width="90" fixed />
          <el-table-column prop="gender" label="性别" width="56" align="center" />
          <el-table-column prop="department" label="部门" width="110" show-overflow-tooltip />
          <el-table-column prop="position" label="职位" width="90" show-overflow-tooltip />
          <el-table-column prop="phone" label="电话" width="118" />
          <el-table-column prop="hire_date" label="入职" width="104" />
          <el-table-column label="评审" width="64" align="center">
            <template #default="{ row }">{{ row.hire_grade || '—' }}</template>
          </el-table-column>
          <el-table-column label="宿舍" width="100" show-overflow-tooltip>
            <template #default="{ row }">
              <template v-if="row.lives_in_dorm">{{ row.dorm_room || '住宿' }}</template>
              <template v-else>—</template>
            </template>
          </el-table-column>
          <el-table-column prop="leave_date" label="离职日" width="104" />
          <el-table-column prop="leave_reason" label="离职原因" min-width="120" show-overflow-tooltip />
          <el-table-column label="状态" width="70" align="center" fixed="right">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '在职' : '离职' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="168" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button
                v-if="row.is_active"
                link
                type="warning"
                size="small"
                @click="openResign(row)"
              >
                离职
              </el-button>
              <el-button v-else link type="success" size="small" @click="onRehire(row)">复职</el-button>
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

    <el-drawer v-model="formOpen" :title="editingId ? '编辑员工' : '新增入职'" size="520px" destroy-on-close>
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="工号" required>
          <el-input v-model="form.employee_no" :disabled="!!editingId" placeholder="如 DX001" />
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="form.gender" clearable style="width: 100%">
            <el-option label="男" value="男" />
            <el-option label="女" value="女" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select
            v-model="form.department"
            filterable
            allow-create
            default-first-option
            clearable
            style="width: 100%"
          >
            <el-option v-for="d in departments" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="职位">
          <el-input v-model="form.position" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="身份证">
          <el-input v-model="form.id_card" />
        </el-form-item>
        <el-form-item label="入职日期">
          <el-date-picker
            v-model="form.hire_date"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="入职评审">
          <el-select v-model="form.hire_grade" clearable style="width: 100%" placeholder="A / B / C / D">
            <el-option v-for="g in hireGrades" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="学历">
          <el-input v-model="form.education" />
        </el-form-item>
        <el-form-item label="住址">
          <el-input v-model="form.address" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="住宿舍">
          <el-switch v-model="form.lives_in_dorm" />
        </el-form-item>
        <el-form-item v-if="form.lives_in_dorm" label="宿舍号">
          <el-input v-model="form.dorm_room" placeholder="如 3栋-201" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-drawer>

    <el-dialog v-model="resignOpen" title="办理离职" width="460px" destroy-on-close>
      <p style="margin: 0 0 12px; color: var(--erp-text-muted)">
        {{ resignRow?.name }}（{{ resignRow?.employee_no }}）
      </p>
      <el-form label-width="88px">
        <el-form-item label="离职日期" required>
          <el-date-picker
            v-model="resignForm.leave_date"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="离职原因" required>
          <el-select
            v-model="resignForm.leave_reason"
            filterable
            allow-create
            default-first-option
            style="width: 100%"
            placeholder="选择或输入原因"
          >
            <el-option v-for="r in leaveReasonPresets" :key="r" :label="r" :value="r" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resignOpen = false">取消</el-button>
        <el-button type="warning" :loading="saving" @click="onResign">确认离职</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createHrEmployee,
  fetchHrEmployees,
  fetchHrMeta,
  rehireHrEmployee,
  resignHrEmployee,
  syncHrEmployees,
  updateHrEmployee,
  type HrEmployee,
  type HrMeta,
} from '@/api/hr'
import { ApiError } from '@/api/http'

const loading = ref(false)
const syncing = ref(false)
const saving = ref(false)
const rows = ref<HrEmployee[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(100)
const meta = ref<HrMeta | null>(null)
const departments = ref<string[]>([])
const hireGrades = ref(['A', 'B', 'C', 'D'])
const leaveReasonPresets = ref([
  '个人发展',
  '家庭原因',
  '薪资待遇',
  '工作环境',
  '合同到期',
  '试用不合格',
  '违纪辞退',
  '其他',
])

const filters = reactive({
  keyword: '',
  department: '',
  active: 'active' as 'all' | 'active' | 'inactive',
  dorm: 'all' as 'all' | 'yes' | 'no',
})

const formOpen = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  employee_no: '',
  name: '',
  gender: '' as string,
  department: '' as string,
  position: '',
  phone: '',
  id_card: '',
  hire_date: '' as string,
  hire_grade: '' as string,
  education: '',
  address: '',
  lives_in_dorm: false,
  dorm_room: '',
  remark: '',
})

const resignOpen = ref(false)
const resignRow = ref<HrEmployee | null>(null)
const resignForm = reactive({
  leave_date: '',
  leave_reason: '',
})

function formatTime(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function today() {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function resetForm() {
  form.employee_no = ''
  form.name = ''
  form.gender = ''
  form.department = ''
  form.position = ''
  form.phone = ''
  form.id_card = ''
  form.hire_date = today()
  form.hire_grade = ''
  form.education = ''
  form.address = ''
  form.lives_in_dorm = false
  form.dorm_room = ''
  form.remark = ''
}

async function loadMeta() {
  try {
    meta.value = await fetchHrMeta()
    departments.value = meta.value.departments || []
    if (meta.value.hire_grades?.length) hireGrades.value = meta.value.hire_grades
    if (meta.value.leave_reason_presets?.length) {
      leaveReasonPresets.value = meta.value.leave_reason_presets
    }
  } catch {
    meta.value = null
  }
}

async function load() {
  loading.value = true
  try {
    const data = await fetchHrEmployees({
      keyword: filters.keyword,
      department: filters.department,
      active: filters.active,
      dorm: filters.dorm,
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

async function onSync() {
  syncing.value = true
  try {
    const r = await syncHrEmployees()
    const dormPart =
      r.dorm_total != null
        ? `；住宿 ${r.dorm_matched}/${r.dorm_total} 人` +
          (r.dorm_unmatched?.length ? `（未匹配 ${r.dorm_unmatched.length}）` : '')
        : ''
    ElMessage.success(
      `同步完成：解析 ${r.parsed}，新增 ${r.created}，更新 ${r.updated}，离职标记 ${r.inactivated}${dormPart}`,
    )
    await loadMeta()
    page.value = 1
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '同步失败')
  } finally {
    syncing.value = false
  }
}

function openCreate() {
  editingId.value = null
  resetForm()
  formOpen.value = true
}

function openEdit(row: HrEmployee) {
  editingId.value = row.id
  form.employee_no = row.employee_no
  form.name = row.name
  form.gender = row.gender || ''
  form.department = row.department || ''
  form.position = row.position || ''
  form.phone = row.phone || ''
  form.id_card = row.id_card || ''
  form.hire_date = row.hire_date || ''
  form.hire_grade = row.hire_grade || ''
  form.education = row.education || ''
  form.address = row.address || ''
  form.lives_in_dorm = !!row.lives_in_dorm
  form.dorm_room = row.dorm_room || ''
  form.remark = row.remark || ''
  formOpen.value = true
}

async function onSave() {
  if (!form.employee_no.trim() || !form.name.trim()) {
    ElMessage.warning('请填写工号和姓名')
    return
  }
  saving.value = true
  try {
    const payload = {
      employee_no: form.employee_no.trim(),
      name: form.name.trim(),
      gender: form.gender || null,
      department: form.department || null,
      position: form.position || null,
      phone: form.phone || null,
      id_card: form.id_card || null,
      hire_date: form.hire_date || null,
      hire_grade: form.hire_grade || null,
      education: form.education || null,
      address: form.address || null,
      lives_in_dorm: form.lives_in_dorm,
      dorm_room: form.lives_in_dorm ? form.dorm_room || null : null,
      remark: form.remark || null,
    }
    if (editingId.value) {
      await updateHrEmployee(editingId.value, payload)
      ElMessage.success('已保存')
    } else {
      await createHrEmployee(payload)
      ElMessage.success('已办理入职')
    }
    formOpen.value = false
    await loadMeta()
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

function openResign(row: HrEmployee) {
  resignRow.value = row
  resignForm.leave_date = today()
  resignForm.leave_reason = ''
  resignOpen.value = true
}

async function onResign() {
  if (!resignRow.value) return
  if (!resignForm.leave_reason.trim()) {
    ElMessage.warning('请填写离职原因')
    return
  }
  saving.value = true
  try {
    await resignHrEmployee(resignRow.value.id, {
      leave_date: resignForm.leave_date || today(),
      leave_reason: resignForm.leave_reason.trim(),
    })
    ElMessage.success('已办理离职')
    resignOpen.value = false
    await loadMeta()
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '离职失败')
  } finally {
    saving.value = false
  }
}

async function onRehire(row: HrEmployee) {
  try {
    await ElMessageBox.confirm(`确认将「${row.name}」复职为在职？`, '复职确认', {
      type: 'warning',
      confirmButtonText: '复职',
    })
  } catch {
    return
  }
  try {
    await rehireHrEmployee(row.id, { hire_date: today(), clear_leave: true })
    ElMessage.success('已复职')
    await loadMeta()
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '复职失败')
  }
}

onMounted(async () => {
  await loadMeta()
  await load()
})
</script>
