<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">生产检查 / QA</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">判定合格后可生成成品入库单</p>
        </div>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="qa_no" label="QA单号" width="150" />
          <el-table-column prop="mo_no" label="生产单" width="140" />
          <el-table-column prop="qty" label="送检" width="80" />
          <el-table-column prop="pass_qty" label="合格" width="80" />
          <el-table-column prop="fail_qty" label="不合格" width="90" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="result" label="结果" width="90" />
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link type="primary" @click="openJudge(row)">判定</el-button>
              <el-button
                v-if="row.status === 'judged' && row.pass_qty > 0"
                link
                type="success"
                @click="onFg(row)"
              >
                生成入库
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="judgeOpen" title="QA 判定" width="400px">
      <el-form label-width="80px">
        <el-form-item label="合格"><el-input-number v-model="passQty" :min="0" /></el-form-item>
        <el-form-item label="不合格"><el-input-number v-model="failQty" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="judgeOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onJudge">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createFgFromQa, fetchQas, judgeQa, type QaDoc } from '@/api/production'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const rows = ref<QaDoc[]>([])
const judgeOpen = ref(false)
const cur = ref<QaDoc | null>(null)
const passQty = ref(0)
const failQty = ref(0)

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchQas()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openJudge(row: QaDoc) {
  cur.value = row
  passQty.value = row.qty
  failQty.value = 0
  judgeOpen.value = true
}

async function onJudge() {
  if (!cur.value) return
  saving.value = true
  try {
    await judgeQa(cur.value.id, passQty.value, failQty.value)
    ElMessage.success('已判定')
    judgeOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onFg(row: QaDoc) {
  try {
    const fg = await createFgFromQa(row.id, false)
    ElMessage.success(`已建入库 ${fg.receipt_no}`)
    await router.push('/production/fg-receipt')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
