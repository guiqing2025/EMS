<template>
  <el-dialog v-model="visible" title="发料出库" width="480px" destroy-on-close>
    <el-form label-width="88px">
      <el-form-item label="物料" required>
        <el-select v-model="materialId" filterable placeholder="选择物料" style="width: 100%">
          <el-option
            v-for="m in materials"
            :key="m.id"
            :label="`${m.customer_name} | ${m.material_code} | 可用${m.available_qty}`"
            :value="m.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="数量" required>
        <el-input-number v-model="qty" :min="0.0001" :precision="4" style="width: 100%" />
      </el-form-item>
      <el-form-item label="领料部门" required>
        <el-select v-model="department" style="width: 100%">
          <el-option label="SMT" value="smt" />
          <el-option label="DIP" value="dip" />
        </el-select>
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="remark" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">提交发料</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createIssue } from '@/api/warehouse'
import type { WarehouseMaterial } from '@/types/warehouse'

const props = defineProps<{ modelValue: boolean; materials: WarehouseMaterial[] }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; saved: [] }>()

const visible = ref(props.modelValue)
const materialId = ref<number | undefined>()
const qty = ref(1)
const department = ref('smt')
const remark = ref('')
const saving = ref(false)

watch(() => props.modelValue, (v) => {
  visible.value = v
  if (v) {
    materialId.value = props.materials[0]?.id
    qty.value = 1
    department.value = 'smt'
    remark.value = ''
  }
})
watch(visible, (v) => emit('update:modelValue', v))

async function onSave() {
  if (!materialId.value || !qty.value) {
    ElMessage.error('请填写完整信息')
    return
  }
  saving.value = true
  try {
    await createIssue(materialId.value, qty.value, department.value, remark.value.trim())
    ElMessage.success('发料单已提交，等待部门确认')
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交失败')
  } finally {
    saving.value = false
  }
}
</script>
