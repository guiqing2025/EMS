<template>
  <el-dialog v-model="visible" title="手动录单" width="520px" destroy-on-close @closed="emit('closed')">
    <el-form label-width="96px" @submit.prevent="onSave">
      <el-form-item label="客户名称" required>
        <el-input v-model="form.customer_name" placeholder="小客户名称" />
      </el-form-item>
      <el-form-item label="订单号" required>
        <el-input v-model="form.purchase_no" />
      </el-form-item>
      <el-form-item label="行号">
        <el-input v-model="form.purchase_seq" />
      </el-form-item>
      <el-form-item label="PCBA料号">
        <el-input v-model="form.product_goods_no" />
      </el-form-item>
      <el-form-item label="品名">
        <el-input v-model="form.product_goods_name" />
      </el-form-item>
      <el-form-item label="规格">
        <el-input v-model="form.product_spec" />
      </el-form-item>
      <el-form-item label="订单量" required>
        <el-input-number v-model="form.batch_pur_qty" :min="1" style="width: 100%" />
      </el-form-item>
      <el-form-item label="下单日期">
        <el-date-picker v-model="form.purchase_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="交期">
        <el-date-picker v-model="form.expect_arrival_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createManualOrder } from '@/api/orders'
import type { ManualOrderInput } from '@/types/order'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; saved: []; closed: [] }>()

const visible = ref(props.modelValue)
const saving = ref(false)
const today = new Date().toISOString().slice(0, 10)

const form = reactive<ManualOrderInput>({
  customer_name: '',
  purchase_no: '',
  purchase_seq: '1',
  product_goods_no: '',
  product_goods_name: '',
  product_spec: '',
  batch_pur_qty: 1,
  purchase_date: today,
  expect_arrival_date: '',
  remark: '',
})

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) resetForm()
  },
)
watch(visible, (v) => emit('update:modelValue', v))

function resetForm() {
  form.customer_name = ''
  form.purchase_no = ''
  form.purchase_seq = '1'
  form.product_goods_no = ''
  form.product_goods_name = ''
  form.product_spec = ''
  form.batch_pur_qty = 1
  form.purchase_date = today
  form.expect_arrival_date = ''
  form.remark = ''
}

async function onSave() {
  if (!form.customer_name.trim() || !form.purchase_no.trim()) {
    ElMessage.error('请填写客户名称和订单号')
    return
  }
  saving.value = true
  try {
    await createManualOrder({
      ...form,
      customer_name: form.customer_name.trim(),
      purchase_no: form.purchase_no.trim(),
      purchase_seq: form.purchase_seq?.trim() || '1',
    })
    ElMessage.success('手动录单成功')
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}
</script>
