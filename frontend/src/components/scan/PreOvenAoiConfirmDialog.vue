<template>
  <el-dialog
    v-model="visible"
    title="炉前AOI真不良 · 产线复判"
    width="92%"
    :style="{ maxWidth: '420px' }"
    :close-on-click-modal="false"
    destroy-on-close
    @closed="onClosed"
  >
    <div v-if="payload" class="po-confirm-body">
      <div class="po-row"><strong>条码</strong> {{ payload.barcode }}</div>
      <div v-if="payload.failReason" class="po-row">
        <strong>不良现象</strong> {{ payload.failReason }}
      </div>
      <ul v-if="payload.failItems?.length" class="po-items">
        <li v-for="(it, idx) in payload.failItems" :key="idx">{{ it.label || it.defect_zh }}</li>
      </ul>
      <p class="po-hint">误报选 PASS 放行；确认真不良选 FALL 送维修。</p>
    </div>
    <template #footer>
      <el-button :disabled="busy" @click="visible = false">取消</el-button>
      <el-button type="warning" :loading="busy" @click="onFail">FALL</el-button>
      <el-button type="success" :loading="busy" @click="onPass">PASS</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  confirmPreOvenAoiLine,
  type PreOvenFailItem,
} from '@/api/processScan'
import { speakScanMessage } from '@/utils/scanVoice'

export interface PreOvenConfirmPayload {
  barcode: string
  failReason?: string
  failItems?: PreOvenFailItem[]
  purchaseNo?: string
  modelCode?: string
}

const props = defineProps<{
  modelValue: boolean
  payload: PreOvenConfirmPayload | null
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  pass: [barcode: string]
  fail: [barcode: string, message: string]
}>()

const visible = ref(false)
const busy = ref(false)

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
  },
  { immediate: true },
)

watch(visible, (v) => {
  if (v !== props.modelValue) emit('update:modelValue', v)
})

function onClosed() {
  busy.value = false
}

async function submit(action: 'pass' | 'fail') {
  if (!props.payload?.barcode || busy.value) return
  busy.value = true
  try {
    const res = await confirmPreOvenAoiLine({
      barcode: props.payload.barcode,
      action,
      purchase_no: props.payload.purchaseNo,
      model_code: props.payload.modelCode,
    })
    visible.value = false
    if (action === 'pass') {
      ElMessage.success(res.message || '已复判 PASS')
      speakScanMessage('已复判PASS，请重扫', 'ok')
      emit('pass', props.payload.barcode)
    } else {
      ElMessage.warning(res.message || '已确认真不良')
      speakScanMessage('已确认真不良', 'warn')
      emit('fail', props.payload.barcode, res.message || '已确认真不良')
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : '提交失败'
    ElMessage.error(msg)
    speakScanMessage(msg, 'err')
  } finally {
    busy.value = false
  }
}

function onPass() {
  void submit('pass')
}

function onFail() {
  void submit('fail')
}
</script>

<style scoped>
.po-confirm-body {
  font-size: 14px;
  line-height: 1.65;
}
.po-row {
  margin-bottom: 8px;
}
.po-items {
  margin: 8px 0 12px;
  padding-left: 20px;
  color: var(--el-color-danger);
}
.po-hint {
  margin: 12px 0 0;
  font-size: 13px;
  color: var(--erp-text-muted, #64748b);
}
</style>
