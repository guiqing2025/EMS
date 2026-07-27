<template>
  <el-dialog v-model="visible" title="仓库进出账" width="520px" destroy-on-close>
    <el-form label-width="96px">
      <el-form-item label="业务类型" required>
        <el-select v-model="movementType" style="width: 100%" @change="onTypeChange">
          <el-option v-for="t in operationTypes" :key="t.type" :label="t.label" :value="t.type" />
        </el-select>
      </el-form-item>
      <el-form-item label="物料" required>
        <el-select v-model="materialId" filterable placeholder="选择物料" style="width: 100%">
          <el-option
            v-for="m in materials"
            :key="m.id"
            :label="`${m.customer_name} | ${m.material_code} | 库存${m.qty}`"
            :value="m.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="数量" required>
        <el-input-number v-model="qty" :min="0.0001" :precision="4" style="width: 100%" />
      </el-form-item>
      <el-form-item v-if="needsOrder" label="订单号">
        <el-input v-model="orderNo" placeholder="如 3502-260512004" />
      </el-form-item>
      <el-form-item v-if="needsOrder" label="机型">
        <el-input v-model="productModel" placeholder="如 03029209" />
      </el-form-item>
      <el-form-item v-if="needsOrder" label="订单数量">
        <el-input-number v-model="orderQty" :min="0" :precision="0" style="width: 100%" />
      </el-form-item>
      <el-form-item v-if="needsProcess" label="工艺">
        <el-select v-model="process" clearable style="width: 100%">
          <el-option label="SMT" value="smt" />
          <el-option label="DIP" value="dip" />
          <el-option label="SMT+DIP" value="smt+dip" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="needsProcess" label="部门">
        <el-select v-model="department" style="width: 100%">
          <el-option label="SMT" value="smt" />
          <el-option label="DIP" value="dip" />
        </el-select>
      </el-form-item>
      <el-form-item label="单据号">
        <el-input v-model="refNo" placeholder="可选，留空自动生成" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="remark" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">确认提交</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createWarehouseOperation, fetchOperationTypes } from '@/api/warehouse'
import type { WarehouseMaterial } from '@/types/warehouse'

const props = defineProps<{
  modelValue: boolean
  materials: WarehouseMaterial[]
  defaultType?: string
  defaultMaterialId?: number
}>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; saved: [] }>()

const visible = ref(props.modelValue)
const operationTypes = ref<{ type: string; label: string }[]>([])
const movementType = ref('inbound')
const materialId = ref<number | undefined>()
const qty = ref(1)
const orderNo = ref('')
const productModel = ref('')
const orderQty = ref<number | undefined>()
const process = ref('')
const department = ref('smt')
const refNo = ref('')
const remark = ref('')
const saving = ref(false)

const needsOrder = computed(() => ['issue', 'return', 'overissue'].includes(movementType.value))
const needsProcess = computed(() => movementType.value === 'issue')

watch(() => props.modelValue, async (v) => {
  visible.value = v
  if (v) {
    if (!operationTypes.value.length) {
      operationTypes.value = await fetchOperationTypes()
    }
    movementType.value = props.defaultType || 'inbound'
    materialId.value = props.defaultMaterialId ?? props.materials[0]?.id
    qty.value = 1
    orderNo.value = ''
    productModel.value = ''
    orderQty.value = undefined
    process.value = ''
    department.value = 'smt'
    refNo.value = ''
    remark.value = ''
  }
})
watch(visible, (v) => emit('update:modelValue', v))

function onTypeChange() {
  if (!needsProcess.value) department.value = 'smt'
}

async function onSave() {
  if (!materialId.value || !qty.value) {
    ElMessage.error('请选择物料并填写数量')
    return
  }
  saving.value = true
  try {
    await createWarehouseOperation({
      material_id: materialId.value,
      movement_type: movementType.value,
      qty: qty.value,
      order_no: orderNo.value.trim(),
      product_model: productModel.value.trim(),
      order_qty: orderQty.value,
      process: process.value || undefined,
      department: needsProcess.value ? department.value : undefined,
      ref_no: refNo.value.trim(),
      remark: remark.value.trim(),
    })
    ElMessage.success('进出账已提交，库存已更新')
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交失败')
  } finally {
    saving.value = false
  }
}
</script>
