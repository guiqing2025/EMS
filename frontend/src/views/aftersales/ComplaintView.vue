<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">投诉单</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">可关联销售订单 / 发货单</p>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="open = true">新建</el-button>
        </div>
      </div>
      <div class="erp-page-body">
        <el-table v-loading="loading" :data="rows" border stripe size="small">
          <el-table-column prop="complaint_no" label="单号" width="140" />
          <el-table-column prop="title" label="标题" min-width="160" />
          <el-table-column prop="customer_name" label="客户" width="120" />
          <el-table-column prop="so_no" label="销售订单" width="130" />
          <el-table-column prop="delivery_no" label="发货单" width="130" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'open'" link type="success" @click="onClose(row)">关闭</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
    <el-dialog v-model="open" title="新建投诉单" width="520px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="标题" required><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="客户"><el-input v-model="form.customer_name" /></el-form-item>
        <el-form-item label="销售订单ID"><el-input-number v-model="form.so_id" :min="0" /></el-form-item>
        <el-form-item label="发货单ID"><el-input-number v-model="form.delivery_id" :min="0" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="form.content" type="textarea" :rows="3" /></el-form-item>
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
import { createComplaint, fetchComplaints, setComplaintStatus, type Complaint } from '@/api/aftersales'

const loading = ref(false)
const saving = ref(false)
const open = ref(false)
const rows = ref<Complaint[]>([])
const form = reactive({ title: '', customer_name: '', so_id: undefined as number | undefined, delivery_id: undefined as number | undefined, content: '' })

async function load() {
  loading.value = true
  try {
    rows.value = (await fetchComplaints()).items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onSave() {
  saving.value = true
  try {
    await createComplaint({
      title: form.title,
      customer_name: form.customer_name,
      so_id: form.so_id || undefined,
      delivery_id: form.delivery_id || undefined,
      content: form.content,
    })
    ElMessage.success('已建投诉单')
    open.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  } finally {
    saving.value = false
  }
}

async function onClose(row: Complaint) {
  try {
    await setComplaintStatus(row.id, 'closed')
    ElMessage.success('已关闭')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '失败')
  }
}

onMounted(load)
</script>
