<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">{{ pageTitle }}</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            ERP 主数据 · 无预置外部客户，请自行维护
          </p>
        </div>
        <div style="display: flex; gap: 8px">
          <el-input v-model="q" clearable placeholder="编码/名称" style="width: 180px" @keyup.enter="load" />
          <el-button @click="load">查询</el-button>
          <el-button type="primary" @click="openEdit()">新建</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small" max-height="calc(100vh - 260px)">
          <el-table-column prop="code" label="编码" width="120" />
          <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
          <el-table-column prop="short_name" label="简称" width="100" />
          <el-table-column prop="contact" label="联系人" width="100" />
          <el-table-column prop="phone" label="电话" width="120" />
          <el-table-column prop="address" label="地址" min-width="160" show-overflow-tooltip />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" @click="onRemove(row)">停用</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="open" :title="form.id ? '编辑' : '新建'" width="520px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="编码" required>
          <el-input v-model="form.code" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="简称">
          <el-input v-model="form.short_name" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="form.contact" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="form.address" />
        </el-form-item>
        <el-form-item label="税号">
          <el-input v-model="form.tax_no" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteCustomer,
  deleteSupplier,
  fetchCustomers,
  fetchSuppliers,
  saveCustomer,
  saveSupplier,
  type Partner,
} from '@/api/master'

const route = useRoute()
const kind = computed(() => (route.meta.partnerKind === 'supplier' ? 'supplier' : 'customer'))
const pageTitle = computed(() => (kind.value === 'supplier' ? '供应商' : '客户资料'))

const loading = ref(false)
const saving = ref(false)
const open = ref(false)
const q = ref('')
const rows = ref<Partner[]>([])
const form = reactive({
  id: 0,
  code: '',
  name: '',
  short_name: '',
  contact: '',
  phone: '',
  address: '',
  tax_no: '',
  remark: '',
  is_active: true,
})

async function load() {
  loading.value = true
  try {
    const res =
      kind.value === 'supplier'
        ? await fetchSuppliers({ q: q.value, active_only: false })
        : await fetchCustomers({ q: q.value, active_only: false })
    rows.value = res.items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openEdit(row?: Partner) {
  form.id = row?.id || 0
  form.code = row?.code || ''
  form.name = row?.name || ''
  form.short_name = row?.short_name || ''
  form.contact = row?.contact || ''
  form.phone = row?.phone || ''
  form.address = row?.address || ''
  form.tax_no = row?.tax_no || ''
  form.remark = row?.remark || ''
  form.is_active = row?.is_active ?? true
  open.value = true
}

async function onSave() {
  if (!form.code.trim() || !form.name.trim()) {
    ElMessage.warning('请填写编码和名称')
    return
  }
  saving.value = true
  try {
    const payload = {
      id: form.id || undefined,
      code: form.code.trim(),
      name: form.name.trim(),
      short_name: form.short_name,
      contact: form.contact,
      phone: form.phone,
      address: form.address,
      tax_no: form.tax_no,
      remark: form.remark,
      is_active: form.is_active,
    }
    if (kind.value === 'supplier') await saveSupplier(payload)
    else await saveCustomer(payload)
    ElMessage.success('已保存')
    open.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onRemove(row: Partner) {
  try {
    await ElMessageBox.confirm(`停用 ${row.code} ${row.name}？`, '确认')
    if (kind.value === 'supplier') await deleteSupplier(row.id)
    else await deleteCustomer(row.id)
    ElMessage.success('已停用')
    await load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e instanceof Error ? e.message : '操作失败')
  }
}

onMounted(load)
watch(kind, () => {
  q.value = ''
  load()
})
</script>
