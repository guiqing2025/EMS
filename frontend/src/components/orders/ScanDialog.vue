<template>
  <el-dialog v-model="visible" title="包装入箱扫码" width="560px" destroy-on-close @open="onOpen" @closed="onClosed">
    <p style="margin: 0 0 8px"><strong>{{ orderBrief }}</strong></p>
    <p class="hint">先设这一箱装多少，再扫板。没装满要去扫别的板，直接关掉即可，不用封箱；回来到「入箱记录」点「继续入箱」。扫满会再弹窗设下一箱数量。</p>
    <el-descriptions :column="3" size="small" border style="margin-bottom: 12px">
      <el-descriptions-item label="订单量">{{ orderQty }}</el-descriptions-item>
      <el-descriptions-item label="已入库">{{ pendingQty }}</el-descriptions-item>
      <el-descriptions-item label="已发货">{{ shippedQty }}</el-descriptions-item>
    </el-descriptions>
    <p v-if="loosePending > 0" class="hint" style="color:#9a3412">
      已入库 {{ pendingQty }} 片里：本箱 {{ currentBox?.qty || 0 }} 片，另有
      {{ loosePending }} 片是以前入库的散板，没有进这只箱子。
      <el-button
        v-if="currentBox"
        link
        type="primary"
        size="small"
        :loading="absorbing"
        @click="onAbsorbLoose"
      >
        并进当前箱
      </el-button>
    </p>

    <div class="box-panel">
      <div v-if="currentBox" class="box-now">
        <div>
          当前箱 <strong>{{ currentBox.box_no }}</strong>
          <span class="box-progress">{{ currentBox.qty }} / {{ currentBox.qty_target }}</span>
        </div>
        <div class="box-actions">
          <el-button size="small" :disabled="currentBox.qty < 1 || sealing" :loading="sealing" @click="onSeal">
            本箱装完、封箱
          </el-button>
        </div>
      </div>
      <div v-else class="box-open-row">
        <span>每箱数量</span>
        <el-input-number v-model="qtyTarget" :min="1" :max="9999" size="small" controls-position="right" />
        <el-button type="primary" size="small" :loading="opening" @click="onOpenBox">
          确认数量，开始扫码
        </el-button>
      </div>
      <p v-if="lastSealedNo" class="box-sealed-tip">
        已封箱 {{ lastSealedNo }}，记录已保留。请到下方入箱记录打印二维码。
      </p>
    </div>

    <el-form label-width="80px" @submit.prevent="onSubmit">
      <el-form-item label="操作员">
        <el-input :model-value="operatorName" disabled placeholder="当前登录账号" />
      </el-form-item>
      <el-form-item label="条码">
        <el-input
          ref="barcodeRef"
          v-model="barcode"
          :disabled="!currentBox"
          :placeholder="currentBox ? '扫描板码，记入当前箱' : '请先填写每箱数量并点开始扫码'"
          @keyup.enter="onSubmit"
        />
      </el-form-item>
    </el-form>
    <div class="sealed-list">
      <div class="sealed-h">
        本单入箱
        <el-button link type="primary" size="small" @click="goAllRecords">打开批次记录</el-button>
      </div>
      <div v-if="!boxRecords.length" class="muted">还没有入箱记录。扫满或点「本箱装完」后会出现。</div>
      <div v-for="b in boxRecords" :key="b.id" class="sealed-row">
        <span>{{ b.box_no }} · {{ b.qty }}片 · {{ boxStatusText(b.status) }}</span>
        <el-button
          v-if="canResumePackBox(b) && currentBox?.id !== b.id"
          link
          type="primary"
          size="small"
          @click="onResume(b)"
        >
          继续这箱
        </el-button>
        <el-button
          v-if="isBoxLabelPrinted(b)"
          link
          disabled
          size="small"
        >
          已打印
        </el-button>
        <el-button
          v-else-if="b.status && b.status !== 'open'"
          link
          type="primary"
          size="small"
          @click="printBox(b.box_no)"
        >
          打印二维码
        </el-button>
        <span v-else-if="currentBox?.id === b.id" class="muted">当前箱</span>
      </div>
    </div>
    <div>
      <div style="font-size: 13px; color: var(--erp-text-muted); margin-bottom: 8px">本箱 / 最近扫码</div>
      <ul class="scan-recent-list">
        <li v-if="!recent.length" class="muted">暂无扫码记录</li>
        <li v-for="row in recent" :key="row.id">{{ row.barcode }}</li>
      </ul>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" :disabled="!currentBox" :loading="submitting" @click="onSubmit">确认扫码</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { ElInput } from 'element-plus'
import {
  canResumePackBox,
  fetchPackBoxCurrent,
  fetchPendingScans,
  absorbLooseIntoBox,
  isBoxLabelPrinted,
  onBoxLabelPrinted,
  openBoxLabelPrint,
  openPackBox,
  promptNextBoxQty,
  resumePackBox,
  sealPackBox,
  submitScan,
  type PackBoxInfo,
} from '@/api/packing'
import type { ScanRecord } from '@/types/order'
import { useAuthStore } from '@/stores/auth'
import { speakScanMessage, preloadScanVoice } from '@/utils/scanVoice'

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
const router = useRouter()
const operatorName = computed(() => auth.user?.display_name || auth.user?.username || '')
let stopPrintedWatch: (() => void) | undefined

function goAllRecords() {
  visible.value = false
  void router.push('/warehouse/pack-boxes')
}

const visible = ref(props.modelValue)
const barcode = ref('')
const recent = ref<ScanRecord[]>([])
const submitting = ref(false)
const opening = ref(false)
const sealing = ref(false)
const absorbing = ref(false)
const barcodeRef = ref<InstanceType<typeof ElInput>>()
const focusTimers: number[] = []

const orderBrief = ref('')
const pendingQty = ref(0)
const shippedQty = ref(0)
const orderQty = ref(0)
const qtyTarget = ref(60)
const currentBox = ref<PackBoxInfo | null>(null)
const boxRecords = ref<PackBoxInfo[]>([])
const lastSealedNo = ref('')
const loosePending = ref(0)

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
  if (!currentBox.value) return
  clearFocusTimers()
  void nextTick(() => {
    focusInputOnce()
    for (const ms of [30, 120, 280]) {
      focusTimers.push(window.setTimeout(focusInputOnce, ms))
    }
  })
}

function printBox(boxNo?: string | null) {
  if (boxNo) openBoxLabelPrint(boxNo)
}

function boxStatusText(status?: string) {
  const s = (status || '').trim()
  if (s === 'open') return '装箱中'
  if (s === 'sealed') return '已封待发'
  if (s === 'awaiting') return '已发待审'
  if (s === 'shipped') return '已发货'
  return s || '—'
}

async function loadBoxState() {
  if (!props.lineKey) return
  try {
    const st = await fetchPackBoxCurrent(props.lineKey)
    currentBox.value = st.box
    boxRecords.value = st.records || st.sealed_boxes || []
    loosePending.value = Number(st.loose_pending || 0)
    if (st.box?.qty_target) qtyTarget.value = st.box.qty_target
  } catch {
    currentBox.value = null
    boxRecords.value = []
    loosePending.value = 0
  }
}

async function afterBoxSealed(sealedNo: string, prevTarget: number) {
  lastSealedNo.value = sealedNo
  currentBox.value = null
  await loadBoxState()
  const next = await promptNextBoxQty(sealedNo, prevTarget)
  if (next) {
    qtyTarget.value = next
    await onOpenBox()
  }
}

async function onOpen() {
  orderBrief.value = `订单：${props.purchaseNo || props.lineKey}`
  orderQty.value = props.orderQty || 0
  pendingQty.value = props.pendingQty || 0
  shippedQty.value = props.shippedQty || 0
  barcode.value = ''
  lastSealedNo.value = ''
  preloadScanVoice()
  await Promise.all([loadRecent(), loadBoxState()])
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

async function onOpenBox() {
  if (!props.lineKey || opening.value) return
  opening.value = true
  try {
    currentBox.value = await openPackBox(props.lineKey, Number(qtyTarget.value) || 60)
    lastSealedNo.value = ''
    ElMessage.success(`每箱 ${currentBox.value.qty_target} 片，可以开始扫板`)
    scheduleFocusInput()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '确认数量失败')
  } finally {
    opening.value = false
  }
}

async function onSeal() {
  const box = currentBox.value
  if (!box || sealing.value) return
  sealing.value = true
  const prevTarget = Number(box.qty_target || qtyTarget.value) || 60
  try {
    const sealed = await sealPackBox(box.id)
    ElMessage.success(`已封箱 ${sealed.box_no}（${sealed.qty}片），记录已保留`)
    await afterBoxSealed(sealed.box_no, prevTarget)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '封箱失败')
  } finally {
    sealing.value = false
  }
}

async function onResume(row: PackBoxInfo) {
  if (!canResumePackBox(row)) return
  try {
    currentBox.value = await resumePackBox(row.id)
    lastSealedNo.value = ''
    await loadBoxState()
    ElMessage.success(`继续 ${currentBox.value.box_no}，${currentBox.value.qty}/${currentBox.value.qty_target}`)
    scheduleFocusInput()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '无法继续这箱')
  }
}

async function onAbsorbLoose() {
  const box = currentBox.value
  if (!box || absorbing.value) return
  absorbing.value = true
  const prevTarget = Number(box.qty_target || qtyTarget.value) || 60
  try {
    const res = await absorbLooseIntoBox(box.id)
    const n = Number(res.absorbed || 0)
    ElMessage.success(
      n
        ? `已把 ${n} 片散板并入 ${res.box_no}，现 ${res.qty}/${res.qty_target}`
        : '没有可并入的散板',
    )
    await loadBoxState()
    if (res.sealed && res.box_no) {
      await afterBoxSealed(res.box_no, prevTarget)
    } else {
      scheduleFocusInput()
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '并入失败')
  } finally {
    absorbing.value = false
  }
}

async function onSubmit() {
  if (submitting.value) return
  if (!currentBox.value) {
    ElMessage.warning('请先填写每箱数量并点开始扫码')
    speakScanMessage('请先设数量', 'warn')
    return
  }
  const code = barcode.value.trim()
  if (!code || !props.lineKey) {
    if (code === '' && props.lineKey) speakScanMessage('请扫描条码', 'warn')
    scheduleFocusInput()
    return
  }
  const operator = operatorName.value.trim()
  if (!operator) {
    ElMessage.warning('未登录账号，无法确认操作员')
    speakScanMessage('未登录', 'warn')
    scheduleFocusInput()
    return
  }
  submitting.value = true
  try {
    const res = await submitScan(props.lineKey, code, operator)
    pendingQty.value = res.pending_ship_qty
    shippedQty.value = res.shipped_local_qty
    const msg = res.message || `入库成功 ${res.pending_ship_qty}/${res.order_qty}`
    ElMessage.success(msg)
    speakScanMessage(res.box_sealed ? '本箱已满' : '通过', 'ok')
    barcode.value = ''
    if (res.box_sealed && res.box_no) {
      const prevTarget = Number(res.box_qty_target || qtyTarget.value) || 60
      await afterBoxSealed(res.box_no, prevTarget)
    } else if (res.box_id && res.box_no) {
      currentBox.value = {
        id: res.box_id,
        box_no: res.box_no,
        line_key: props.lineKey,
        qty: Number(res.box_qty || 0),
        qty_target: Number(res.box_qty_target || qtyTarget.value),
        status: 'open',
      }
      await loadBoxState()
    }
    await loadRecent()
    emit('scanned', res.pending_ship_qty, res.shipped_local_qty)
  } catch (e) {
    const msg = e instanceof Error ? e.message : '扫码失败'
    ElMessage.error(msg)
    speakScanMessage(msg, 'err')
    barcode.value = ''
  } finally {
    submitting.value = false
    scheduleFocusInput()
  }
}

onMounted(() => {
  stopPrintedWatch = onBoxLabelPrinted(() => {
    void loadBoxState()
  })
})
onBeforeUnmount(() => {
  clearFocusTimers()
  stopPrintedWatch?.()
})
</script>

<style scoped>
.hint {
  margin: 0 0 12px;
  color: var(--erp-text-muted, #64748b);
  font-size: 13px;
}
.box-panel {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--erp-border, #e5e7eb);
  border-radius: 8px;
  background: #f8fafc;
}
.box-now,
.box-open-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.box-progress {
  margin-left: 8px;
  font-weight: 700;
  color: #2563eb;
}
.box-actions {
  display: flex;
  gap: 8px;
}
.box-sealed-tip {
  margin: 8px 0 0;
  font-size: 13px;
  color: #b45309;
}
.sealed-list {
  margin-top: 12px;
  font-size: 13px;
}
.sealed-h {
  color: var(--erp-text-muted, #64748b);
  margin-bottom: 4px;
}
.sealed-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 0;
}
.muted {
  color: var(--erp-text-muted, #64748b);
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
