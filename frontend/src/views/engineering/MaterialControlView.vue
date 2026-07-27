<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">物料管制</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            一张管制单可含多机型；工单总量与「本批管制数量」分开：从总量中抽多批分别换料，非整单都改
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button v-if="canEdit" @click="onDownloadTemplate">下载 Excel 模板</el-button>
          <el-button v-if="canEdit" :loading="importing" @click="excelInput?.click()">Excel 导入</el-button>
          <el-button v-if="canEdit" :loading="ecnParsing" type="success" plain @click="ecnInput?.click()">
            导入ECN
          </el-button>
          <el-button v-if="canEdit" type="primary" @click="openCreate">新建管制单</el-button>
          <input ref="excelInput" type="file" accept=".xlsx,.xlsm" style="display: none" @change="onImportExcel" />
          <input
            ref="ecnInput"
            type="file"
            accept=".xls,.xlsx,.xlsm,application/vnd.ms-excel"
            style="display: none"
            @change="onParseEcn"
          />
        </div>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" class="mc-filter" @submit.prevent="loadList">
          <el-form-item label="状态">
            <el-select v-model="status" clearable placeholder="全部" style="width: 120px" @change="loadList">
              <el-option label="草稿" value="draft" />
              <el-option label="已生效" value="active" />
              <el-option label="已取消" value="cancelled" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-input v-model="keyword" placeholder="管制单号 / 机型 / ECN" clearable style="width: 220px" @keyup.enter="loadList" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="loadList">查询</el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="loading" :data="rows" stripe border size="small" max-height="calc(100vh - 280px)">
          <el-table-column prop="control_no" label="管制单号" width="140" show-overflow-tooltip />
          <el-table-column prop="model_code" label="机型" min-width="160" show-overflow-tooltip />
          <el-table-column prop="control_type" label="类型" width="100" />
          <el-table-column label="状态" width="88">
            <template #default="{ row }">
              <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="工单" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              {{ (row.orders || []).map((o) => o.purchase_no).join('、') || '—' }}
            </template>
          </el-table-column>
          <el-table-column label="删料→放入" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ changeSummary(row) }}</template>
          </el-table-column>
          <el-table-column label="放入的料" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ addSummary(row) }}</template>
          </el-table-column>
          <el-table-column prop="ecn_no" label="ECN" width="100" show-overflow-tooltip />
          <el-table-column prop="created_by" label="录入帐号" width="120" show-overflow-tooltip />
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openDetail(row)">详情</el-button>
              <el-button v-if="canEdit && row.status === 'draft'" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button
                v-if="canEdit && row.status === 'draft'"
                size="small"
                type="primary"
                :loading="actingId === row.id"
                @click="onConfirm(row)"
              >
                确认
              </el-button>
              <el-button
                v-if="canEdit && (row.status === 'active' || row.status === 'draft')"
                size="small"
                type="danger"
                plain
                :loading="actingId === row.id"
                @click="onCancel(row)"
              >
                撤销
              </el-button>
              <el-button
                v-if="canEdit && row.status === 'cancelled'"
                size="small"
                type="danger"
                :loading="actingId === row.id"
                @click="onDelete(row)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-drawer v-model="detailOpen" title="管制单详情" size="860px">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="管制单号">{{ detail.control_no }}</el-descriptions-item>
          <el-descriptions-item label="机型">{{ detail.model_code }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ detail.control_type }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(detail.status)" size="small">{{ statusLabel(detail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="录入帐号">{{ detail.created_by || '—' }}</el-descriptions-item>
          <el-descriptions-item label="录入时间">{{ formatDt(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="确认帐号">{{ detail.confirmed_by || '—' }}</el-descriptions-item>
          <el-descriptions-item label="确认时间">{{ formatDt(detail.confirmed_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.status === 'cancelled'" label="取消帐号">
            {{ detail.cancelled_by || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="原因">{{ detail.reason || '—' }}</el-descriptions-item>
          <el-descriptions-item label="ECN">{{ detail.ecn_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="原件">
            <a v-if="detail.attachment_path" :href="attachmentHref(detail.id)" target="_blank" rel="noopener">
              {{ detail.attachment_name || '查看附件' }}
            </a>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="放入的料">{{ addSummary(detail) }}</el-descriptions-item>
        </el-descriptions>
        <div v-for="(g, gi) in detailGroups(detail)" :key="gi" class="mc-group-view">
          <h4>机型 {{ g.model_code }}</h4>
          <el-table :data="g.orders" size="small" border style="margin-bottom: 8px">
            <el-table-column prop="purchase_no" label="订单号" />
            <el-table-column prop="order_qty" label="工单总量" width="100" />
            <el-table-column prop="control_qty" label="合计管制" width="100" />
          </el-table>
          <div class="mc-sub-label">换料明细（共 {{ g.changes?.length || 0 }} 行；位号完整展示）</div>
          <el-table :data="g.changes" size="small" border class="mc-change-table">
            <el-table-column v-if="groupHasBatchQty(g)" prop="control_qty" label="本批管制" width="88" />
            <el-table-column prop="remove_code" label="删掉的料" min-width="120" />
            <el-table-column prop="remove_qty" label="删量" width="64" />
            <el-table-column label="删位号" min-width="160">
              <template #default="{ row }">
                <span class="mc-refdes">{{ row.remove_refdes || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="add_code" label="放入的料" min-width="120" />
            <el-table-column prop="add_qty" label="放量" width="64" />
            <el-table-column label="放位号" min-width="160">
              <template #default="{ row }">
                <span class="mc-refdes">{{ row.add_refdes || '—' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="formOpen" :title="editingId ? '编辑管制单' : '新建管制单'" width="820px" destroy-on-close>
      <el-alert
        v-if="parseWarnings.length"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        title="识别结果请人工核对后再保存；确认生效才会改 BOM"
      >
        <ul class="mc-warn-list">
          <li v-for="(w, i) in parseWarnings" :key="i">{{ w }}</li>
        </ul>
      </el-alert>
      <el-form v-loading="parsing" element-loading-text="正在识别…" label-width="96px">
        <el-form-item label="管制单号" required>
          <el-input v-model="form.control_no" placeholder="如 GZ2026060501" />
        </el-form-item>
        <el-form-item label="类型">
          <el-input v-model="form.control_type" />
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="form.reason" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="ECN">
          <el-input v-model="form.ecn_no" />
        </el-form-item>
        <el-form-item label="机型分组" required>
          <div class="mc-groups">
            <div v-for="(g, gi) in form.groups" :key="gi" class="mc-group-card">
              <div class="mc-group-head">
                <el-input v-model="g.model_code" placeholder="机型料号 如 120-300109-00" style="flex: 1" />
                <el-button :disabled="form.groups.length <= 1" @click="form.groups.splice(gi, 1)">删组</el-button>
              </div>
              <div class="mc-sub-label">工单（总量 ≠ 本批管制数量）</div>
              <div v-for="(o, oi) in g.orders" :key="'o' + oi" class="mc-dyn-row">
                <el-input v-model="o.purchase_no" placeholder="采购订单号" style="flex: 1" />
                <el-input-number
                  v-model="o.order_qty"
                  :min="0"
                  controls-position="right"
                  style="width: 120px"
                  placeholder="工单总量"
                />
                <span class="mc-qty-hint">总量</span>
                <el-input-number
                  v-model="o.control_qty"
                  :min="0"
                  controls-position="right"
                  style="width: 120px"
                  placeholder="合计管制"
                />
                <span class="mc-qty-hint">合计</span>
                <el-button :disabled="g.orders.length <= 1" @click="g.orders.splice(oi, 1)">删</el-button>
              </div>
              <el-button size="small" @click="g.orders.push({ purchase_no: '', order_qty: 0, control_qty: 0 })">
                加工单
              </el-button>
              <div class="mc-sub-label">
                换料（每行一批；本批套数可留 0，表示整单变更写在上方「合计」）
              </div>
              <div v-for="(c, ci) in g.changes" :key="'c' + ci" class="mc-change-block">
                <div class="mc-dyn-row">
                  <el-input-number
                    v-model="c.control_qty"
                    :min="0"
                    controls-position="right"
                    style="width: 130px"
                  />
                  <span class="mc-qty-hint">本批管制套数（分批时填；整单可填 0）</span>
                </div>
                <div class="mc-dyn-row">
                  <el-input v-model="c.remove_code" placeholder="删料号" style="flex: 1" />
                  <el-input-number v-model="c.remove_qty" :min="0" controls-position="right" style="width: 100px" />
                  <el-input v-model="c.remove_refdes" placeholder="删位号" style="flex: 1.2; min-width: 160px" />
                </div>
                <div class="mc-dyn-row">
                  <el-input v-model="c.add_code" placeholder="加料号" style="flex: 1" />
                  <el-input-number v-model="c.add_qty" :min="0" controls-position="right" style="width: 100px" />
                  <el-input v-model="c.add_refdes" placeholder="加位号" style="flex: 1.2; min-width: 160px" />
                </div>
                <div class="mc-dyn-row">
                  <el-input v-model="c.remark" placeholder="备注" style="flex: 1" />
                  <el-button :disabled="g.changes.length <= 1" @click="g.changes.splice(ci, 1)">删行</el-button>
                </div>
              </div>
              <el-button size="small" @click="g.changes.push(emptyChange())">加换料行</el-button>
            </div>
            <el-button type="primary" plain size="small" @click="addGroup">加机型分组</el-button>
          </div>
        </el-form-item>
        <el-form-item label="原件">
          <div class="mc-file-row">
            <input type="file" accept=".pdf,image/*" @change="onPickFile" />
            <span v-if="parsing" style="color: var(--erp-primary)">识别中…</span>
            <span v-else-if="form.attachment_name" style="color: var(--erp-text-muted)">已存：{{ form.attachment_name }}</span>
            <span v-else-if="pendingFile" style="color: var(--erp-text-muted)">待上传：{{ pendingFile.name }}</span>
          </div>
          <div class="mc-file-hint">选择 PDF / 图片后按机型自动拆组预填；保存草稿时再上传原件</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="ecnOpen" title="永联 ECN 导入预览" width="860px" destroy-on-close>
      <template v-if="ecnPreview">
        <el-alert
          v-if="ecnPreview.warnings?.length"
          type="warning"
          :closable="false"
          style="margin-bottom: 12px"
          :title="ecnPreview.warnings.join('；')"
        />
        <el-descriptions :column="2" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="机型">{{ ecnPreview.model_code }}</el-descriptions-item>
          <el-descriptions-item label="规格">{{ ecnPreview.model_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="建议单号">{{ ecnPreview.suggested_control_no }}</el-descriptions-item>
          <el-descriptions-item label="日期">{{ ecnPreview.ecn_date || '—' }}</el-descriptions-item>
          <el-descriptions-item label="原因" :span="2">{{ ecnPreview.reason || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div class="mc-sub-label">匹配在制订单（默认全选）</div>
        <el-table
          :data="ecnPreview.matched_orders"
          size="small"
          border
          max-height="180"
          style="margin-bottom: 12px"
          @selection-change="onEcnOrderSelect"
          ref="ecnOrderTable"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column prop="purchase_no" label="采购订单号" min-width="160" />
          <el-table-column prop="qty" label="数量" width="80" />
          <el-table-column prop="customer_name" label="客户" width="90" />
          <el-table-column prop="product_goods_name" label="品名" min-width="140" show-overflow-tooltip />
        </el-table>
        <div v-if="!ecnPreview.matched_orders?.length" class="mc-file-hint" style="margin-bottom: 12px">
          未匹配到在制订单，请确认订单已同步后再导入
        </div>
        <div class="mc-sub-label">换料明细（{{ ecnPreview.changes?.length || 0 }} 行；位号完整展示）</div>
        <el-table :data="ecnPreview.changes" size="small" border max-height="320" class="mc-change-table">
          <el-table-column label="删料号" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.remove_code || '—' }}</template>
          </el-table-column>
          <el-table-column label="删用量" width="70">
            <template #default="{ row }">{{ row.remove_qty || '—' }}</template>
          </el-table-column>
          <el-table-column label="删位号" min-width="160">
            <template #default="{ row }">
              <span class="mc-refdes">{{ row.remove_refdes || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="加料号" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.add_code || '—' }}</template>
          </el-table-column>
          <el-table-column label="加用量" width="70">
            <template #default="{ row }">{{ row.add_qty || '—' }}</template>
          </el-table-column>
          <el-table-column label="加位号" min-width="160">
            <template #default="{ row }">
              <span class="mc-refdes">{{ row.add_refdes || '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="ecnOpen = false">取消</el-button>
        <el-button type="primary" :loading="ecnImporting" :disabled="!ecnCanImport" @click="onImportEcnConfirm">
          生成管制草稿
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cancelMaterialControl,
  deleteMaterialControl,
  confirmMaterialControl,
  createMaterialControl,
  downloadMaterialControlTemplate,
  fetchMaterialControls,
  importMaterialControlExcel,
  importYonglianEcnFile,
  materialControlAttachmentUrl,
  parseMaterialControlFile,
  parseYonglianEcnFile,
  updateMaterialControl,
  uploadMaterialControlAttachment,
} from '@/api/materialControls'
import { useAuthStore } from '@/stores/auth'
import type { MaterialControl, MaterialControlParseResult, YonglianEcnParseResult } from '@/types/materialControl'

const auth = useAuthStore()
const canEdit = computed(() => {
  const role = auth.user?.role
  return role === 'admin' || role === 'planner' || role === 'engineering'
})

const loading = ref(false)
const saving = ref(false)
const parsing = ref(false)
const importing = ref(false)
const ecnParsing = ref(false)
const ecnImporting = ref(false)
const actingId = ref<number | null>(null)
const rows = ref<MaterialControl[]>([])
const status = ref('')
const keyword = ref('')
const excelInput = ref<HTMLInputElement | null>(null)
const ecnInput = ref<HTMLInputElement | null>(null)
const ecnOpen = ref(false)
const ecnPreview = ref<YonglianEcnParseResult | null>(null)
const ecnFile = ref<File | null>(null)
const ecnSelectedPos = ref<string[]>([])
const ecnOrderTable = ref<{ toggleRowSelection: (row: unknown, selected?: boolean) => void; clearSelection: () => void } | null>(null)

const ecnCanImport = computed(() => {
  if (!ecnPreview.value || !ecnFile.value) return false
  return ecnSelectedPos.value.length > 0 && (ecnPreview.value.changes?.length || 0) > 0
})

const detailOpen = ref(false)
const detail = ref<MaterialControl | null>(null)

const formOpen = ref(false)
const editingId = ref<number | null>(null)
const pendingFile = ref<File | null>(null)
const parseWarnings = ref<string[]>([])

type FormOrder = { purchase_no: string; order_qty: number; control_qty: number }
type FormChange = {
  control_qty: number
  remove_code: string
  remove_qty: number
  remove_refdes: string
  add_code: string
  add_qty: number
  add_refdes: string
  remark: string
}
type FormGroup = { model_code: string; orders: FormOrder[]; changes: FormChange[] }

const form = reactive({
  control_no: '',
  control_type: 'PCBA管制',
  reason: '',
  ecn_no: '',
  attachment_name: '',
  groups: [emptyGroup()] as FormGroup[],
})

function emptyChange(): FormChange {
  return {
    control_qty: 0,
    remove_code: '',
    remove_qty: 0,
    remove_refdes: '',
    add_code: '',
    add_qty: 0,
    add_refdes: '',
    remark: '',
  }
}

function emptyGroup(): FormGroup {
  return {
    model_code: '',
    orders: [{ purchase_no: '', order_qty: 0, control_qty: 0 }],
    changes: [emptyChange()],
  }
}

function addGroup() {
  form.groups.push(emptyGroup())
}

function statusLabel(s: string) {
  if (s === 'draft') return '草稿'
  if (s === 'active') return '已生效'
  if (s === 'cancelled') return '已取消'
  return s
}

function statusTag(s: string) {
  if (s === 'active') return 'success'
  if (s === 'cancelled') return 'info'
  return 'warning'
}

function detailGroups(row: MaterialControl) {
  if (row.groups?.length) return row.groups
  return [
    {
      model_code: row.model_code || '—',
      orders: row.orders || [],
      changes: row.changes || [],
    },
  ]
}

/** 永联 ECR 整单变更时常不填行级本批管制（全 0）；有分批数量时才显示该列 */
function groupHasBatchQty(g: { changes?: Array<{ control_qty?: number | null }> }) {
  return (g.changes || []).some((c) => Number(c.control_qty || 0) > 0)
}

function changeSummary(row: MaterialControl) {
  const groups = detailGroups(row)
  const pairs = new Set<string>()
  for (const g of groups) {
    for (const c of g.changes || []) {
      pairs.add(`${c.remove_code || '—'}→${c.add_code || '—'}`)
    }
  }
  return [...pairs].join('；') || '—'
}

function addSummary(row: MaterialControl) {
  const groups = detailGroups(row)
  const codes = new Set<string>()
  for (const g of groups) {
    for (const c of g.changes || []) {
      const code = (c.add_code || '').trim()
      if (code) codes.add(code)
    }
  }
  return [...codes].join('、') || '—'
}

function formatDt(v?: string | null) {
  if (!v) return '—'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v).replace('T', ' ').slice(0, 19)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function attachmentHref(id: number) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const base = materialControlAttachmentUrl(id)
  return token ? `${base}?access_token=${encodeURIComponent(token)}` : base
}

function genControlNo() {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const seq = String(Math.floor(Math.random() * 90) + 10)
  return `GZ${y}${m}${day}${seq}`
}

function resetForm() {
  form.control_no = genControlNo()
  form.control_type = 'PCBA管制'
  form.reason = ''
  form.ecn_no = ''
  form.attachment_name = ''
  form.groups = [emptyGroup()]
  pendingFile.value = null
  parseWarnings.value = []
}

function mapGroupFromApi(g: {
  model_code?: string
  orders?: Array<{ purchase_no?: string; order_qty?: number; control_qty?: number }>
  changes?: Array<Record<string, unknown>>
}): FormGroup {
  const orders = (g.orders || []).map((o) => ({
    purchase_no: o.purchase_no || '',
    order_qty: Number(o.order_qty) || 0,
    control_qty: Number(o.control_qty) || 0,
  }))
  const changes = (g.changes || []).map((c) => ({
    control_qty: Number(c.control_qty) || 0,
    remove_code: String(c.remove_code || ''),
    remove_qty: Number(c.remove_qty) || 0,
    remove_refdes: String(c.remove_refdes || ''),
    add_code: String(c.add_code || ''),
    add_qty: Number(c.add_qty) || 0,
    add_refdes: String(c.add_refdes || ''),
    remark: String(c.remark || ''),
  }))
  return {
    model_code: g.model_code || '',
    orders: orders.length ? orders : [{ purchase_no: '', order_qty: 0, control_qty: 0 }],
    changes: changes.length ? changes : [emptyChange()],
  }
}

function applyParseResult(result: MaterialControlParseResult) {
  const f = result.fields || {}
  if (f.control_no) form.control_no = f.control_no
  if (f.control_type) form.control_type = f.control_type
  if (f.reason) form.reason = f.reason
  if (f.ecn_no) form.ecn_no = f.ecn_no
  if (f.groups?.length) {
    form.groups = f.groups.map((g) => mapGroupFromApi(g))
  } else if (f.model_code || f.orders?.length) {
    form.groups = [
      mapGroupFromApi({
        model_code: f.model_code,
        orders: f.orders,
        changes: f.changes,
      }),
    ]
  }
  parseWarnings.value = result.warnings?.length ? [...result.warnings] : ['识别结果请人工核对']
}

function openCreate() {
  editingId.value = null
  resetForm()
  formOpen.value = true
}

function openEdit(row: MaterialControl) {
  editingId.value = row.id
  parseWarnings.value = []
  form.control_no = row.control_no
  form.control_type = row.control_type || 'PCBA管制'
  form.reason = row.reason || ''
  form.ecn_no = row.ecn_no || ''
  form.attachment_name = row.attachment_name || ''
  form.groups = detailGroups(row).map((g) => mapGroupFromApi(g))
  if (!form.groups.length) form.groups = [emptyGroup()]
  pendingFile.value = null
  formOpen.value = true
}

function openDetail(row: MaterialControl) {
  detail.value = row
  detailOpen.value = true
}

async function onPickFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0] || null
  pendingFile.value = file
  if (!file) return
  parsing.value = true
  try {
    const result = await parseMaterialControlFile(file)
    applyParseResult(result)
    ElMessage.success(`已识别 ${form.groups.length} 个机型分组，请核对后保存`)
  } catch (e) {
    parseWarnings.value = [e instanceof Error ? e.message : '识别失败，请手工填写']
    ElMessage.warning(parseWarnings.value[0])
  } finally {
    parsing.value = false
  }
}

async function onDownloadTemplate() {
  try {
    await downloadMaterialControlTemplate()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下载失败')
  }
}

async function onImportExcel(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importing.value = true
  try {
    const result = await importMaterialControlExcel(file)
    const msg = `导入完成：成功 ${result.created_count} 张草稿`
    if (result.errors?.length) {
      ElMessage.warning(`${msg}；失败 ${result.error_count}：${result.errors.slice(0, 3).join('；')}`)
    } else {
      ElMessage.success(msg)
    }
    await loadList()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导入失败')
  } finally {
    importing.value = false
  }
}

async function onParseEcn(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  ecnParsing.value = true
  try {
    const preview = await parseYonglianEcnFile(file)
    ecnFile.value = file
    ecnPreview.value = preview
    ecnSelectedPos.value = (preview.matched_orders || [])
      .filter((o) => o.selected !== false)
      .map((o) => o.purchase_no)
    ecnOpen.value = true
    setTimeout(() => {
      const table = ecnOrderTable.value
      table?.clearSelection?.()
      for (const row of preview.matched_orders || []) {
        if (row.selected !== false) table?.toggleRowSelection?.(row, true)
      }
    }, 50)
    if (preview.warnings?.length) {
      ElMessage.warning(preview.warnings[0])
    } else {
      ElMessage.success(preview.message || '识别成功')
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : 'ECN 解析失败')
  } finally {
    ecnParsing.value = false
  }
}

function onEcnOrderSelect(selected: Array<{ purchase_no: string }>) {
  ecnSelectedPos.value = selected.map((r) => r.purchase_no)
}

async function onImportEcnConfirm() {
  if (!ecnFile.value || !ecnPreview.value) return
  if (!ecnSelectedPos.value.length) {
    ElMessage.warning('请至少选择一个在制订单')
    return
  }
  ecnImporting.value = true
  try {
    const res = await importYonglianEcnFile(ecnFile.value, {
      selectedPurchaseNos: ecnSelectedPos.value,
      controlNo: ecnPreview.value.suggested_control_no,
    })
    ElMessage.success(res.message || '已生成草稿')
    ecnOpen.value = false
    ecnFile.value = null
    ecnPreview.value = null
    await loadList()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '生成草稿失败')
  } finally {
    ecnImporting.value = false
  }
}

function buildPayload() {
  return {
    control_no: form.control_no.trim(),
    control_type: form.control_type.trim() || 'PCBA管制',
    reason: form.reason.trim() || null,
    ecn_no: form.ecn_no.trim() || null,
    groups: form.groups
      .map((g) => ({
        model_code: g.model_code.trim(),
        orders: g.orders
          .filter((o) => o.purchase_no.trim())
          .map((o) => ({
            purchase_no: o.purchase_no.trim(),
            order_qty: Number(o.order_qty) || 0,
            control_qty: Number(o.control_qty) || 0,
          })),
        changes: g.changes
          .filter((c) => c.remove_code.trim() || c.add_code.trim())
          .map((c) => ({
            control_qty: Number(c.control_qty) || 0,
            remove_code: c.remove_code.trim(),
            remove_qty: Number(c.remove_qty) || 0,
            remove_refdes: c.remove_refdes.trim() || null,
            add_code: c.add_code.trim(),
            add_qty: Number(c.add_qty) || 0,
            add_refdes: c.add_refdes.trim() || null,
            remark: c.remark.trim() || null,
          })),
      }))
      .filter((g) => g.model_code && g.orders.length && g.changes.length),
  }
}

async function onSave() {
  const payload = buildPayload()
  if (!payload.control_no) {
    ElMessage.warning('请填写管制单号')
    return
  }
  if (!payload.groups.length) {
    ElMessage.warning('请至少完整填写一个机型分组（机型+工单+换料）')
    return
  }
  saving.value = true
  try {
    let saved: MaterialControl
    if (editingId.value) {
      saved = await updateMaterialControl(editingId.value, payload)
    } else {
      saved = await createMaterialControl(payload)
      editingId.value = saved.id
    }
    if (pendingFile.value) {
      saved = await uploadMaterialControlAttachment(saved.id, pendingFile.value)
      pendingFile.value = null
    }
    ElMessage.success('已保存')
    formOpen.value = false
    await loadList()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onConfirm(row: MaterialControl) {
  const groups = detailGroups(row)
  const batches: Array<{ qty: number; text: string }> = []
  for (const g of groups) {
    for (const c of g.changes || []) {
      const bq = Number(c.control_qty) || 0
      if (bq > 0) {
        batches.push({
          qty: bq,
          text: `${bq}套 ${c.remove_refdes || '—'}：${c.remove_code}→${c.add_code}`,
        })
      }
    }
  }
  const oq = Math.max(0, ...groups.flatMap((g) => (g.orders || []).map((o) => Number(o.order_qty) || 0)), 0)
  const isPartial =
    batches.length > 1 || (oq > 0 && batches.length >= 1 && batches.some((b) => b.qty < oq * 0.98))
  const tip = isPartial
    ? `本单疑似分批管制${oq ? `（工单总量 ${oq}）` : ''}：\n${batches
        .slice(0, 6)
        .map((b) => b.text)
        .join('\n')}${batches.length > 6 ? '\n…' : ''}\n\n确认后仅备案标记，不会把各组换料套到整份订单 BOM。`
    : `确认生效「${row.control_no}」？将按各机型分组修改在制订单专属 BOM。`

  try {
    await ElMessageBox.confirm(tip, '确认管制', { type: 'warning' })
  } catch {
    return
  }
  actingId.value = row.id
  try {
    const res = await confirmMaterialControl(row.id)
    const applied = res.confirm_applied?.length ? res.confirm_applied.join('、') : ''
    const skipDone = res.confirm_skipped_inactive?.length
      ? `已跳过非在制 ${res.confirm_skipped_inactive.length} 单`
      : ''
    const skipBom = res.confirm_skipped_no_bom?.length
      ? `在制无 BOM 未改料 ${res.confirm_skipped_no_bom.join('、')}`
      : ''
    const extra = [skipDone, skipBom].filter(Boolean).join('；')
    ElMessage.success(extra ? `已确认：${applied || '—'}${extra ? `（${extra}）` : ''}` : '已确认并写入在制订单 BOM')
    await loadList()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '确认失败')
  } finally {
    actingId.value = null
  }
}

async function askActionPassword(title: string): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt('请输入操作密码后继续', title, {
      inputType: 'password',
      inputPlaceholder: '操作密码',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValidator: (v) => (!!v && !!String(v).trim() ? true : '请输入密码'),
    })
    return String(value || '').trim()
  } catch {
    return null
  }
}

async function onCancel(row: MaterialControl) {
  try {
    await ElMessageBox.confirm(
      `撤销「${row.control_no}」将回滚其 BOM 变更（若已生效）。是否继续？`,
      '撤销管制',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const password = await askActionPassword('撤销管制 · 验证密码')
  if (!password) return
  actingId.value = row.id
  try {
    await cancelMaterialControl(row.id, password)
    ElMessage.success('已撤销；若订单无其他生效管制，订单列表将不再显示管制')
    await loadList()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '撤销失败')
  } finally {
    actingId.value = null
  }
}

async function onDelete(row: MaterialControl) {
  try {
    await ElMessageBox.confirm(`删除「${row.control_no}」后不可恢复，是否继续？`, '删除管制单', {
      type: 'warning',
    })
  } catch {
    return
  }
  const password = await askActionPassword('删除管制 · 验证密码')
  if (!password) return
  actingId.value = row.id
  try {
    await deleteMaterialControl(row.id, password)
    ElMessage.success('已删除')
    await loadList()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  } finally {
    actingId.value = null
  }
}

async function loadList() {
  loading.value = true
  try {
    rows.value = await fetchMaterialControls({
      status: status.value || undefined,
      keyword: keyword.value || undefined,
    })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadList)
</script>

<style scoped>
.mc-filter {
  margin-bottom: 12px;
}
.mc-dyn-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
.mc-change-block {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}
.mc-warn-list {
  margin: 6px 0 0;
  padding-left: 18px;
}
.mc-file-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.mc-file-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--erp-text-muted);
}
.mc-groups {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mc-group-card {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 10px;
  background: var(--el-fill-color-blank);
}
.mc-group-head {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.mc-sub-label {
  font-size: 12px;
  color: var(--erp-text-muted);
  margin: 8px 0 4px;
}
.mc-qty-hint {
  font-size: 12px;
  color: var(--erp-text-muted);
  white-space: nowrap;
}
.mc-group-view {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color);
}
.mc-group-view h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.mc-change-table :deep(.cell) {
  white-space: normal;
  line-height: 1.4;
}
.mc-refdes {
  display: block;
  white-space: normal;
  word-break: break-word;
  line-height: 1.45;
}
</style>
