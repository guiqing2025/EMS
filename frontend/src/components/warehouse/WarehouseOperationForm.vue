<template>
  <div class="wh-op-form">
    <div class="wh-op-form-title">录入仓库动作</div>
    <el-form label-width="80px" size="small">
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="业务类型" required>
            <el-select v-model="movementType" style="width: 100%" @change="onTypeChange">
              <el-option v-for="t in operationTypes" :key="t.type" :label="t.label" :value="t.type" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="数量" required>
            <el-input-number v-model="qty" :min="0.0001" :precision="4" style="width: 100%" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item :label="giverLabel" :required="giverRequired">
            <el-input v-model="giver" :placeholder="giverPlaceholder" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item :label="receiverLabel" required>
            <el-input v-model="receiver" :placeholder="receiverPlaceholder" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="提交人">
            <el-input :model-value="operatorName" disabled />
          </el-form-item>
        </el-col>
        <template v-if="needsOrder">
          <el-col :span="12">
            <el-form-item label="订单号">
              <el-input v-model="orderNo" placeholder="如 3502-260512004" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="机型">
              <el-input v-model="productModel" placeholder="如 03029209" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="订单数量">
              <el-input-number v-model="orderQty" :min="0" :precision="0" style="width: 100%" />
            </el-form-item>
          </el-col>
        </template>
        <template v-if="needsProcess">
          <el-col :span="12">
            <el-form-item label="工艺">
              <el-select v-model="process" clearable style="width: 100%">
                <el-option label="SMT" value="smt" />
                <el-option label="DIP" value="dip" />
                <el-option label="SMT+DIP" value="smt+dip" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="部门">
              <el-select v-model="department" style="width: 100%">
                <el-option label="SMT" value="smt" />
                <el-option label="DIP" value="dip" />
              </el-select>
            </el-form-item>
          </el-col>
        </template>
        <el-col :span="12">
          <el-form-item label="单据号">
            <el-input v-model="refNo" placeholder="可选，留空自动生成" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="备注">
            <el-input v-model="remark" placeholder="可选" />
          </el-form-item>
        </el-col>
      </el-row>
      <div class="wh-op-form-actions">
        <el-button type="primary" size="small" :loading="saving" @click="onSave">确认提交</el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createWarehouseOperation, fetchOperationTypes } from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ materialId: number }>()
const emit = defineEmits<{ saved: [] }>()
const auth = useAuthStore()

const operationTypes = ref<{ type: string; label: string }[]>([])
const movementType = ref('inbound')
const qty = ref(1)
const orderNo = ref('')
const productModel = ref('')
const orderQty = ref<number | undefined>()
const process = ref('')
const department = ref('smt')
const refNo = ref('')
const remark = ref('')
const giver = ref('')
const receiver = ref('')
const saving = ref(false)

const operatorName = computed(() => auth.user?.display_name || auth.user?.username || '')

const needsOrder = computed(() => ['issue', 'return', 'overissue'].includes(movementType.value))
const needsProcess = computed(() => movementType.value === 'issue')

const isInboundLike = computed(() => ['inbound', 'return'].includes(movementType.value))
const isIssueLike = computed(() =>
  ['issue', 'overissue', 'smt_loss', 'adjust', 'customer_return'].includes(movementType.value),
)

const giverLabel = computed(() => {
  if (movementType.value === 'customer_return') return '退料人'
  if (isInboundLike.value) return '送货人'
  if (isIssueLike.value) return '发料人'
  return '给方'
})
const receiverLabel = computed(() => {
  if (movementType.value === 'customer_return') return '收方(客户)'
  if (isInboundLike.value) return '接收人'
  if (isIssueLike.value) return '领料人'
  return '收方'
})
const giverPlaceholder = computed(() => {
  if (movementType.value === 'customer_return') return '仓库 / 谁经手退客'
  return isInboundLike.value ? '送货人 / 谁送来的' : '谁发出的'
})
const receiverPlaceholder = computed(() => {
  if (movementType.value === 'customer_return') return '退回客户 / 签收人'
  return isInboundLike.value ? '仓管签收人' : '领料 / 接收人'
})
const giverRequired = computed(() => isInboundLike.value || movementType.value === 'customer_return')

watch(
  () => props.materialId,
  async () => {
    if (!operationTypes.value.length) {
      operationTypes.value = await fetchOperationTypes()
    }
    resetForm()
  },
  { immediate: true },
)

function applyPartyDefaults() {
  const name = operatorName.value
  if (isInboundLike.value) {
    if (!receiver.value) receiver.value = name
  } else if (isIssueLike.value) {
    if (!giver.value) giver.value = name
  } else if (!receiver.value) {
    receiver.value = name
  }
}

function resetForm() {
  movementType.value = 'inbound'
  qty.value = 1
  orderNo.value = ''
  productModel.value = ''
  orderQty.value = undefined
  process.value = ''
  department.value = 'smt'
  refNo.value = ''
  remark.value = ''
  giver.value = ''
  receiver.value = operatorName.value
  applyPartyDefaults()
}

function onTypeChange() {
  if (!needsProcess.value) department.value = 'smt'
  giver.value = ''
  receiver.value = ''
  applyPartyDefaults()
}

async function onSave() {
  if (!props.materialId || !qty.value) {
    ElMessage.error('请填写数量')
    return
  }
  if (giverRequired.value && !giver.value.trim()) {
    ElMessage.error(`请填写${giverLabel.value}`)
    return
  }
  if (!receiver.value.trim()) {
    ElMessage.error(`请填写${receiverLabel.value}`)
    return
  }
  saving.value = true
  try {
    await createWarehouseOperation({
      material_id: props.materialId,
      movement_type: movementType.value,
      qty: qty.value,
      order_no: orderNo.value.trim(),
      product_model: productModel.value.trim(),
      order_qty: orderQty.value,
      process: process.value || undefined,
      department: needsProcess.value ? department.value : undefined,
      ref_no: refNo.value.trim(),
      remark: remark.value.trim(),
      giver: giver.value.trim(),
      receiver: receiver.value.trim(),
    })
    ElMessage.success('已录入，库存已更新')
    resetForm()
    emit('saved')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.wh-op-form {
  background: var(--erp-bg-muted, #f8fafc);
  border: 1px solid var(--erp-border, #e2e8f0);
  border-radius: 8px;
  padding: 12px 12px 4px;
  margin-bottom: 16px;
}
.wh-op-form-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}
.wh-op-form-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 4px;
}
</style>
