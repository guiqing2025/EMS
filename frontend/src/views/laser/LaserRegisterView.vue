<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">镭雕登记</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            菲利斯按镭雕日期+机型+流水挂单；恩玖按贴码前缀+流水挂单。AOI / ICT 板码按此规则归属订单
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button :loading="importing" @click="onImportDefault">导入桌面旧表</el-button>
          <el-button type="primary" plain :loading="importingFeilisi" @click="onImportFeilisi">
            导入菲利斯贴码登记表
          </el-button>
          <el-button type="success" :loading="importingEnjiu" @click="onImportEnjiu">导入恩玖贴码登记表</el-button>
          <el-button type="success" plain :loading="ttsSyncing" @click="onTtsSync">同步 TTS 镭雕/补码</el-button>
          <el-button type="warning" plain :loading="aoiSyncing" @click="onAoiSync">抓取 AOI</el-button>
          <el-button type="warning" plain :loading="ictSyncing" @click="onIctSync">抓取 ICT</el-button>
          <el-button type="primary" @click="dialogOpen = true">新建登记</el-button>
        </div>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" @submit.prevent="load">
          <el-form-item label="客户">
            <el-select v-model="filters.customer_id" clearable style="width: 140px">
              <el-option label="菲利斯" value="feilisi" />
              <el-option label="恩玖·鼎雄" value="enjiu" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-input v-model="filters.purchase_no" placeholder="采购订单号" clearable style="width: 180px" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="filters.model_code" placeholder="机型" clearable style="width: 160px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="load">查询</el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="loading" :data="rows" border stripe size="small" max-height="calc(100vh - 280px)">
          <el-table-column prop="laser_date" label="日期" width="90" />
          <el-table-column prop="model_code" label="机型" width="120" show-overflow-tooltip />
          <el-table-column prop="purchase_no" label="采购订单号" width="150" show-overflow-tooltip />
          <el-table-column prop="barcode_prefix" label="贴码前缀" width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.barcode_prefix || '—' }}</template>
          </el-table-column>
          <el-table-column label="流水段" width="120">
            <template #default="{ row }">{{ padSeq(row) }}</template>
          </el-table-column>
          <el-table-column prop="order_qty" label="订单数" width="80" align="right" />
          <el-table-column prop="customer_name" label="客户" width="100" />
          <el-table-column prop="source" label="来源" width="120" show-overflow-tooltip />
          <el-table-column prop="created_by" label="登记人" width="90" />
          <el-table-column prop="remark" label="备注" min-width="100" show-overflow-tooltip />
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button link type="danger" @click="onDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="dialogOpen" title="新建镭雕登记" width="520px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="客户">
          <el-select v-model="form.customer_id" style="width: 100%" @change="onCustomerPick">
            <el-option label="菲利斯" value="feilisi" />
            <el-option label="恩玖·鼎雄" value="enjiu" />
          </el-select>
        </el-form-item>
        <el-form-item label="镭雕日期" required>
          <el-input v-model="form.laser_date" placeholder="YYMMDD，多日用 \\ 分隔，如 260303\\260304" />
        </el-form-item>
        <el-form-item label="机型" required>
          <el-input v-model="form.model_code" placeholder="如 120-200235-09" />
        </el-form-item>
        <el-form-item label="采购订单号" required>
          <el-input v-model="form.purchase_no" />
        </el-form-item>
        <el-form-item label="订单数">
          <el-input-number v-model="form.order_qty" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="对应流水" required>
          <el-input v-model="form.seq_range" placeholder="如 00001-03000 或 03/80001-89999" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createLaserBatch,
  deleteLaserBatch,
  fetchLaserBatches,
  importDefaultLaserExcel,
  importEnjiuPrintRegister,
  importFeilisiPrintRegister,
  syncAoi,
  syncIct,
  syncTtsLaser,
  type LaserBatch,
} from '@/api/laser'

const loading = ref(false)
const importing = ref(false)
const importingFeilisi = ref(false)
const importingEnjiu = ref(false)
const aoiSyncing = ref(false)
const ictSyncing = ref(false)
const ttsSyncing = ref(false)
const saving = ref(false)
const dialogOpen = ref(false)
const rows = ref<LaserBatch[]>([])
const filters = reactive({ customer_id: 'enjiu', purchase_no: '', model_code: '' })
const form = reactive({
  customer_id: 'feilisi',
  customer_name: '菲利斯',
  laser_date: '',
  model_code: '',
  purchase_no: '',
  order_qty: 0,
  seq_range: '',
  remark: '',
})

function pad(n: number, width = 5) {
  return String(n).padStart(width, '0')
}

function padSeq(row: LaserBatch) {
  const w = row.barcode_prefix ? 4 : 5
  return `${pad(row.seq_from, w)}-${pad(row.seq_to, w)}`
}

function onCustomerPick() {
  form.customer_name = form.customer_id === 'enjiu' ? '恩玖·鼎雄' : '菲利斯'
}

async function load() {
  loading.value = true
  try {
    rows.value = await fetchLaserBatches({ ...filters, limit: 2000 })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onSave() {
  saving.value = true
  try {
    await createLaserBatch({ ...form })
    ElMessage.success('已保存')
    dialogOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onDelete(row: LaserBatch) {
  try {
    await ElMessageBox.confirm(`删除 ${row.purchase_no} / ${row.laser_date} 流水段？`, '确认')
    await deleteLaserBatch(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}

async function onImportDefault() {
  importing.value = true
  try {
    const res = await importDefaultLaserExcel()
    ElMessage.success(`导入完成：${res.created_rows || 0} 行`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导入失败')
  } finally {
    importing.value = false
  }
}

async function onImportFeilisi() {
  importingFeilisi.value = true
  try {
    const res = await importFeilisiPrintRegister()
    const errN = (res.errors || []).length
    ElMessage.success(
      `菲利斯贴码导入：新增 ${res.created}，更新 ${res.updated}，跳过 ${res.skipped}` +
        (res.ict_rematch_linked != null ? `；ICT 归属 ${res.ict_rematch_linked}` : '') +
        (res.aoi_rematch_matched != null ? `；AOI 归属 ${res.aoi_rematch_matched}` : '') +
        (errN ? `；解析告警 ${errN}` : ''),
    )
    filters.customer_id = 'feilisi'
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导入失败')
  } finally {
    importingFeilisi.value = false
  }
}

async function onImportEnjiu() {
  importingEnjiu.value = true
  try {
    const res = await importEnjiuPrintRegister()
    const errN = (res.errors || []).length
    ElMessage.success(
      `恩玖贴码导入：新增 ${res.created}，更新 ${res.updated}，跳过 ${res.skipped}` +
        (res.ict_rematch_linked != null ? `；ICT 归属 ${res.ict_rematch_linked}` : '') +
        (errN ? `；解析告警 ${errN}` : ''),
    )
    filters.customer_id = 'enjiu'
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导入失败')
  } finally {
    importingEnjiu.value = false
  }
}

async function onAoiSync() {
  aoiSyncing.value = true
  try {
    const res = await syncAoi(false)
    ElMessage.success(
      `AOI 处理文件 ${res.files_processed || 0}，板码 ${res.boards_upserted || 0}，归属 ${(res.rematch as any)?.matched ?? '—'}`,
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : 'AOI 抓取失败')
  } finally {
    aoiSyncing.value = false
  }
}

async function onIctSync() {
  ictSyncing.value = true
  try {
    const res = await syncIct(false)
    ElMessage.success(
      `ICT 处理文件 ${res.files_processed || 0}，板码 ${res.boards_upserted || 0}，归属 ${(res.rematch as any)?.matched ?? '—'}`,
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : 'ICT 抓取失败')
  } finally {
    ictSyncing.value = false
  }
}

async function onTtsSync() {
  ttsSyncing.value = true
  try {
    const res = await syncTtsLaser(true)
    ElMessage.success(
      `TTS 同步完成：新增 ${res.created || 0}，更新 ${res.updated || 0}，纠正单号 ${res.po_fixed || 0}，跳过 ${res.skipped || 0}`,
    )
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : 'TTS 同步失败')
  } finally {
    ttsSyncing.value = false
  }
}

onMounted(load)
</script>
