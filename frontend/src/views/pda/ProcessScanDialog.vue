<template>
  <el-dialog
    :model-value="modelValue"
    :title="`${stationLabel}扫码 · ${purchaseNo || ''}`"
    width="480px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
    @opened="onOpened"
  >
    <p class="hint">{{ hintText }}</p>
    <el-input
      ref="inputRef"
      v-model="barcode"
      placeholder="扫描或输入条码后回车"
      clearable
      size="large"
      @keyup.enter="onSubmit"
    />
    <div v-if="lastMsg" class="last-msg" :class="lastKind">{{ lastMsg }}</div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      <el-button type="primary" :loading="busy" @click="onSubmit">确认</el-button>
    </template>
  </el-dialog>

  <PreOvenAoiConfirmDialog
    v-model="preOvenConfirmOpen"
    :payload="preOvenConfirmPayload"
    @pass="onPreOvenPass"
    @fail="onPreOvenFail"
  />
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { submitProcessScan, type ProcessStation } from '@/api/processScan'
import PreOvenAoiConfirmDialog, {
  type PreOvenConfirmPayload,
} from '@/components/scan/PreOvenAoiConfirmDialog.vue'
import { speakScanMessage, preloadScanVoice } from '@/utils/scanVoice'

const props = defineProps<{
  modelValue: boolean
  station: ProcessStation
  purchaseNo: string
  /** 订单行机型料号：多机型订单必须带上，否则会落到最严默认（卡 AOI） */
  modelCode?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  scanned: [station: ProcessStation]
}>()

const barcode = ref('')
const busy = ref(false)
const lastMsg = ref('')
const lastKind = ref<'ok' | 'warn' | 'err'>('ok')
const preOvenConfirmOpen = ref(false)
const preOvenConfirmPayload = ref<PreOvenConfirmPayload | null>(null)
const pendingScanCode = ref('')
const inputRef = ref<{
  focus?: () => void
  input?: HTMLInputElement
  $el?: HTMLElement
} | null>(null)

const focusTimers: number[] = []

const stationLabel = computed(() => {
  if (props.station === 'plugin') return '插件'
  if (props.station === 'post_solder') return '后焊'
  return '三防'
})

const hintText = computed(() => {
  const model = (props.modelCode || '').trim()
  const modelHint = model ? `（机型 ${model}）` : ''
  if (props.station === 'plugin')
    return `卡控按工序对照${modelHint}：若该机型勾了 SMT-AOI 才须 AOI PASS；已取消则不卡 AOI`
  if (props.station === 'post_solder') return `卡控：须先过插件工序${modelHint}`
  return `卡控：须先后焊；若勾了 ICT 才须 ICT PASS${modelHint}`
})

function clearFocusTimers() {
  while (focusTimers.length) {
    window.clearTimeout(focusTimers.pop())
  }
}

function focusInputOnce() {
  const inst = inputRef.value
  inst?.focus?.()
  const native =
    inst?.input ||
    (inst?.$el?.querySelector?.('input') as HTMLInputElement | null | undefined)
  native?.focus?.()
  native?.select?.()
}

/** 扫完后多次回焦，避开 ElMessage / 按钮抢走焦点 */
function scheduleFocusInput() {
  clearFocusTimers()
  void nextTick(() => {
    focusInputOnce()
    for (const ms of [30, 120, 280]) {
      focusTimers.push(window.setTimeout(focusInputOnce, ms))
    }
  })
}

async function onOpened() {
  barcode.value = ''
  lastMsg.value = ''
  preloadScanVoice()
  scheduleFocusInput()
}

async function onSubmit() {
  if (busy.value) return
  const code = barcode.value.trim()
  if (!code) {
    ElMessage.warning('请扫描条码')
    speakScanMessage('请扫描条码', 'warn')
    scheduleFocusInput()
    return
  }
  busy.value = true
  try {
    const res = await submitProcessScan({
      station: props.station,
      barcode: code,
      purchase_no: props.purchaseNo,
      model_code: (props.modelCode || '').trim() || undefined,
    })
    if (res.status === 'ok') {
      lastKind.value = 'ok'
      lastMsg.value = res.message || '扫码成功'
      ElMessage.success(res.message || '扫码成功')
      speakScanMessage(lastMsg.value, 'ok')
      barcode.value = ''
      emit('scanned', props.station)
    } else if (res.status === 'already_scanned') {
      lastKind.value = 'warn'
      lastMsg.value = res.message || '已扫过'
      ElMessage.warning(res.message || '已扫过')
      speakScanMessage(lastMsg.value, 'warn')
      barcode.value = ''
    } else if (res.pre_oven_confirm_required && res.barcode && props.station === 'post_solder') {
      lastKind.value = 'warn'
      lastMsg.value = res.message || '炉前AOI不良'
      ElMessage.warning(res.message || '炉前AOI不良')
      speakScanMessage(lastMsg.value, 'warn')
      pendingScanCode.value = code
      preOvenConfirmPayload.value = {
        barcode: res.barcode,
        failReason: res.pre_oven_fail_reason,
        failItems: res.pre_oven_fail_items,
        purchaseNo: props.purchaseNo,
        modelCode: props.modelCode,
      }
      preOvenConfirmOpen.value = true
      barcode.value = ''
    } else {
      lastKind.value = 'err'
      lastMsg.value = res.message || '扫码被拦截'
      ElMessage.error(res.message || '扫码被拦截')
      speakScanMessage(lastMsg.value, 'err')
      barcode.value = ''
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : '扫码失败'
    ElMessage.error(msg)
    speakScanMessage(msg, 'err')
  } finally {
    busy.value = false
    scheduleFocusInput()
  }
}

onBeforeUnmount(() => clearFocusTimers())

async function onPreOvenPass(_barcode: string) {
  if (!pendingScanCode.value) return
  barcode.value = pendingScanCode.value
  pendingScanCode.value = ''
  await onSubmit()
}

function onPreOvenFail(_barcode: string, message: string) {
  lastKind.value = 'warn'
  lastMsg.value = message
  pendingScanCode.value = ''
  scheduleFocusInput()
}
</script>

<style scoped>
.hint {
  margin: 0 0 12px;
  color: var(--erp-text-muted, #64748b);
  font-size: 13px;
}
.last-msg {
  margin-top: 12px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
}
.last-msg.ok {
  background: #ecfdf5;
  color: #047857;
}
.last-msg.warn {
  background: #fffbeb;
  color: #b45309;
}
.last-msg.err {
  background: #fef2f2;
  color: #b91c1c;
}
</style>
