<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">PMC 排产</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            维护 SMT / DIP 产线排产顺序、交期与日计划；可刷新备料齐套状态
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button @click="load">刷新</el-button>
          <el-button :loading="refreshing" @click="onRefreshKit">刷新备料状态</el-button>
          <el-button type="primary" @click="openEdit()">新建排产</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-tabs v-model="lineType" @tab-change="load">
          <el-tab-pane label="SMT" name="smt" />
          <el-tab-pane label="DIP" name="dip" />
        </el-tabs>

        <el-table v-loading="loading" :data="rows" border stripe size="small" max-height="calc(100vh - 300px)">
          <el-table-column prop="sort_order" label="序" width="56" />
          <el-table-column prop="line_name" label="线别" width="90" />
          <el-table-column prop="purchase_no" label="订单/PO" width="130" show-overflow-tooltip />
          <el-table-column prop="model_code" label="机型" width="120" show-overflow-tooltip />
          <el-table-column prop="model_name" label="品名" min-width="120" show-overflow-tooltip />
          <el-table-column prop="order_qty" label="数量" width="80" />
          <el-table-column prop="due_date" label="交期" width="110" />
          <el-table-column prop="daily_plan" label="日计划" width="120" show-overflow-tooltip />
          <el-table-column label="备料" width="90">
            <template #default="{ row }">
              <el-tag :type="matTag(row.material_status)" size="small">
                {{ matLabel(row.material_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="排产状态" width="90">
            <template #default="{ row }">
              {{ schLabel(row.schedule_status) }}
            </template>
          </el-table-column>
          <el-table-column prop="remark" label="备注" min-width="100" show-overflow-tooltip />
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" @click="onRemove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="open" :title="form.id ? '编辑排产' : '新建排产'" width="560px" destroy-on-close>
      <el-form label-width="96px">
        <el-form-item label="线体">
          <el-radio-group v-model="form.line_type">
            <el-radio-button label="smt">SMT</el-radio-button>
            <el-radio-button label="dip">DIP</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="线别名">
          <el-input v-model="form.line_name" placeholder="如 SMT1" />
        </el-form-item>
        <el-form-item label="订单/PO">
          <el-input v-model="form.purchase_no" />
        </el-form-item>
        <el-form-item label="机型">
          <el-input v-model="form.model_code" />
        </el-form-item>
        <el-form-item label="品名">
          <el-input v-model="form.model_name" />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="form.order_qty" :min="0" :controls="false" style="width: 160px" />
        </el-form-item>
        <el-form-item label="交期">
          <el-input v-model="form.due_date" placeholder="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="日计划">
          <el-input v-model="form.daily_plan" placeholder="如 09-10 上线 500" />
        </el-form-item>
        <el-form-item label="排产状态">
          <el-select v-model="form.schedule_status" style="width: 160px">
            <el-option v-for="(lab, k) in meta?.schedule_statuses || {}" :key="k" :label="lab" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createSchedule,
  deleteSchedule,
  fetchScheduleMeta,
  fetchSchedules,
  refreshScheduleKitting,
  updateSchedule,
  type ScheduleMeta,
  type ScheduleRow,
} from '@/api/planning'

const loading = ref(false)
const saving = ref(false)
const refreshing = ref(false)
const open = ref(false)
const lineType = ref<'smt' | 'dip'>('smt')
const rows = ref<ScheduleRow[]>([])
const meta = ref<ScheduleMeta | null>(null)

const form = reactive({
  id: 0,
  line_type: 'smt' as 'smt' | 'dip',
  line_name: '',
  purchase_no: '',
  model_code: '',
  model_name: '',
  order_qty: 0,
  due_date: '',
  daily_plan: '',
  schedule_status: 'planned',
  remark: '',
})

function matLabel(st: string) {
  return meta.value?.material_statuses?.[st] || st || '—'
}
function schLabel(st: string) {
  return meta.value?.schedule_statuses?.[st] || st || '—'
}
function matTag(st: string) {
  if (st === 'ready') return 'success'
  if (st === 'partial') return 'warning'
  if (st === 'shortage' || st === 'unbound') return 'danger'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    if (!meta.value) meta.value = await fetchScheduleMeta()
    rows.value = await fetchSchedules(lineType.value)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openEdit(row?: ScheduleRow) {
  form.id = row?.id || 0
  form.line_type = (row?.line_type as 'smt' | 'dip') || lineType.value
  form.line_name = row?.line_name || ''
  form.purchase_no = row?.purchase_no || ''
  form.model_code = row?.model_code || ''
  form.model_name = row?.model_name || ''
  form.order_qty = row?.order_qty || 0
  form.due_date = row?.due_date || ''
  form.daily_plan = row?.daily_plan || ''
  form.schedule_status = row?.schedule_status || 'planned'
  form.remark = row?.remark || ''
  open.value = true
}

async function onSave() {
  if (!form.model_code.trim() && !form.purchase_no.trim()) {
    ElMessage.warning('请至少填写机型或订单号')
    return
  }
  saving.value = true
  try {
    const body = {
      line_type: form.line_type,
      line_name: form.line_name,
      purchase_no: form.purchase_no,
      model_code: form.model_code,
      model_name: form.model_name,
      order_qty: form.order_qty,
      due_date: form.due_date,
      daily_plan: form.daily_plan,
      schedule_status: form.schedule_status,
      remark: form.remark,
    }
    if (form.id) await updateSchedule(form.id, body)
    else await createSchedule(body)
    ElMessage.success('已保存')
    open.value = false
    lineType.value = form.line_type
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onRemove(row: ScheduleRow) {
  try {
    await ElMessageBox.confirm(`删除排产 ${row.model_code || row.purchase_no || row.id}？`, '确认')
    await deleteSchedule(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}

async function onRefreshKit() {
  refreshing.value = true
  try {
    const res = await refreshScheduleKitting(lineType.value)
    ElMessage.success(res.message || '已刷新')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '刷新失败')
  } finally {
    refreshing.value = false
  }
}

onMounted(load)
</script>
