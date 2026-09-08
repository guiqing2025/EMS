<template>
  <div class="floor-body">
    <template v-if="!station">
      <div class="floor-empty">
        尚未选择工位
        <button type="button" class="floor-btn ghost" style="margin-top: 12px" @click="$router.push({ name: 'floor-me' })">
          去选工位
        </button>
      </div>
    </template>

    <template v-else>
      <div class="floor-banner">
        <div>工位：<strong>{{ stationLabel }}</strong></div>
        <div>订单：<strong>{{ order?.purchase_no || '未锁定' }}</strong></div>
        <div>机型：<strong>{{ order?.product_goods_no || '—' }}</strong></div>
        <div v-if="station === 'packing'">
          入库 <strong>{{ pendingQty }}</strong> / 已发 <strong>{{ shippedQty }}</strong>
          <template v-if="currentBox"> · {{ currentBox.box_no }} {{ currentBox.qty }}/{{ currentBox.qty_target }}</template>
        </div>
      </div>

      <p v-if="!order" class="floor-hint">请先在「任务」点选一张工单，或使用盲扫认单。</p>
      <p v-else class="floor-hint">{{ hintText }}</p>

      <div v-if="station === 'packing' && order" class="floor-box-panel">
        <template v-if="currentBox">
          <div class="floor-box-now">{{ currentBox.box_no }} · {{ currentBox.qty }}/{{ currentBox.qty_target }}</div>
          <div class="floor-box-btns">
            <button type="button" class="floor-btn secondary" :disabled="busy || currentBox.qty < 1" @click="onSealBox">
              本箱装完
            </button>
          </div>
        </template>
        <template v-else>
          <label class="floor-label">每箱数量</label>
          <input v-model.number="qtyTarget" class="floor-input" type="number" min="1" style="margin-bottom: 8px" />
          <button type="button" class="floor-btn" :disabled="busy" @click="onOpenBox">确认数量，开始扫码</button>
        </template>
        <p v-if="lastSealedNo && lastSealedPrinted" class="floor-hint">已封 {{ lastSealedNo }}，二维码已打印</p>
        <p v-else-if="lastSealedNo" class="floor-hint">已封 {{ lastSealedNo }}，记录已保留</p>
        <button
          v-if="lastSealedNo && !lastSealedPrinted"
          type="button"
          class="floor-btn secondary"
          style="margin-top: 8px"
          @click="printLastSealed"
        >
          打印上一箱二维码
        </button>
      </div>

      <div v-if="station === 'smt'" style="display: flex; gap: 10px; margin-bottom: 12px">
        <button
          type="button"
          class="floor-btn"
          :class="smtResult === 'PASS' ? 'success' : 'secondary'"
          style="margin: 0"
          @click="smtResult = 'PASS'"
        >
          PASS
        </button>
        <button
          type="button"
          class="floor-btn"
          :class="smtResult === 'FAIL' ? 'warn' : 'secondary'"
          style="margin: 0"
          @click="smtResult = 'FAIL'"
        >
          FAIL
        </button>
      </div>

      <div class="floor-scan-zone">
        <div class="ico">▦</div>
        <div>请扫板号</div>
      </div>

      <input
        ref="inputEl"
        v-model="barcode"
        class="floor-input"
        type="text"
        enterkeyhint="done"
        autocomplete="off"
        autocorrect="off"
        autocapitalize="off"
        spellcheck="false"
        placeholder="扫描条码后回车提交"
        :disabled="!order || busy"
        @keyup.enter="onSubmit"
      />

      <button type="button" class="floor-btn success" :disabled="!order || busy" @click="onSubmit">
        {{ busy ? '提交中…' : station === 'smt' && smtResult === 'FAIL' ? '过站 FAIL' : '过站 PASS' }}
      </button>

      <div v-if="lastMsg" class="floor-result" :class="lastKind">{{ lastMsg }}</div>

      <div v-if="recent.length" class="floor-recent" style="margin-top: 14px">
        <div v-for="(r, i) in recent" :key="i" class="floor-recent-row">
          <span class="bc">{{ r.barcode }}</span>
          <span class="ok">{{ r.ok ? '✓' : '!' }} {{ r.time }}</span>
        </div>
      </div>

      <button type="button" class="floor-btn ghost" style="margin-top: 16px" @click="changeOrder">
        更换订单
      </button>
      <button
        type="button"
        class="floor-btn ghost"
        @click="$router.push({ name: 'pda-resolve', query: { station } })"
      >
        盲扫认单（PDA）
      </button>
    </template>
  </div>

  <PreOvenAoiConfirmDialog
    v-model="preOvenConfirmOpen"
    :payload="preOvenConfirmPayload"
    @pass="onPreOvenPass"
    @fail="onPreOvenFail"
  />
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { submitProcessScan, submitSmtScan, type ProcessStation } from '@/api/processScan'
import PreOvenAoiConfirmDialog, {
  type PreOvenConfirmPayload,
} from '@/components/scan/PreOvenAoiConfirmDialog.vue'
import {
  fetchPackBoxCurrent,
  onBoxLabelPrinted,
  openBoxLabelPrint,
  openPackBox,
  promptNextBoxQty,
  sealPackBox,
  submitScan,
  type PackBoxInfo,
} from '@/api/packing'
import { useAuthStore } from '@/stores/auth'
import { preloadScanVoice, speakScanMessage } from '@/utils/scanVoice'
import {
  PDA_STATION_LABELS,
  clearPdaOrder,
  getPdaOrder,
  getPdaStation,
  setPdaOrder,
  type PdaOrderPick,
  type PdaStation,
} from '@/views/pda/pdaSession'

const router = useRouter()
const auth = useAuthStore()

const station = ref<PdaStation | ''>('')
const order = ref<PdaOrderPick | null>(null)
const barcode = ref('')
const busy = ref(false)
const lastMsg = ref('')
const lastKind = ref<'ok' | 'warn' | 'err'>('ok')
const smtResult = ref<'PASS' | 'FAIL'>('PASS')
const pendingQty = ref(0)
const shippedQty = ref(0)
const qtyTarget = ref(60)
const currentBox = ref<PackBoxInfo | null>(null)
const lastSealedNo = ref('')
const lastSealedPrinted = ref(false)
let stopPrintedWatch: (() => void) | undefined
const inputEl = ref<HTMLInputElement | null>(null)
const recent = ref<Array<{ barcode: string; ok: boolean; time: string }>>([])
const preOvenConfirmOpen = ref(false)
const preOvenConfirmPayload = ref<PreOvenConfirmPayload | null>(null)
const preOvenRescanCode = ref('')

const stationLabel = computed(() => (station.value ? PDA_STATION_LABELS[station.value] : '—'))

const hintText = computed(() => {
  const model = order.value?.product_goods_no || ''
  const modelHint = model ? `（机型 ${model}）` : ''
  if (station.value === 'smt') return `SMT 手工补录${modelHint}`
  if (station.value === 'plugin') return `插件过站${modelHint}`
  if (station.value === 'post_solder') return `后焊过站${modelHint}`
  if (station.value === 'coating') return `三防过站${modelHint}`
  if (station.value === 'packing') return `包装入箱：先设每箱数量再扫板，板码只扫一遍`
  return ''
})

function focusInput() {
  nextTick(() => inputEl.value?.focus())
}

function nowHm() {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function changeOrder() {
  clearPdaOrder()
  order.value = null
  router.push({ name: 'floor-tasks' })
}

async function onSubmit() {
  const code = barcode.value.trim()
  if (!code || busy.value || !order.value || !station.value) return
  busy.value = true
  lastMsg.value = ''
  try {
    const operator = auth.user?.display_name || auth.user?.username || ''
    let msg = ''
    let ok = true
    if (station.value === 'smt') {
      const res = await submitSmtScan({
        barcode: code,
        result: smtResult.value,
        purchase_no: order.value.purchase_no,
        model_code: order.value.product_goods_no,
        operator,
      })
      msg = res.message || (res.status === 'ok' ? 'OK' : res.status)
      ok = res.status === 'ok' || res.status === 'already_scanned' || res.status === 'already_aoi'
      lastKind.value = ok ? (res.status === 'ok' ? 'ok' : 'warn') : 'err'
    } else if (station.value === 'packing') {
      if (!currentBox.value) {
        throw new Error('请先填写每箱数量并点开始扫码')
      }
      const res = await submitScan(order.value.line_key, code, operator)
      msg = res.message || '入库成功'
      ok = true
      lastKind.value = 'ok'
      if (typeof res.pending_ship_qty === 'number') {
        pendingQty.value = res.pending_ship_qty
      } else {
        pendingQty.value += 1
      }
      if (typeof res.shipped_local_qty === 'number') {
        shippedQty.value = res.shipped_local_qty
      }
      if (res.box_sealed && res.box_no) {
        lastMsg.value = msg
        recent.value = [{ barcode: code, ok, time: nowHm() }, ...recent.value].slice(0, 8)
        speakScanMessage('本箱已满', 'ok')
        barcode.value = ''
        busy.value = false
        await afterFloorSealed(res.box_no, Number(res.box_qty_target || qtyTarget.value) || 60)
        focusInput()
        return
      }
      await loadPackBox()
    } else {
      const res = await submitProcessScan({
        station: station.value as ProcessStation,
        barcode: code,
        purchase_no: order.value.purchase_no,
        model_code: order.value.product_goods_no,
        operator,
      })
      if (res.pre_oven_confirm_required && res.barcode && station.value === 'post_solder') {
        msg = res.message || '炉前AOI不良'
        ok = false
        lastKind.value = 'warn'
        preOvenRescanCode.value = code
        preOvenConfirmPayload.value = {
          barcode: res.barcode,
          failReason: res.pre_oven_fail_reason,
          failItems: res.pre_oven_fail_items,
          purchaseNo: order.value.purchase_no,
          modelCode: order.value.product_goods_no || undefined,
        }
        preOvenConfirmOpen.value = true
      } else {
        msg = res.message || res.status
        ok = res.status === 'ok' || res.status === 'already_scanned'
        lastKind.value = ok ? (res.status === 'ok' ? 'ok' : 'warn') : 'err'
      }
    }
    if (!preOvenConfirmOpen.value) {
      lastMsg.value = msg
      recent.value = [{ barcode: code, ok, time: nowHm() }, ...recent.value].slice(0, 8)
      speakScanMessage(msg, ok ? 'ok' : 'err')
    } else {
      lastMsg.value = msg
      speakScanMessage(msg, 'warn')
    }
  } catch (e: any) {
    lastKind.value = 'err'
    lastMsg.value = e?.message || '提交失败'
    recent.value = [{ barcode: code, ok: false, time: nowHm() }, ...recent.value].slice(0, 8)
    speakScanMessage(lastMsg.value, 'err')
  } finally {
    barcode.value = ''
    busy.value = false
    focusInput()
  }
}

async function onPreOvenPass(_barcode: string) {
  if (!preOvenRescanCode.value) return
  barcode.value = preOvenRescanCode.value
  preOvenRescanCode.value = ''
  await onSubmit()
}

function onPreOvenFail(_barcode: string, message: string) {
  lastKind.value = 'warn'
  lastMsg.value = message
  preOvenRescanCode.value = ''
  focusInput()
}

onMounted(() => {
  preloadScanVoice()
  station.value = getPdaStation()
  order.value = getPdaOrder()
  if (order.value) {
    pendingQty.value = Number(order.value.pending_ship_qty || 0)
    shippedQty.value = Number(order.value.shipped_local_qty || 0)
    setPdaOrder(order.value)
  }
  if (station.value === 'packing') void loadPackBox()
  stopPrintedWatch = onBoxLabelPrinted((boxNo) => {
    if (boxNo === lastSealedNo.value) lastSealedPrinted.value = true
  })
  focusInput()
})

onBeforeUnmount(() => {
  stopPrintedWatch?.()
})

async function loadPackBox() {
  if (!order.value?.line_key) {
    currentBox.value = null
    return
  }
  try {
    const st = await fetchPackBoxCurrent(order.value.line_key)
    currentBox.value = st.box
    if (st.box?.qty_target) qtyTarget.value = st.box.qty_target
  } catch {
    currentBox.value = null
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
    focusInput()
  }
}

function printLastSealed() {
  if (lastSealedPrinted.value) return
  if (lastSealedNo.value) openBoxLabelPrint(lastSealedNo.value)
}

async function afterFloorSealed(sealedNo: string, prevTarget: number) {
  lastSealedNo.value = sealedNo
  lastSealedPrinted.value = false
  currentBox.value = null
  lastKind.value = 'ok'
  lastMsg.value = `已封箱 ${sealedNo}，记录已保留`
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
    await afterFloorSealed(sealed.box_no, prevTarget)
  } catch (e: any) {
    lastKind.value = 'err'
    lastMsg.value = e?.message || '封箱失败'
    speakScanMessage(lastMsg.value, 'err')
  } finally {
    busy.value = false
    focusInput()
  }
}
</script>

<style scoped>
.floor-box-panel {
  margin-bottom: 12px;
}
.floor-box-now {
  font-weight: 700;
  margin-bottom: 8px;
}
.floor-box-btns {
  display: flex;
  gap: 8px;
}
.floor-label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
}
</style>
