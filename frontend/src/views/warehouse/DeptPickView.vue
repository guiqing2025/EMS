<template>
  <div class="erp-content dept-page">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">{{ pageTitle }}</h2>
          <div class="dept-summary">
            <div class="dept-stat"><span>待确认领料</span><strong>{{ summary.pending_issues }}</strong></div>
            <div class="dept-stat"><span>退料处理中</span><strong>{{ summary.pending_returns }}</strong></div>
          </div>
        </div>
      </div>

      <div class="erp-page-body">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="待确认领料" name="pending" />
          <el-tab-pane label="退料记录" name="returns" />
          <el-tab-pane label="申请退料" name="apply-return" />
        </el-tabs>

        <div v-if="activeTab === 'pending'" v-loading="loading">
          <p v-if="!pendingIssues.length" class="empty-card">暂无待确认领料</p>
          <div v-for="item in pendingIssues" :key="item.id" class="dept-card">
            <div class="dept-card-title">{{ item.material_code }}</div>
            <div class="dept-card-meta">{{ item.customer_name }} · {{ item.material_name || '' }}</div>
            <div class="dept-card-qty">数量 <strong>{{ item.qty }}</strong></div>
            <div class="dept-card-meta">单号 {{ item.issue_no }}</div>
            <div class="dept-card-actions">
              <el-button type="primary" class="btn-block" @click="onConfirmIssue(item.id)">确认签收</el-button>
              <el-button class="btn-block" @click="onRejectIssue(item.id)">拒收</el-button>
            </div>
          </div>
        </div>

        <div v-else-if="activeTab === 'returns'" v-loading="loading">
          <p v-if="!deptReturns.length" class="empty-card">暂无退料记录</p>
          <div v-for="item in deptReturns" :key="item.id" class="dept-card">
            <div class="dept-card-title">{{ item.return_no }}</div>
            <div class="dept-card-meta">{{ item.material_code }} · {{ item.qty }}</div>
            <div class="dept-card-meta">状态：{{ issueStatusLabel(item.status) }}</div>
          </div>
        </div>

        <div v-else class="dept-return-form">
          <el-form label-width="80px" style="max-width: 480px">
            <el-form-item label="物料" required>
              <el-select v-model="returnMaterialId" filterable placeholder="选择物料" style="width: 100%">
                <el-option
                  v-for="m in materials"
                  :key="m.id"
                  :label="`${m.customer_name} | ${m.material_code} | 可用${m.available_qty}`"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="数量" required>
              <el-input-number v-model="returnQty" :min="0.0001" :precision="4" style="width: 100%" />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="returnRemark" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="submitting" class="btn-block" @click="onSubmitReturn">提交退料申请</el-button>
            </el-form-item>
          </el-form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  confirmIssue,
  createReturn,
  fetchDeptSummary,
  fetchIssues,
  fetchMaterials,
  fetchReturns,
  rejectIssue,
} from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import type { StockIssue, StockReturn, WarehouseMaterial } from '@/types/warehouse'
import { issueStatusLabel } from '@/utils/warehouse'

const auth = useAuthStore()

const pageTitle = computed(
  () => `${auth.user?.display_name || auth.user?.department?.toUpperCase() || '部门'} · 领料确认`,
)

const activeTab = ref('pending')
const loading = ref(false)
const submitting = ref(false)
const summary = ref({ pending_issues: 0, pending_returns: 0 })
const pendingIssues = ref<StockIssue[]>([])
const deptReturns = ref<StockReturn[]>([])
const materials = ref<WarehouseMaterial[]>([])
const returnMaterialId = ref<number | undefined>()
const returnQty = ref(1)
const returnRemark = ref('')

watch(activeTab, (tab) => {
  if (tab === 'pending') loadPending()
  else if (tab === 'returns') loadDeptReturns()
  else if (tab === 'apply-return') loadMaterialsForReturn()
})

async function loadSummary() {
  summary.value = await fetchDeptSummary()
}

async function loadPending() {
  loading.value = true
  try {
    pendingIssues.value = await fetchIssues('pending_confirm')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadDeptReturns() {
  loading.value = true
  try {
    deptReturns.value = await fetchReturns()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadMaterialsForReturn() {
  try {
    materials.value = await fetchMaterials()
    returnMaterialId.value = materials.value[0]?.id
    returnQty.value = 1
    returnRemark.value = ''
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载物料失败')
  }
}

async function refresh() {
  await loadSummary()
  if (activeTab.value === 'pending') await loadPending()
  else if (activeTab.value === 'returns') await loadDeptReturns()
}

async function onConfirmIssue(id: number) {
  try {
    await confirmIssue(id)
    ElMessage.success('已确认签收')
    await refresh()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  }
}

async function onRejectIssue(id: number) {
  try {
    const { value } = await ElMessageBox.prompt('拒收原因（可选）', '拒收领料', {
      confirmButtonText: '拒收',
      cancelButtonText: '取消',
    })
    await rejectIssue(id, value || '')
    ElMessage.success('已拒收')
    await refresh()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e instanceof Error ? e.message : '操作失败')
  }
}

async function onSubmitReturn() {
  if (!returnMaterialId.value || !returnQty.value) {
    ElMessage.error('请选择物料并填写数量')
    return
  }
  submitting.value = true
  try {
    await createReturn(returnMaterialId.value, returnQty.value, returnRemark.value.trim())
    ElMessage.success('退料申请已提交')
    activeTab.value = 'returns'
    await refresh()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadSummary()
  await loadPending()
})
</script>

<style scoped>
.dept-page .erp-page-card {
  max-width: 640px;
  margin: 0 auto;
}
.dept-summary {
  display: flex;
  gap: 16px;
  margin-top: 10px;
}
.dept-stat {
  background: #f8fafc;
  border: 1px solid var(--erp-border);
  border-radius: 8px;
  padding: 10px 14px;
  min-width: 120px;
}
.dept-stat span {
  display: block;
  font-size: 12px;
  color: var(--erp-text-muted);
}
.dept-stat strong {
  font-size: 22px;
  color: var(--erp-primary);
}
.dept-card {
  border: 1px solid var(--erp-border);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 12px;
  background: #fff;
}
.dept-card-title {
  font-size: 16px;
  font-weight: 700;
}
.dept-card-meta {
  color: var(--erp-text-muted);
  font-size: 13px;
  margin-top: 6px;
}
.dept-card-qty {
  margin-top: 8px;
  font-size: 14px;
}
.dept-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.btn-block {
  flex: 1;
}
.empty-card {
  text-align: center;
  color: var(--erp-text-muted);
  padding: 32px;
  border: 1px dashed var(--erp-border);
  border-radius: 8px;
}
</style>
