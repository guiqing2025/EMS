<template>
  <el-dialog v-model="visible" title="批量来料入账" width="920px" destroy-on-close @open="onOpen">
    <el-form label-width="72px" size="small">
      <el-form-item label="客户" required>
        <el-select v-model="customerId" filterable placeholder="选择客户" style="width: 220px">
          <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="送货人" required>
        <el-input v-model="giver" placeholder="谁送来的" style="width: 180px" />
      </el-form-item>
      <el-form-item label="接收人" required>
        <el-input v-model="receiver" placeholder="仓管签收人" style="width: 180px" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="batchRemark" placeholder="整批备注（可选）" style="max-width: 420px" />
      </el-form-item>
    </el-form>

    <div class="batch-toolbar">
      <el-upload
        :auto-upload="false"
        :show-file-list="false"
        accept=".xlsx,.xlsm"
        :disabled="parsing"
        @change="onFileChange"
      >
        <el-button type="primary" size="small" :loading="parsing">导入 Excel</el-button>
      </el-upload>
      <el-button size="small" link type="primary" :loading="tplLoading" @click="onDownloadTemplate">下载导入模板</el-button>
      <el-button size="small" @click="addRow">手动添加一行</el-button>
      <span class="cell-muted">表头需含「物料编码」「数量」；品名/规格可选。无档案料号将自动建档</span>
    </div>

    <div v-if="importInfo" class="import-info">{{ importInfo }}</div>

    <el-table :data="rows" border size="small" max-height="380">
      <el-table-column type="index" width="48" />
      <el-table-column label="物料编码" min-width="140">
        <template #default="{ row }">
          <el-input v-model="row.material_code" placeholder="料号" />
        </template>
      </el-table-column>
      <el-table-column label="数量" width="120">
        <template #default="{ row }">
          <el-input-number v-model="row.qty" :min="0" :precision="4" controls-position="right" style="width: 100%" />
        </template>
      </el-table-column>
      <el-table-column label="品名" min-width="100">
        <template #default="{ row }">
          <el-input v-model="row.material_name" placeholder="可选" />
        </template>
      </el-table-column>
      <el-table-column label="规格" min-width="100">
        <template #default="{ row }">
          <el-input v-model="row.spec" placeholder="可选" />
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="100">
        <template #default="{ row }">
          <el-input v-model="row.remark" placeholder="可选" />
        </template>
      </el-table-column>
      <el-table-column width="56" align="center">
        <template #default="{ $index }">
          <el-button link type="danger" @click="rows.splice($index, 1)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSubmit">确认入账</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { UploadFile } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchInbound, downloadInboundTemplate, fetchWarehouseCustomers, parseInboundExcel } from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import type { BatchInboundLine, WarehouseCustomer } from '@/types/warehouse'

const props = defineProps<{ modelValue: boolean; defaultCustomerId?: string }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; saved: [] }>()
const auth = useAuthStore()

const visible = ref(props.modelValue)
const saving = ref(false)
const parsing = ref(false)
const tplLoading = ref(false)
const customerId = ref('')
const batchRemark = ref('')
const giver = ref('')
const receiver = ref('')
const importInfo = ref('')
const customers = ref<WarehouseCustomer[]>([])
const rows = ref<BatchInboundLine[]>([])

watch(() => props.modelValue, (v) => { visible.value = v })
watch(visible, (v) => emit('update:modelValue', v))

function emptyRow(): BatchInboundLine {
  return { material_code: '', qty: 0, remark: '', material_name: '', spec: '' }
}

function addRow() {
  rows.value.push(emptyRow())
}

function formatCreatedHint(createdCount: number, createdCodes: string[]) {
  if (!createdCount) return ''
  const sample = createdCodes.slice(0, 5).join('、')
  const more = createdCodes.length > 5 ? ` 等 ${createdCount} 个` : ''
  return `，其中新建料号 ${createdCount} 条${sample ? `（${sample}${more}）` : ''}`
}

async function onDownloadTemplate() {
  tplLoading.value = true
  try {
    await downloadInboundTemplate()
    ElMessage.success('模板已开始下载')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下载失败')
  } finally {
    tplLoading.value = false
  }
}

async function onOpen() {
  if (!customers.value.length) customers.value = await fetchWarehouseCustomers()
  customerId.value = props.defaultCustomerId || customers.value[0]?.id || ''
  batchRemark.value = ''
  giver.value = ''
  receiver.value = auth.user?.display_name || auth.user?.username || ''
  importInfo.value = ''
  rows.value = []
}

async function onFileChange(uploadFile: UploadFile) {
  const raw = uploadFile.raw
  if (!raw) return
  parsing.value = true
  importInfo.value = ''
  try {
    const res = await parseInboundExcel(raw)
    rows.value = res.items.map((item) => ({
      material_code: item.material_code,
      qty: item.qty,
      remark: item.remark || '',
      material_name: item.material_name || '',
      spec: item.spec || '',
    }))
    const errCount = res.errors?.length || 0
    importInfo.value = `已从 Excel 解析 ${res.parsed_count} 行${res.header_row ? `（表头在第 ${res.header_row} 行）` : ''}${errCount ? `，${errCount} 行数量无效已跳过` : ''}`
    ElMessage.success(`已导入 ${res.parsed_count} 行`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '解析失败')
  } finally {
    parsing.value = false
  }
}

async function onSubmit() {
  if (!customerId.value) {
    ElMessage.error('请选择客户')
    return
  }
  if (!giver.value.trim()) {
    ElMessage.error('请填写送货人')
    return
  }
  if (!receiver.value.trim()) {
    ElMessage.error('请填写接收人')
    return
  }
  const items = rows.value
    .map((r) => ({
      material_code: r.material_code.trim(),
      qty: Number(r.qty),
      remark: r.remark?.trim() || '',
      material_name: r.material_name?.trim() || '',
      spec: r.spec?.trim() || '',
    }))
    .filter((r) => r.material_code && r.qty > 0)
  if (!items.length) {
    ElMessage.error('请先导入 Excel 或填写至少一行有效来料')
    return
  }
  saving.value = true
  try {
    const res = await batchInbound(customerId.value, items, {
      remark: batchRemark.value.trim(),
      giver: giver.value.trim(),
      receiver: receiver.value.trim(),
    })
    const errs = res.errors || []
    const createdCount = res.created_count || 0
    const createdCodes = res.created_codes || []
    const createdHint = formatCreatedHint(createdCount, createdCodes)
    if (errs.length) {
      const detail = errs
        .slice(0, 20)
        .map((e) => `第${e.row ?? '?'}行 ${e.material_code || '—'}：${e.error}`)
        .join('\n')
      const more = errs.length > 20 ? `\n…另有 ${errs.length - 20} 条` : ''
      await ElMessageBox.alert(
        `成功 ${res.success_count} 条${createdHint}，批次号 ${res.ref_no}\n失败 ${errs.length} 条：\n\n${detail}${more}`,
        '部分来料失败',
        { confirmButtonText: '知道了', type: 'warning' },
      )
      const failedCodes = new Set(errs.map((e) => (e.material_code || '').trim()).filter(Boolean))
      rows.value = rows.value.filter((r) => failedCodes.has(r.material_code.trim()))
      emit('saved')
      return
    }
    ElMessage.success(`来料入账 ${res.success_count} 条${createdHint}，批次号 ${res.ref_no}`)
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '入账失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.batch-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.import-info {
  font-size: 12px;
  color: #16a34a;
  margin-bottom: 8px;
}
.cell-muted {
  font-size: 12px;
  color: var(--erp-text-muted);
}
</style>
