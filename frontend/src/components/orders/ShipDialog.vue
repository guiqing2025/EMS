<template>
  <el-dialog v-model="visible" title="出库单确认" width="480px" destroy-on-close @open="onOpen" @closed="emit('closed')">
    <p style="margin: 0 0 12px; color: var(--erp-text-muted)">{{ orderBrief }}</p>
    <el-form label-width="88px">
      <el-form-item label="已入库待出">
        <el-input :model-value="String(pendingQty)" disabled />
      </el-form-item>
      <el-form-item label="出库日期">
        <el-date-picker v-model="shipDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="箱数">
        <el-input-number v-model="boxCount" :min="1" style="width: 100%" />
      </el-form-item>
      <el-form-item label="物流信息">
        <el-input v-model="logistics" placeholder="快递单号等" />
      </el-form-item>
      <el-form-item label="操作员">
        <el-input v-model="operator" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="remark" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onConfirm">确认出库</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmShipment } from '@/api/packing'

const OPERATOR_KEY = 'ems_scan_operator'

const props = defineProps<{
  modelValue: boolean
  lineKey: string
  pendingQty?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  shipped: []
  closed: []
}>()

const visible = ref(props.modelValue)
const pendingQty = ref(0)
const orderBrief = ref('')
const shipDate = ref(new Date().toISOString().slice(0, 10))
const boxCount = ref(1)
const logistics = ref('')
const operator = ref(localStorage.getItem(OPERATOR_KEY) || '')
const remark = ref('')
const submitting = ref(false)

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
  },
)
watch(visible, (v) => emit('update:modelValue', v))

function onOpen() {
  orderBrief.value = `订单行：${props.lineKey}`
  pendingQty.value = props.pendingQty || 0
  shipDate.value = new Date().toISOString().slice(0, 10)
  boxCount.value = 1
  logistics.value = ''
  remark.value = ''
  operator.value = localStorage.getItem(OPERATOR_KEY) || ''
}

async function onConfirm() {
  if (!props.lineKey) return
  if (operator.value.trim()) localStorage.setItem(OPERATOR_KEY, operator.value.trim())
  submitting.value = true
  try {
    const res = await confirmShipment({
      line_key: props.lineKey,
      ship_date: shipDate.value,
      box_count: boxCount.value,
      logistics: logistics.value.trim(),
      remark: remark.value.trim(),
      operator: operator.value.trim(),
    })
    ElMessage.success(`出库成功：${res.shipment_no}，共 ${res.qty} 片`)
    window.open(`/static/ship_print.html?id=${res.id}`, '_blank')
    visible.value = false
    emit('shipped')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '出库失败')
  } finally {
    submitting.value = false
  }
}
</script>
