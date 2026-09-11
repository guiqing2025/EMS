<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">{{ isReturn ? '采购退货' : '采购入库 / 验收' }}</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            {{
              isReturn
                ? '不合格确认退货（不入 GOOD 良品仓）'
                : '仅合格数量过账入 GOOD；过账生成应付挂钩点'
            }}
          </p>
        </div>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="erp-page-body">
        <el-table v-if="!isReturn" v-loading="loading" :data="receipts" border stripe size="small">
          <el-table-column prop="receipt_no" label="入库单号" width="150" />
          <el-table-column prop="po_no" label="采购单" width="140" />
          <el-table-column prop="warehouse_code" label="仓库" width="90" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="行摘要" min-width="180">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code}×${l.qty}`).join('；') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="success" :loading="acting === row.id" @click="onPost(row)">
                过账入库
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-table v-else v-loading="loading" :data="returns" border stripe size="small">
          <el-table-column prop="return_no" label="退货单号" width="150" />
          <el-table-column prop="po_no" label="采购单" width="140" />
          <el-table-column prop="warehouse_code" label="仓" width="90" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="行摘要" min-width="180">
            <template #default="{ row }">
              {{ (row.lines || []).map((l) => `${l.material_code}×${l.qty}`).join('；') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="danger" :loading="acting === row.id" @click="onConfirm(row)">
                确认退货
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  confirmReturn,
  fetchReceipts,
  fetchReturns,
  postReceipt,
  type ReceiptDoc,
  type ReturnDoc,
} from '@/api/purchase'

const route = useRoute()
const isReturn = computed(() => route.meta.purchaseKind === 'return')
const loading = ref(false)
const acting = ref<number | ''>('')
const receipts = ref<ReceiptDoc[]>([])
const returns = ref<ReturnDoc[]>([])

async function load() {
  loading.value = true
  try {
    if (isReturn.value) returns.value = (await fetchReturns()).items || []
    else receipts.value = (await fetchReceipts()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onPost(row: ReceiptDoc) {
  acting.value = row.id
  try {
    await postReceipt(row.id)
    ElMessage.success('已过账入 GOOD')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '过账失败')
  } finally {
    acting.value = ''
  }
}

async function onConfirm(row: ReturnDoc) {
  acting.value = row.id
  try {
    await confirmReturn(row.id)
    ElMessage.success('退货已确认')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    acting.value = ''
  }
}

onMounted(load)
watch(isReturn, load)
</script>
