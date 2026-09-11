<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">库存盘点</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">实盘过账调账（盘盈入库 / 盘亏出库）</p>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="openEdit">新建</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="stocktake_no" label="盘点单号" width="150" />
          <el-table-column prop="stock_owner" label="归属" width="100" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="行摘要" min-width="200">
            <template #default="{ row }">
              {{
                (row.lines || [])
                  .map((l) => `${l.material_code} 账${l.book_qty}/实${l.count_qty}`)
                  .join('；')
              }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" @click="onPost(row)">过账</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
    <el-dialog v-model="open" title="新建盘点" width="640px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="归属"><el-input v-model="form.stock_owner" /></el-form-item>
        <el-table :data="form.lines" border size="small">
          <el-table-column label="料号" min-width="120">
            <template #default="{ row }"><el-input v-model="row.material_code" size="small" /></template>
          </el-table-column>
          <el-table-column label="账面" width="110">
            <template #default="{ row }"><el-input-number v-model="row.book_qty" size="small" /></template>
          </el-table-column>
          <el-table-column label="实盘" width="110">
            <template #default="{ row }"><el-input-number v-model="row.count_qty" size="small" /></template>
          </el-table-column>
        </el-table>
        <el-button style="margin-top: 8px" @click="form.lines.push({ material_code: '', book_qty: 0, count_qty: 0 })">
          加一行
        </el-button>
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
import { ElMessage } from 'element-plus'
import { createStocktake, fetchStocktakes, postStocktake, type Stocktake } from '@/api/warehouseAux'

const loading = ref(false)
const saving = ref(false)
const open = ref(false)
const rows = ref<Stocktake[]>([])
const form = reactive({
  stock_owner: 'internal',
  lines: [{ material_code: '', book_qty: 0, count_qty: 0 }],
})

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchStocktakes()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openEdit() {
  form.stock_owner = 'internal'
  form.lines = [{ material_code: '', book_qty: 0, count_qty: 0 }]
  open.value = true
}

async function onSave() {
  saving.value = true
  try {
    await createStocktake({ ...form, lines: form.lines })
    ElMessage.success('已建盘点单')
    open.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onPost(row: Stocktake) {
  try {
    await postStocktake(row.id)
    ElMessage.success('盘点已过账')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
