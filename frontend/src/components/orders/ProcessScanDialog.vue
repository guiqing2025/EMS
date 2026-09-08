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
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { submitProcessScan, type ProcessStation } from '@/api/processScan'
import { playScanFall, playScanPass, preloadScanVoice } from '@/utils/scanVoice'

const props = defineProps<{
  modelValue: boolean
  station: ProcessStation
  purchaseNo: string
  /** 订单行机型；无贴码登记时写入扫码记录，刷新后数量才能回显 */
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
  if (props.station === 'plugin') return '卡控：须 AOI 已测且 PASS；AOI 不良不可过站'
  if (props.station === 'post_solder') return '卡控：须先过插件工序'
  return '卡控：须先后焊，且 ICT 已测 PASS；ICT 不良不可过站'
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
    playScanFall()
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
      playScanPass()
      barcode.value = ''
      emit('scanned', props.station)
    } else if (res.status === 'already_scanned') {
      lastKind.value = 'warn'
      lastMsg.value = res.message || '已扫过'
      ElMessage.warning(res.message || '已扫过')
      playScanFall()
      barcode.value = ''
    } else {
      lastKind.value = 'err'
      lastMsg.value = res.message || '扫码被拦截'
      ElMessage.error(res.message || '扫码被拦截')
      playScanFall()
      barcode.value = ''
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '扫码失败')
    playScanFall()
  } finally {
    busy.value = false
    scheduleFocusInput()
  }
}

onBeforeUnmount(() => clearFocusTimers())
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
