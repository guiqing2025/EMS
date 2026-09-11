<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">客户资料</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            维护客户基础信息与三证（营业执照 / 组织机构代码证 / 税务登记证）
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
          <el-table-column label="三证" width="100" align="center">
            <template #default="{ row }">
              <span>{{ certCount(row) }}/3</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openDetail(row)">详情</el-button>
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" @click="onRemove(row)">停用</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 详情 -->
    <el-drawer v-model="detailOpen" title="客户详情" size="520px" destroy-on-close>
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="编码">{{ detail.code }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="简称">{{ detail.short_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="联系人">{{ detail.contact || '—' }}</el-descriptions-item>
          <el-descriptions-item label="电话">{{ detail.phone || '—' }}</el-descriptions-item>
          <el-descriptions-item label="地址">{{ detail.address || '—' }}</el-descriptions-item>
          <el-descriptions-item label="税号">{{ detail.tax_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="备注">{{ detail.remark || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="detail.is_active ? 'success' : 'info'" size="small">
              {{ detail.is_active ? '启用' : '停用' }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>
        <h4 style="margin: 20px 0 12px">三证</h4>
        <div class="cert-grid">
          <div v-for="c in CERT_DEFS" :key="c.kind" class="cert-card">
            <div class="cert-label">{{ c.label }}</div>
            <el-image
              v-if="certUrl(detail, c.kind)"
              :src="certUrl(detail, c.kind)"
              :preview-src-list="[certUrl(detail, c.kind)]"
              fit="contain"
              class="cert-img"
            />
            <div v-else class="cert-empty">未上传</div>
          </div>
        </div>
        <div style="margin-top: 20px">
          <el-button type="primary" @click="openEdit(detail); detailOpen = false">编辑</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 新建 / 编辑 -->
    <el-dialog
      v-model="editOpen"
      :title="form.id ? '编辑客户' : '新建客户'"
      width="640px"
      destroy-on-close
      @closed="onEditClosed"
    >
      <el-form label-width="100px">
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

      <template v-if="form.id">
        <el-divider content-position="left">三证图片</el-divider>
        <div class="cert-grid">
          <div v-for="c in CERT_DEFS" :key="c.kind" class="cert-card">
            <div class="cert-label">{{ c.label }}</div>
            <el-image
              v-if="certUrl(form, c.kind)"
              :src="certUrl(form, c.kind)"
              :preview-src-list="[certUrl(form, c.kind)]"
              fit="contain"
              class="cert-img"
            />
            <div v-else class="cert-empty">未上传</div>
            <div class="cert-actions">
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                accept="image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif"
                :disabled="uploadingKind === c.kind"
                @change="(f) => onCertPick(c.kind, f)"
              >
                <el-button size="small" :loading="uploadingKind === c.kind">上传</el-button>
              </el-upload>
              <el-button
                v-if="certUrl(form, c.kind)"
                size="small"
                type="danger"
                plain
                :loading="uploadingKind === c.kind"
                @click="onCertRemove(c.kind)"
              >
                删除
              </el-button>
            </div>
          </div>
        </div>
      </template>
      <p v-else style="margin: 0; color: var(--erp-text-muted); font-size: 13px">
        请先保存客户资料，再上传三证图片。
      </p>

      <template #footer>
        <el-button @click="editOpen = false">关闭</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import {
  deleteCustomer,
  deleteCustomerCert,
  fetchCustomer,
  fetchCustomers,
  saveCustomer,
  uploadCustomerCert,
  type CertKind,
  type Partner,
} from '@/api/master'

const CERT_DEFS: { kind: CertKind; label: string }[] = [
  { kind: 'business', label: '营业执照' },
  { kind: 'org', label: '组织机构代码证' },
  { kind: 'tax', label: '税务登记证' },
]

const loading = ref(false)
const saving = ref(false)
const editOpen = ref(false)
const detailOpen = ref(false)
const q = ref('')
const rows = ref<Partner[]>([])
const detail = ref<Partner | null>(null)
const uploadingKind = ref<CertKind | null>(null)

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
  cert_business_url: '',
  cert_org_url: '',
  cert_tax_url: '',
})

function certCount(row: Partner) {
  return [row.cert_business_url, row.cert_org_url, row.cert_tax_url].filter(Boolean).length
}

function certUrl(row: Partner | typeof form, kind: CertKind) {
  if (kind === 'business') return row.cert_business_url || ''
  if (kind === 'org') return row.cert_org_url || ''
  return row.cert_tax_url || ''
}

function applyCerts(src: Partner) {
  form.cert_business_url = src.cert_business_url || ''
  form.cert_org_url = src.cert_org_url || ''
  form.cert_tax_url = src.cert_tax_url || ''
}

async function load() {
  loading.value = true
  try {
    const res = await fetchCustomers({ q: q.value, active_only: false })
    rows.value = res.items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function openDetail(row: Partner) {
  try {
    detail.value = await fetchCustomer(row.id)
    detailOpen.value = true
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载详情失败')
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
  applyCerts(row || ({} as Partner))
  editOpen.value = true
  if (row?.id) {
    fetchCustomer(row.id)
      .then((full) => {
        if (form.id === full.id) applyCerts(full)
      })
      .catch(() => undefined)
  }
}

function onEditClosed() {
  uploadingKind.value = null
}

async function onSave() {
  if (!form.code.trim() || !form.name.trim()) {
    ElMessage.warning('请填写编码和名称')
    return
  }
  saving.value = true
  try {
    const saved = await saveCustomer({
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
    })
    form.id = saved.id
    applyCerts(saved)
    ElMessage.success('已保存')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onCertPick(kind: CertKind, uploadFile: UploadFile) {
  const raw = uploadFile.raw
  if (!raw || !form.id) return
  uploadingKind.value = kind
  try {
    const saved = await uploadCustomerCert(form.id, kind, raw)
    applyCerts(saved)
    ElMessage.success('证照已上传')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '上传失败')
  } finally {
    uploadingKind.value = null
  }
}

async function onCertRemove(kind: CertKind) {
  if (!form.id) return
  try {
    await ElMessageBox.confirm('删除该证照图片？', '确认')
  } catch {
    return
  }
  uploadingKind.value = kind
  try {
    const saved = await deleteCustomerCert(form.id, kind)
    applyCerts(saved)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  } finally {
    uploadingKind.value = null
  }
}

async function onRemove(row: Partner) {
  try {
    await ElMessageBox.confirm(`停用 ${row.code} ${row.name}？`, '确认')
    await deleteCustomer(row.id)
    ElMessage.success('已停用')
    await load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e instanceof Error ? e.message : '操作失败')
  }
}

onMounted(load)
</script>

<style scoped>
.cert-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.cert-card {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 8px;
  min-height: 140px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cert-label {
  font-size: 13px;
  font-weight: 600;
}
.cert-img {
  width: 100%;
  height: 110px;
  background: #f5f7fa;
}
.cert-empty {
  height: 110px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--erp-text-muted);
  background: #f5f7fa;
  font-size: 12px;
}
.cert-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
@media (max-width: 640px) {
  .cert-grid {
    grid-template-columns: 1fr;
  }
}
</style>
