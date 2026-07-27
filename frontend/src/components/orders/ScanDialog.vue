<template>
  <el-dialog v-model="visible" title="包装扫码入库" width="520px" destroy-on-close @open="onOpen" @closed="onClosed">
    <p style="margin: 0 0 8px"><strong>{{ orderBrief }}</strong></p>
    <p class="hint">卡控：须已过三防工序。扫码成功即入库，发货请用订单列表「发货」。</p>
    <el-descriptions :column="3" size="small" border style="margin-bottom: 16px">
      <el-descriptions-item label="订单量">{{ orderQty }}</el-descriptions-item>
      <el-descriptions-item label="已入库">{{ pendingQty }}</el-descriptions-item>
      <el-descriptions-item label="已发货">{{ shippedQty }}</el-descriptions-item>
    </el-descriptions>
    <el-form label-width="80px" @submit.prevent="onSubmit">
      <el-form-item label="操作员">
        <el-input :model-value="operatorName" disabled placeholder="当前登录账号" />
      </el-form-item>
      <el-form-item label="条码">
        <el-input
          ref="barcodeRef"
          v-model="barcode"
          placeholder="扫描或输入 PCBA 条码"
          @keyup.enter="onSubmit"
        />
      </el-form-item>
    </el-form>
    <div>
      <div style="font-size: 13px; color: var(--erp-text-muted); margin-bottom: 8px">最近扫码（已入库）</div>
      <ul class="scan-recent-list">
        <li v-if="!recent.length" class="muted">暂无扫码记录</li>
        <li v-for="row in recent" :key="row.id">{{ row.barcode }}</li>
      </ul>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">确认扫码</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { ElInput } from 'element-plus'
import { fetchPendingScans, submitScan } from '@/api/packing'
import type { ScanRecord } from '@/types/order'
import { useAuthStore } from '@/stores/auth'
import { playScanFall, playScanPass, preloadScanVoice } from '@/utils/scanVoice'

const props = defineProps<{
  modelValue: boolean
  lineKey: string
  purchaseNo?: string
  orderQty?: number
  pendingQty?: number
  shippedQty?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  scanned: [pending: number, shipped: number]
  closed: []
}>()

const auth = useAuthStore()
const operatorName = computed(() => auth.user?.display_name || auth.user?.username || '')

const visible = ref(props.modelValue)
const barcode = ref('')
const recent = ref<ScanRecord[]>([])
const submitting = ref(false)
const barcodeRef = ref<InstanceType<typeof ElInput>>()
const focusTimers: number[] = []

const orderBrief = ref('')
const pendingQty = ref(0)
const shippedQty = ref(0)
const orderQty = ref(0)

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
  },
)
watch(visible, (v) => emit('update:modelValue', v))

function clearFocusTimers() {
  while (focusTimers.length) {
    window.clearTimeout(focusTimers.pop())
  }
}

function focusInputOnce() {
  const inst = barcodeRef.value as
    | (InstanceType<typeof ElInput> & { input?: HTMLInputElement; $el?: HTMLElement })
    | undefined
  inst?.focus?.()
  const native =
    inst?.input ||
    (inst?.$el?.querySelector?.('input') as HTMLInputElement | null | undefined)
  native?.focus?.()
  native?.select?.()
}

function scheduleFocusInput() {
  clearFocusTimers()
  void nextTick(() => {
    focusInputOnce()
    for (const ms of [30, 120, 280]) {
      focusTimers.push(window.setTimeout(focusInputOnce, ms))
    }
  })
}

async function onOpen() {
  orderBrief.value = `订单：${props.purchaseNo || props.lineKey}`
  orderQty.value = props.orderQty || 0
  pendingQty.value = props.pendingQty || 0
  shippedQty.value = props.shippedQty || 0
  barcode.value = ''
  preloadScanVoice()
  await loadRecent()
  scheduleFocusInput()
}

function onClosed() {
  clearFocusTimers()
  emit('closed')
}

async function loadRecent() {
  if (!props.lineKey) return
  try {
    recent.value = await fetchPendingScans(props.lineKey)
  } catch {
    recent.value = []
  }
}

async function onSubmit() {
  if (submitting.value) return
  const code = barcode.value.trim()
  if (!code || !props.lineKey) {
    if (code === '' && props.lineKey) playScanFall()
    scheduleFocusInput()
    return
  }
  const operator = operatorName.value.trim()
  if (!operator) {
    ElMessage.warning('未登录账号，无法确认操作员')
    scheduleFocusInput()
    return
  }
  submitting.value = true
  try {
    const res = await submitScan(props.lineKey, code, operator)
    pendingQty.value = res.pending_ship_qty
    shippedQty.value = res.shipped_local_qty
    ElMessage.success(`入库成功 ${res.pending_ship_qty}/${res.order_qty}`)
    playScanPass()
    barcode.value = ''
    await loadRecent()
    emit('scanned', res.pending_ship_qty, res.shipped_local_qty)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '扫码失败')
    playScanFall()
    barcode.value = ''
  } finally {
    submitting.value = false
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
.scan-recent-list {
  list-style: none;
  padding: 0;
  margin: 0;
  max-height: 160px;
  overflow: auto;
  border: 1px solid var(--erp-border);
  border-radius: 6px;
}
.scan-recent-list li {
  padding: 8px 12px;
  border-bottom: 1px solid var(--erp-border);
  font-family: monospace;
  font-size: 13px;
}
.scan-recent-list li:last-child {
  border-bottom: none;
}
.scan-recent-list .muted {
  color: var(--erp-text-muted);
  font-family: inherit;
}
</style>
