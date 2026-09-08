<template>
  <div class="pda-body">
    <div class="pda-banner">
      <div class="row">批次记录查询</div>
      <div class="row">扫 PCBA 板码查出库批次 · 本枪不入库</div>
    </div>
    <p class="pda-hint">扫板上的编码，可查属于哪一批 SH-xxx、何时出库、和同批有哪些板码。也可直接扫批次号。</p>

    <label class="pda-label">板码 / 批次号</label>
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
      placeholder="扫描后自动查询"
      @keyup.enter="onLookup"
    />
    <button type="button" class="pda-btn" :disabled="busy" @click="onLookup">
      {{ busy ? '查询中…' : '查询批次' }}
    </button>

    <div v-if="hit?.shipment" class="pda-card" style="text-align: center">
      <p class="pda-hint" style="margin-top: 0">所属批次</p>
      <p class="box-no-big">{{ hit.shipment.shipment_no }}</p>
      <p class="sub">{{ hit.shipment.status_label }} · 共 {{ hit.batch_total }} 片</p>
      <p class="title">{{ hit.shipment.purchase_no || '—' }}</p>
      <p class="muted">{{ hit.shipment.product_goods_no || '' }} {{ hit.shipment.product_goods_name || '' }}</p>
      <p class="muted">出库 {{ hit.shipment.ship_date || '—' }} · {{ hit.shipment.operator || '—' }}</p>
      <p v-if="hit.scan?.barcode" class="muted">板码 {{ hit.scan.barcode }}</p>
    </div>
    <div v-else-if="hit && hit.message" class="pda-card">
      <p class="muted">{{ hit.message }}</p>
      <p v-if="hit.scan?.barcode" class="muted">板码 {{ hit.scan.barcode }} · 入库 {{ hit.scan.scanned_at || '—' }}</p>
    </div>
    <p v-if="error" class="pda-empty" style="color: #fca5a5">{{ error }}</p>

    <button type="button" class="pda-btn ghost" style="margin-top: 18px" @click="goHome">
      返回 PDA 首页
    </button>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { lookupShipmentRecord, type ShipmentRecordLookup } from '@/api/packing'
import { preloadScanVoice, speakScanMessage } from '@/utils/scanVoice'

const router = useRouter()
const barcode = ref('')
const busy = ref(false)
const error = ref('')
const hit = ref<ShipmentRecordLookup | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)
const focusTimers: number[] = []

function clearFocusTimers() {
  while (focusTimers.length) {
    window.clearTimeout(focusTimers.pop())
  }
}

function focusInput() {
  const el = inputEl.value
  el?.focus()
  el?.select()
}

function scheduleFocus() {
  clearFocusTimers()
  void nextTick(() => {
    focusInput()
    for (const ms of [30, 120, 280]) {
      focusTimers.push(window.setTimeout(focusInput, ms))
    }
  })
}

async function onLookup() {
  const code = barcode.value.trim()
  if (!code || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const data = await lookupShipmentRecord(code)
    hit.value = data
    if (data.shipment) {
      speakScanMessage(`批次 ${data.shipment.shipment_no}`, 'ok')
    } else {
      speakScanMessage(data.message || '尚未出库', 'ok')
    }
    barcode.value = ''
    scheduleFocus()
  } catch (e) {
    hit.value = null
    const msg = e instanceof Error ? e.message : '查询失败'
    error.value = msg
    speakScanMessage(msg, 'err')
    barcode.value = ''
    scheduleFocus()
  } finally {
    busy.value = false
  }
}

function goHome() {
  router.replace({ name: 'pda-home' })
}

onMounted(() => {
  preloadScanVoice()
  scheduleFocus()
})

onBeforeUnmount(() => {
  clearFocusTimers()
})
</script>

<style scoped>
.box-no-big {
  margin: 6px 0 10px;
  font-size: 34px;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: #34d399;
  word-break: break-all;
  line-height: 1.2;
}
</style>
