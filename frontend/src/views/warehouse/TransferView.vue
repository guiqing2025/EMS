<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">{{ isOut ? '库存出库' : '库存调拨' }}</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            {{ isOut ? '从指定归属扣减库存' : '在库存归属之间调拨（customer_id / stock_owner）' }}
          </p>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="openEdit">新建</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="doc_no" label="单号" width="150" />
          <el-table-column prop="kind" label="类型" width="90" />
          <el-table-column prop="from_owner" label="来源" width="110" />
          <el-table-column prop="to_owner" label="目标" width="110" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="行摘要" min-width="160">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code}×${l.qty}`).join('；') }}
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
    <el-dialog v-model="open" :title="isOut ? '新建库存出库' : '新建调拨'" width="640px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="来源归属"><el-input v-model="form.from_owner" /></el-form-item>
        <el-form-item v-if="!isOut" label="目标归属"><el-input v-model="form.to_owner" /></el-form-item>
        <el-table :data="form.lines" border size="small">
          <el-table-column label="料号" min-width="120">
            <template #default="{ row }"><el-input v-model="row.material_code" size="small" /></template>
          </el-table-column>
          <el-table-column label="数量" width="120">
            <template #default="{ row }"><el-input-number v-model="row.qty" :min="0" size="small" /></template>
          </el-table-column>
        </el-table>
        <el-button style="margin-top: 8px" @click="form.lines.push({ material_code: '', qty: 1 })">加一行</el-button>
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
import { ElMessage } from 'element-plus'
import { createTransfer, fetchTransfers, postTransfer, type Transfer } from '@/api/warehouseAux'

const route = useRoute()
const isOut = computed(() => route.meta.transferKind === 'out')
const loading = ref(false)
const saving = ref(false)
const open = ref(false)
const rows = ref<Transfer[]>([])
const form = reactive({
  from_owner: 'internal',
  to_owner: 'customer-A',
  lines: [{ material_code: '', qty: 1 }],
})

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchTransfers(isOut.value ? 'out' : 'transfer')).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openEdit() {
  form.from_owner = 'internal'
  form.to_owner = 'customer-A'
  form.lines = [{ material_code: '', qty: 1 }]
  open.value = true
}

async function onSave() {
  saving.value = true
  try {
    await createTransfer({
      kind: isOut.value ? 'out' : 'transfer',
      from_owner: form.from_owner,
      to_owner: isOut.value ? '' : form.to_owner,
      lines: form.lines,
    })
    ElMessage.success('已建单')
    open.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onPost(row: Transfer) {
  try {
    await postTransfer(row.id)
    ElMessage.success('已过账')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
watch(isOut, load)
</script>
