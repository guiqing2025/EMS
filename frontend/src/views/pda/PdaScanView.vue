<template>
  <!-- 防误触：整屏界面，只保留扫码键过站 + 左滑右解除 -->
  <div v-if="guardOn" class="pda-guard-screen">
    <input
      ref="inputEl"
      v-model="barcode"
      class="pda-guard-hidden-input"
      type="text"
      enterkeyhint="done"
      autocomplete="off"
      autocorrect="off"
      autocapitalize="off"
      spellcheck="false"
      tabindex="0"
      @keyup.enter="onSubmit"
      @blur="onInputBlur"
    />
    <div class="pda-guard-screen-main">
      <div class="pda-guard-screen-title">防误触已开启</div>
      <div class="pda-guard-screen-sub">扫码键可继续过站 · 可揣口袋</div>
      <div class="pda-guard-screen-meta">
        <div>{{ stationLabel }} · {{ order?.purchase_no || '—' }}</div>
        <div>{{ order?.product_goods_no || '—' }}</div>
        <div v-if="station === 'packing'">
          入库 {{ pendingQty }} / 已发 {{ shippedQty }}
          <template v-if="currentBox"> · {{ currentBox.box_no }} {{ currentBox.qty }}/{{ currentBox.qty_target }}</template>
        </div>
        <div v-if="station === 'smt'">SMT {{ smtResult }}</div>
      </div>
      <div v-if="lastMsg" class="pda-result" :class="lastKind">{{ lastMsg }}</div>
      <div v-else class="pda-guard-screen-idle">等待扫码…</div>
    </div>
    <div class="pda-guard-screen-foot">
      <div
        ref="slideTrackEl"
        class="pda-slide-track"
        @pointerdown.prevent="onSlideStart"
        @pointermove.prevent="onSlideMove"
        @pointerup.prevent="onSlideEnd"
        @pointercancel.prevent="onSlideEnd"
      >
        <div class="pda-slide-fill" :style="{ width: slideFillPx + 'px' }" />
        <div class="pda-slide-label">{{ slideLabel }}</div>
        <div class="pda-slide-thumb" :style="{ transform: `translateX(${slideX}px)` }">››</div>
      </div>
    </div>
  </div>

  <div v-else class="pda-body">
    <div class="pda-banner">
      <div class="row">工位：<strong>{{ stationLabel }}</strong></div>
      <div class="row">订单：<strong>{{ order?.purchase_no || '—' }}</strong></div>
      <div class="row">机型：<strong>{{ order?.product_goods_no || '—' }}</strong></div>
      <div v-if="station === 'packing'" class="row">
        入库 <strong>{{ pendingQty }}</strong> / 已发 <strong>{{ shippedQty }}</strong>
      </div>
      <div v-if="station === 'packing' && currentBox" class="row">
        当前箱 <strong>{{ currentBox.box_no }}</strong>
        {{ currentBox.qty }}/{{ currentBox.qty_target }}
      </div>
    </div>

    <p v-if="justLocked" class="pda-result ok">订单已锁定，请再扫一枪过站（认单那枪不算）</p>
    <p class="pda-hint">{{ hintText }}</p>

    <div v-if="station === 'packing'" class="pda-box-panel">
      <template v-if="currentBox">
        <div class="pda-box-now">
          {{ currentBox.box_no }} · {{ currentBox.qty }}/{{ currentBox.qty_target }}
        </div>
        <div class="pda-box-btns">
          <button type="button" class="pda-btn secondary" :disabled="busy || currentBox.qty < 1" @click="onSealBox">
            本箱装完
          </button>
          <button
            v-if="loosePending > 0"
            type="button"
            class="pda-btn secondary"
            :disabled="busy"
            @click="onAbsorbLoose"
          >
            散板并入本箱（{{ loosePending }}）
          </button>
        </div>
      </template>
      <template v-else>
        <label class="pda-label">每箱数量</label>
        <input v-model.number="qtyTarget" class="pda-input" type="number" min="1" />
        <button type="button" class="pda-btn" :disabled="busy" @click="onOpenBox">确认数量，开始扫码</button>
      </template>
      <p v-if="lastSealedNo && lastSealedPrinted" class="pda-hint">已封 {{ lastSealedNo }}，二维码已打印</p>
      <p v-else-if="lastSealedNo" class="pda-hint">已封 {{ lastSealedNo }}，可在下方入箱记录打印二维码</p>
      <button
        v-if="lastSealedNo && !lastSealedPrinted"
        type="button"
        class="pda-btn secondary"
        style="margin-top: 8px"
        @click="printLastSealed"
      >
        打印上一箱二维码
      </button>
      <div v-if="boxRecords.length" class="pda-box-records">
        <div class="pda-label">入箱记录</div>
        <div v-for="b in boxRecords" :key="b.id" class="pda-box-row">
          <span>{{ b.box_no }} · {{ b.qty }}片</span>
          <span v-if="isBoxLabelPrinted(b)" class="pda-hint" style="margin: 0">已打印</span>
          <button
            v-else-if="b.status && b.status !== 'open'"
            type="button"
            class="pda-btn secondary"
            style="margin: 0; padding: 6px 10px; width: auto"
            @click="openBoxLabelPrint(b.box_no)"
          >
            打印
          </button>
        </div>
      </div>
    </div>

    <div v-if="station === 'smt'" style="margin-bottom: 12px">
      <label class="pda-label">SMT 结果</label>
      <div style="display: flex; gap: 10px">
        <button
          type="button"
          class="pda-btn"
          :class="smtResult === 'PASS' ? 'success' : 'secondary'"
          style="margin: 0"
          @click="smtResult = 'PASS'"
        >
          PASS
        </button>
        <button
          type="button"
          class="pda-btn"
          :class="smtResult === 'FAIL' ? 'warn' : 'secondary'"
          style="margin: 0"
          @click="smtResult = 'FAIL'"
        >
          FAIL
        </button>
      </div>
    </div>

    <label class="pda-label">条码</label>
    <input
      ref="inputEl"
      v-model="barcode"
      class="pda-input scan"
      type="text"
      enterkeyhint="done"
      autocomplete="off"
      autocorrect="off"
      autocapitalize="off"
      spellcheck="false"
      placeholder="扫描条码后自动提交"
      @keyup.enter="onSubmit"
    />
    <button type="button" class="pda-btn" :disabled="busy" @click="onSubmit">
      {{ busy ? '提交中…' : '确认扫码' }}
    </button>

    <div v-if="lastMsg" class="pda-result" :class="lastKind">{{ lastMsg }}</div>

    <button type="button" class="pda-btn warn" style="margin-top: 18px" @click="enableGuard">
      打开防误触
    </button>
    <p class="pda-hint">打开后整屏锁定，可揣口袋；扫码键仍可过站。换单/换工位需从左往右滑解除。</p>
    <button v-if="station === 'packing'" type="button" class="pda-btn ghost" @click="goBoxQuery">
      查箱号（扫板码）
    </button>
    <button type="button" class="pda-btn ghost" @click="changeOrder">更换订单</button>
    <button type="button" class="pda-btn ghost" @click="changeStation">更换工位</button>
  </div>

  <PreOvenAoiConfirmDialog
    v-model="preOvenConfirmOpen"
    :payload="preOvenConfirmPayload"
    @pass="onPreOvenPass"
    @fail="onPreOvenFail"
  />
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { submitProcessScan, submitSmtScan, type ProcessScanResult, type ProcessStation } from '@/api/processScan'
import PreOvenAoiConfirmDialog, {
  type PreOvenConfirmPayload,
} from '@/components/scan/PreOvenAoiConfirmDialog.vue'
import {
  fetchPackBoxCurrent,
  absorbLooseIntoBox,
  isBoxLabelPrinted,
  onBoxLabelPrinted,
  openBoxLabelPrint,
  openPackBox,
  promptNextBoxQty,
  sealPackBox,
  submitScan,
  type PackBoxInfo,
} from '@/api/packing'
import { useAuthStore } from '@/stores/auth'
import { speakScanMessage, preloadScanVoice } from '@/utils/scanVoice'
import {
  PDA_STATION_LABELS,
  getPdaGuard,
  getPdaOrder,
  getPdaStation,
  setPdaGuard,
  setPdaOrder,
  type PdaOrderPick,
  type PdaStation,
} from './pdaSession'

const THUMB_SIZE = 56
const UNLOCK_RATIO = 0.85

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const station = ref<PdaStation | ''>('')
const order = ref<PdaOrderPick | null>(null)
const barcode = ref('')
const busy = ref(false)
const preOvenConfirmOpen = ref(false)
const preOvenConfirmPayload = ref<PreOvenConfirmPayload | null>(null)
const preOvenRescanStation = ref<ProcessStation | null>(null)
const lastMsg = ref('')
const lastKind = ref<'ok' | 'warn' | 'err'>('ok')
const justLocked = ref(false)
const smtResult = ref<'PASS' | 'FAIL'>('PASS')
const pendingQty = ref(0)
const shippedQty = ref(0)
const qtyTarget = ref(60)
const currentBox = ref<PackBoxInfo | null>(null)
const boxRecords = ref<PackBoxInfo[]>([])
const lastSealedNo = ref('')
const loosePending = ref(0)
const lastSealedPrinted = computed(() => {
  const no = lastSealedNo.value
  if (!no) return false
  const rec = boxRecords.value.find((b) => b.box_no === no)
  return isBoxLabelPrinted(rec)
})
let stopPrintedWatch: (() => void) | undefined
const inputEl = ref<HTMLInputElement | null>(null)
const slideTrackEl = ref<HTMLElement | null>(null)
const scannedOnce = ref(new Set<string>())
const focusTimers: number[] = []
const guardOn = ref(false)
const slideX = ref(0)
const sliding = ref(false)
let slideMax = 0
let slideStartX = 0
let slideBaseX = 0

const stationLabel = computed(() =>
  station.value ? PDA_STATION_LABELS[station.value] : '—',
)

const hintText = computed(() => {
  const model = order.value?.product_goods_no || ''
  const modelHint = model ? `（机型 ${model}）` : ''
  if (station.value === 'smt') return `SMT 手工补录${modelHint}，须与当前订单机型一致`
  if (station.value === 'plugin') return `插件卡控${modelHint}：按工序对照是否验 AOI`
  if (station.value === 'post_solder') return `后焊卡控：须先过插件${modelHint}`
  if (station.value === 'coating') return `三防卡控：须先后焊；若勾 ICT 则验 ICT${modelHint}`
  if (station.value === 'packing') return `包装入箱：先设每箱数量再扫板，板码只扫一遍`
  return ''
})

const slideFillPx = computed(() => Math.max(THUMB_SIZE, slideX.value + THUMB_SIZE))

const slideLabel = computed(() => {
  if (slideMax > 0 && slideX.value >= slideMax * UNLOCK_RATIO) return '松开即可解除'
  if (sliding.value) return '继续向右滑…'
  return '从左往右滑动解除防误触'
})

function clearFocusTimers() {
  while (focusTimers.length) window.clearTimeout(focusTimers.pop())
}

function scheduleFocus() {
  clearFocusTimers()
  const run = () => {
    const el = inputEl.value
    if (!el) return
    el.focus({ preventScroll: true })
    el.select?.()
  }
  run()
  focusTimers.push(window.setTimeout(run, 80))
  focusTimers.push(window.setTimeout(run, 220))
}

function onInputBlur() {
  if (!guardOn.value) return
  focusTimers.push(window.setTimeout(() => scheduleFocus(), 30))
}

function enableGuard() {
  guardOn.value = true
  setPdaGuard(true)
  resetSlide()
  nextTick(() => scheduleFocus())
}

function disableGuard() {
  resetSlide()
  guardOn.value = false
  setPdaGuard(false)
  nextTick(() => scheduleFocus())
}

watch(guardOn, () => nextTick(() => scheduleFocus()))

function resetSlide() {
  sliding.value = false
  slideX.value = 0
  slideMax = 0
}

function onSlideStart(ev: PointerEvent) {
  const track = slideTrackEl.value
  if (!track) return
  track.setPointerCapture?.(ev.pointerId)
  const w = track.clientWidth
  slideMax = Math.max(0, w - THUMB_SIZE - 8)
  sliding.value = true
  slideStartX = ev.clientX
  slideBaseX = slideX.value
}

function onSlideMove(ev: PointerEvent) {
  if (!sliding.value) return
  const dx = ev.clientX - slideStartX
  slideX.value = Math.max(0, Math.min(slideMax, slideBaseX + dx))
}

function onSlideEnd() {
  if (!sliding.value) return
  const done = slideMax > 0 && slideX.value >= slideMax * UNLOCK_RATIO
  sliding.value = false
  if (done) {
    disableGuard()
    return
  }
  slideX.value = 0
  if (guardOn.value) scheduleFocus()
}

onMounted(async () => {
  station.value = getPdaStation()
  order.value = getPdaOrder()
  if (!station.value || !order.value) {
    router.replace({ name: 'pda-home' })
    return
  }
  justLocked.value = String(route.query.locked || '') === '1'
  pendingQty.value = order.value.pending_ship_qty || 0
  shippedQty.value = order.value.shipped_local_qty || 0
  barcode.value = ''
  guardOn.value = getPdaGuard()
  preloadScanVoice()
  if (station.value === 'packing') await loadPackBox()
  stopPrintedWatch = onBoxLabelPrinted(() => {
    void loadPackBox()
  })
  await nextTick()
  scheduleFocus()
})

onBeforeUnmount(() => {
  clearFocusTimers()
  resetSlide()
  stopPrintedWatch?.()
})

function changeOrder() {
  if (guardOn.value) return
  if (!station.value) {
    router.replace({ name: 'pda-home' })
    return
  }
  router.replace({ name: 'pda-resolve', query: { station: station.value } })
}

function goBoxQuery() {
  if (guardOn.value) return
  router.push({ name: 'pda-box-query' })
}

function changeStation() {
  if (guardOn.value) return
  router.replace({ name: 'pda-home' })
}

async function onSubmit() {
  if (busy.value) return
  const code = barcode.value.trim()
  if (!code) {
    lastKind.value = 'warn'
    lastMsg.value = '请扫描条码'
    speakScanMessage('请扫描条码', 'warn')
    scheduleFocus()
    return
  }
  if (!station.value || !order.value) return
  justLocked.value = false

  if (station.value === 'smt') {
    const key = code.toUpperCase()
    if (scannedOnce.value.has(key)) {
      lastKind.value = 'warn'
      lastMsg.value = '已扫过'
      speakScanMessage('已扫过', 'warn')
      barcode.value = ''
      scheduleFocus()
      return
    }
    scannedOnce.value.add(key)
  }

  busy.value = true
  try {
    if (station.value === 'smt') {
      await doSmt(code)
    } else if (station.value === 'packing') {
      await doPacking(code)
    } else {
      await doProcess(code, station.value)
    }
  } catch (e) {
    if (station.value === 'smt') scannedOnce.value.delete(code.toUpperCase())
    const msg = e instanceof Error ? e.message : '扫码失败'
    lastKind.value = 'err'
    lastMsg.value = msg
    speakScanMessage(msg, 'err')
    barcode.value = ''
  } finally {
    busy.value = false
    scheduleFocus()
  }
}

async function doSmt(code: string) {
  const res = await submitSmtScan({
    barcode: code,
    result: smtResult.value,
    purchase_no: order.value!.purchase_no,
    model_code: order.value!.product_goods_no || '',
  })
  if (res.status === 'ok') {
    lastKind.value = smtResult.value === 'FAIL' ? 'warn' : 'ok'
    lastMsg.value = res.message || '扫码成功'
    speakScanMessage(lastMsg.value, lastKind.value === 'ok' ? 'ok' : 'warn')
  } else if (res.status === 'already_aoi' || res.status === 'already_scanned') {
    lastKind.value = 'warn'
    lastMsg.value = res.message || '已扫过'
    speakScanMessage(lastMsg.value, 'warn')
  } else {
    scannedOnce.value.delete(code.toUpperCase())
    lastKind.value = 'err'
    lastMsg.value = res.message || '扫码被拦截'
    speakScanMessage(lastMsg.value, 'err')
  }
  barcode.value = ''
}

async function doProcess(code: string, st: ProcessStation) {
  const res = await submitProcessScan({
    station: st,
    barcode: code,
    purchase_no: order.value!.purchase_no,
    model_code: order.value!.product_goods_no || undefined,
  })
  if (res.status === 'ok') {
    lastKind.value = 'ok'
    lastMsg.value = res.message || '扫码成功'
    speakScanMessage(lastMsg.value, 'ok')
  } else if (res.status === 'already_scanned') {
    lastKind.value = 'warn'
    lastMsg.value = res.message || '已扫过'
    speakScanMessage(lastMsg.value, 'warn')
  } else if (res.pre_oven_confirm_required && res.barcode && st === 'post_solder') {
    lastKind.value = 'warn'
    lastMsg.value = res.message || '炉前AOI不良'
    speakScanMessage(lastMsg.value, 'warn')
    preOvenConfirmPayload.value = {
      barcode: res.barcode,
      failReason: res.pre_oven_fail_reason,
      failItems: res.pre_oven_fail_items,
      purchaseNo: order.value?.purchase_no,
      modelCode: order.value?.product_goods_no || undefined,
    }
    preOvenRescanStation.value = st
    preOvenConfirmOpen.value = true
  } else {
    lastKind.value = 'err'
    lastMsg.value = res.message || '扫码被拦截'
    speakScanMessage(lastMsg.value, 'err')
  }
  barcode.value = ''
}

async function onPreOvenPass(code: string) {
  const st = preOvenRescanStation.value
  if (!st || !order.value) return
  busy.value = true
  try {
    await doProcess(code, st)
  } finally {
    busy.value = false
    scheduleFocus()
  }
}

function onPreOvenFail(_code: string, message: string) {
  lastKind.value = 'warn'
  lastMsg.value = message
  scheduleFocus()
}

async function loadPackBox() {
  if (!order.value?.line_key) {
    currentBox.value = null
    loosePending.value = 0
    return
  }
  try {
    const st = await fetchPackBoxCurrent(order.value.line_key)
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

async function onOpenBox() {
  if (!order.value?.line_key || busy.value) return
  busy.value = true
  try {
    currentBox.value = await openPackBox(order.value.line_key, Number(qtyTarget.value) || 60)
    lastKind.value = 'ok'
    lastMsg.value = `每箱 ${currentBox.value.qty_target} 片，可以扫板`
    speakScanMessage('可以扫板', 'ok')
  } catch (e: any) {
    lastKind.value = 'err'
    lastMsg.value = e?.message || '确认数量失败'
    speakScanMessage(lastMsg.value, 'err')
  } finally {
    busy.value = false
    scheduleFocus()
  }
}

async function onAbsorbLoose() {
  const box = currentBox.value
  if (!box || busy.value) return
  busy.value = true
  try {
    const res = await absorbLooseIntoBox(box.id)
    const n = Number(res.absorbed || 0)
    lastKind.value = 'ok'
    lastMsg.value = n
      ? `已把 ${n} 片散板并入，现 ${res.qty}/${res.qty_target}`
      : '没有可并入的散板'
    speakScanMessage(lastMsg.value, 'ok')
    await loadPackBox()
    if (res.sealed && res.box_no) {
      await afterPdaSealed(res.box_no, Number(res.qty_target || qtyTarget.value) || 60)
    }
  } catch (e: any) {
    lastKind.value = 'err'
    lastMsg.value = e?.message || '并入失败'
    speakScanMessage(lastMsg.value, 'err')
  } finally {
    busy.value = false
    scheduleFocus()
  }
}

function printLastSealed() {
  const rec = boxRecords.value.find((b) => b.box_no === lastSealedNo.value)
  if (isBoxLabelPrinted(rec)) {
    lastKind.value = 'warn'
    lastMsg.value = '该箱二维码已打印，不能再打'
    return
  }
  if (lastSealedNo.value) openBoxLabelPrint(lastSealedNo.value)
}

async function afterPdaSealed(sealedNo: string, prevTarget: number) {
  lastSealedNo.value = sealedNo
  currentBox.value = null
  lastKind.value = 'ok'
  lastMsg.value = `已封箱 ${sealedNo}，记录已保留，可打印二维码`
  speakScanMessage('本箱已满', 'ok')
  await loadPackBox()
  const next = await promptNextBoxQty(sealedNo, prevTarget)
  if (next && order.value?.line_key) {
    qtyTarget.value = next
    currentBox.value = await openPackBox(order.value.line_key, next)
    lastMsg.value = `已开下一箱 ${currentBox.value.box_no}`
  }
}

async function onSealBox() {
  const box = currentBox.value
  if (!box || busy.value) return
  busy.value = true
  const prevTarget = Number(box.qty_target || qtyTarget.value) || 60
  try {
    const sealed = await sealPackBox(box.id)
    busy.value = false
    await afterPdaSealed(sealed.box_no, prevTarget)
  } catch (e: any) {
    lastKind.value = 'err'
    lastMsg.value = e?.message || '封箱失败'
    speakScanMessage(lastMsg.value, 'err')
  } finally {
    busy.value = false
    scheduleFocus()
  }
}

async function doPacking(code: string) {
  if (!currentBox.value) {
    lastKind.value = 'warn'
    lastMsg.value = '请先填写每箱数量并点开始扫码'
    speakScanMessage('请先设数量', 'warn')
    barcode.value = ''
    return
  }
  const op =
    (auth.user?.display_name || '').trim() || (auth.user?.username || '').trim() || ''
  const res = await submitScan(order.value!.line_key, code, op)
  pendingQty.value = Number(res.pending_ship_qty ?? pendingQty.value)
  shippedQty.value = Number(res.shipped_local_qty ?? shippedQty.value)
  if (res.line_key && order.value && res.line_key !== order.value.line_key) {
    order.value = {
      ...order.value,
      line_key: res.line_key,
      purchase_no: res.purchase_no || order.value.purchase_no,
      product_goods_no: res.product_goods_no || order.value.product_goods_no,
      pending_ship_qty: pendingQty.value,
      shipped_local_qty: shippedQty.value,
    }
    setPdaOrder(order.value)
  }
  barcode.value = ''
  if (res.box_sealed && res.box_no) {
    const prevTarget = Number(res.box_qty_target || qtyTarget.value) || 60
    await afterPdaSealed(res.box_no, prevTarget)
    return
  }
  lastKind.value = 'ok'
  lastMsg.value = res.message || `入库成功 · 待发 ${pendingQty.value}`
  speakScanMessage('入库成功', 'ok')
  await loadPackBox()
}
</script>

<style scoped>
.pda-box-panel {
  margin-bottom: 12px;
}
.pda-box-now {
  font-weight: 700;
  margin-bottom: 8px;
}
.pda-box-btns {
  display: flex;
  gap: 8px;
}
.pda-box-btns .pda-btn {
  margin: 0;
  flex: 1;
}
.pda-box-records {
  margin-top: 10px;
  font-size: 14px;
}
.pda-box-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
</style>
