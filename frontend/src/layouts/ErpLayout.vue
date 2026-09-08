<template>
  <el-container class="erp-layout">
    <!-- 桌面侧栏 -->
    <el-aside v-show="!isMobile" width="220px" class="erp-aside">
      <div class="erp-brand">
        <img :src="logoUrl" alt="鼎雄" />
        <div class="erp-brand-text">
          <div class="name">鼎雄 EMS</div>
          <div class="sub">生产管理系统</div>
        </div>
      </div>
      <div class="erp-menu-wrap">
        <el-menu
          class="erp-menu"
          :default-active="activeMenu"
          :default-openeds="openMenus"
          router
          background-color="transparent"
          text-color="rgba(255,255,255,0.82)"
          active-text-color="#ffffff"
        >
          <template v-for="item in visibleMenu" :key="item.key">
            <el-sub-menu v-if="item.children?.length" :index="item.key">
              <template #title>
                <span>{{ item.title }}</span>
              </template>
              <el-menu-item
                v-for="child in item.children"
                :key="child.key"
                :index="child.path || child.key"
              >
                <span>{{ child.title }}</span>
                <el-badge
                  v-if="child.key === 'eng-docs' && engPendingCount > 0"
                  :value="engPendingCount"
                  class="eng-menu-badge eng-menu-badge-hot"
                />
                <el-badge
                  v-if="child.key === 'warehouse-finished' && shipPendingCount > 0"
                  :value="shipPendingCount"
                  class="eng-menu-badge eng-menu-badge-hot"
                />
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="item.path || item.key">
              {{ item.title }}
            </el-menu-item>
          </template>
        </el-menu>
      </div>
      <div class="erp-aside-footer">
        <div>{{ userLabel }}</div>
        <div class="erp-build">构建 {{ buildLabel }}</div>
      </div>
    </el-aside>

    <!-- 手机抽屉菜单 -->
    <el-drawer
      v-model="drawerOpen"
      direction="ltr"
      size="78%"
      :with-header="false"
      class="erp-mobile-drawer"
    >
      <div class="erp-aside erp-aside--drawer">
        <div class="erp-brand">
          <img :src="logoUrl" alt="鼎雄" />
          <div class="erp-brand-text">
            <div class="name">鼎雄 EMS</div>
            <div class="sub">生产管理系统</div>
          </div>
        </div>
        <div class="erp-menu-wrap">
          <el-menu
            class="erp-menu"
            :default-active="activeMenu"
            :default-openeds="openMenus"
            router
            background-color="transparent"
            text-color="rgba(255,255,255,0.82)"
            active-text-color="#ffffff"
            @select="drawerOpen = false"
          >
            <template v-for="item in visibleMenu" :key="item.key">
              <el-sub-menu v-if="item.children?.length" :index="item.key">
                <template #title>
                  <span>{{ item.title }}</span>
                </template>
                <el-menu-item
                  v-for="child in item.children"
                  :key="child.key"
                  :index="child.path || child.key"
                >
                  <span>{{ child.title }}</span>
                  <el-badge
                    v-if="child.key === 'warehouse-finished' && shipPendingCount > 0"
                    :value="shipPendingCount"
                    class="eng-menu-badge eng-menu-badge-hot"
                  />
                </el-menu-item>
              </el-sub-menu>
              <el-menu-item v-else :index="item.path || item.key">
                {{ item.title }}
              </el-menu-item>
            </template>
          </el-menu>
        </div>
        <div class="erp-aside-footer">
          <div>{{ userLabel }}</div>
          <div class="erp-build">构建 {{ buildLabel }}</div>
        </div>
      </div>
    </el-drawer>

    <el-container class="erp-main-wrap">
      <el-header class="erp-header">
        <div class="erp-header-left">
          <el-button
            v-if="isMobile"
            class="erp-menu-btn"
            text
            @click="drawerOpen = true"
          >
            菜单
          </el-button>
          <el-breadcrumb v-if="!isMobile" separator="/">
            <el-breadcrumb-item>首页</el-breadcrumb-item>
            <el-breadcrumb-item v-for="(c, i) in breadcrumbs" :key="i">{{ c }}</el-breadcrumb-item>
          </el-breadcrumb>
          <div v-else class="erp-mobile-title">{{ breadcrumbs[breadcrumbs.length - 1] || 'EMS' }}</div>
        </div>
        <div class="erp-header-right">
          <el-badge
            v-if="canSeeShipApprove && shipPendingCount > 0"
            :value="shipPendingCount"
            class="ship-header-badge"
          >
            <el-button type="warning" plain size="small" @click="openShipApprovePage">
              待确认发货
            </el-button>
          </el-badge>
          <el-tag v-if="!isMobile" size="small" type="info">{{ userLabel }}</el-tag>
          <el-button type="danger" plain size="small" @click="onLogout">退出</el-button>
        </div>
      </el-header>
      <div v-if="hubReturnPath" class="erp-hub-return" @click="router.push(hubReturnPath)">
        ← 返回订单工作台
      </div>
      <el-main class="erp-main">
        <router-view />
      </el-main>
    </el-container>

    <el-dialog
      v-model="shipApprovePopupOpen"
      title="待确认发货"
      width="900px"
      :close-on-click-modal="false"
      append-to-body
      @closed="dismissShipApprovePopup"
    >
      <p class="label-popup-lead">
        有 <strong>{{ shipPendingItems.length }}</strong> 单成品发货待确认。
        请 dxgc / dxgc002 / WGQ 审核后才计入已发货。
      </p>
      <el-table :data="shipPendingItems" border size="small" max-height="320">
        <el-table-column prop="shipment_no" label="出库单" min-width="120" show-overflow-tooltip />
        <el-table-column prop="purchase_no" label="订单号" min-width="120" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户" width="100" show-overflow-tooltip />
        <el-table-column prop="qty" label="数量" width="64" align="right" />
        <el-table-column label="装箱" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.pack_note || row.remark || `${row.box_count || 0}箱` }}</template>
        </el-table-column>
        <el-table-column prop="ship_date" label="送货日" width="100" />
        <el-table-column prop="operator" label="制单" width="90" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="dismissShipApprovePopup">稍后</el-button>
        <el-button type="warning" @click="openShipApprovePage">去确认发货</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="labelPopupOpen"
      title="待打印产品标签"
      width="720px"
      :close-on-click-modal="false"
      append-to-body
      @closed="dismissLabelPopup"
    >
      <p class="label-popup-lead">
        有 <strong>{{ labelJobs.length }}</strong> 张送货单待打印标签，共
        <strong>{{ labelBoxTotal }}</strong> 箱。请按装箱信息打印后贴箱。
      </p>
      <el-table :data="labelJobs" border size="small" max-height="320">
        <el-table-column prop="slip_no" label="送货单" min-width="130" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户" width="100" show-overflow-tooltip />
        <el-table-column prop="ship_date" label="日期" width="100" />
        <el-table-column prop="total_qty" label="数量" width="64" align="right" />
        <el-table-column prop="total_boxes" label="箱数" width="64" align="right" />
        <el-table-column prop="operator" label="制单" width="90" show-overflow-tooltip />
        <el-table-column label="" width="72" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openLabelJob(row)">打印</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="dismissLabelPopup">稍后</el-button>
        <el-button type="primary" :disabled="!labelJobs.length" @click="printAllPendingLabels">
          打印全部
        </el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElNotification } from 'element-plus'
import { isEngPushUser, isShipApprover, isShipLabelPopupUser } from '@/auth/access'
import { fetchEngReviewPendingCount } from '@/api/engineering'
import {
  fetchPendingShipApprovals,
  fetchPendingShipLabels,
  type PendingShipApprovalItem,
  type PendingShipLabelJob,
} from '@/api/packing'
import { useAuthStore } from '@/stores/auth'
import { breadcrumbFor, filterMenu, menuTree } from '@/menu'
import logoUrl from '@/assets/logo.png'

const ENG_TODO_AUTO_NAV_KEY = 'eng_todo_auto_nav_v1'
const SHIP_LABEL_POPUP_SEEN_KEY = 'ship_label_popup_seen_v1'
const SHIP_APPROVE_SEEN_KEY = 'ship_approve_seen_v1'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const engPendingCount = ref(0)
let lastEngPending = -1
let engPendingTimer: number | undefined

const shipPendingCount = ref(0)
const shipPendingItems = ref<PendingShipApprovalItem[]>([])
const shipApprovePopupOpen = ref(false)
let lastShipApproveFp = ''
let shipApproveTimer: number | undefined

const labelPopupOpen = ref(false)
const labelJobs = ref<PendingShipLabelJob[]>([])
const labelBoxTotal = computed(() =>
  labelJobs.value.reduce((s, r) => s + Math.max(0, Number(r.total_boxes) || 0), 0),
)
let lastLabelFp = ''
let shipLabelTimer: number | undefined

const drawerOpen = ref(false)
const isMobile = ref(false)

function syncMobile() {
  isMobile.value = window.matchMedia('(max-width: 860px)').matches
  if (!isMobile.value) drawerOpen.value = false
}

const hubReturnPath = computed(() => {
  const raw = String(route.query.return || '').trim()
  if (!raw.startsWith('/orders/hub/')) return ''
  if (route.path.startsWith('/orders/hub/')) return ''
  return raw
})

const canSeeEngPending = computed(() => {
  const role = auth.user?.role
  const name = String(auth.user?.username || '').toLowerCase()
  return (
    role === 'eng_auditor' ||
    role === 'eng_importer' ||
    role === 'admin' ||
    role === 'pmc' ||
    role === 'engineering' ||
    name === 'wgq' ||
    name === 'dxgc' ||
    name === 'dxgc002' ||
    name === 'dxsmt001' ||
    name === 'dx003'
  )
})
const canSeeShipApprove = computed(() => isShipApprover(auth.user))
const engPendingTitle = ref('待处理事项')

const buildLabel = computed(() => {
  const raw = typeof __EMS_BUILD_AT__ === 'string' ? __EMS_BUILD_AT__ : ''
  if (!raw) return '—'
  const m = raw.match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (!m) return raw.slice(0, 16)
  return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`
})

const visibleMenu = computed(() => filterMenu(menuTree, auth.user))
const userLabel = computed(() => {
  const u = auth.user
  if (!u) return ''
  const name = (u.display_name || '').trim()
  const account = (u.username || '').trim()
  if (name && account && name !== account) return `${name}（${account}）`
  return name || account
})
const activeMenu = computed(() => {
  const p = route.path
  if (p.startsWith('/quotation')) return '/quotation'
  if (p.startsWith('/orders/hub/')) return '/orders'
  return p
})
const openMenus = computed(() => {
  const path = route.path
  for (const item of visibleMenu.value) {
    if (!item.children?.length) continue
    const hit = item.children.some(
      (c) => c.path && (path === c.path || path.startsWith(`${c.path}/`)),
    )
    if (hit) return [item.key]
  }
  return []
})
const breadcrumbs = computed(() => {
  const items = breadcrumbFor(route.path)
  return items.length ? items : [String(route.meta.title || '')]
})

function maybeAutoOpenEngTodo(n: number) {
  if (n <= 0 || !isEngPushUser(auth.user)) return
  if (sessionStorage.getItem(ENG_TODO_AUTO_NAV_KEY) === '1') return
  sessionStorage.setItem(ENG_TODO_AUTO_NAV_KEY, '1')
  ElNotification({
    title: engPendingTitle.value,
    message: `您有 ${n} 条待处理事项，已为您打开工程待办`,
    type: 'warning',
    duration: 4500,
  })
  let code = ''
  try {
    const customer = sessionStorage.getItem('eng_last_customer')
    code = customer ? JSON.parse(customer).internal_code || '' : ''
  } catch {
    code = ''
  }
  const query: Record<string, string> = { tab: 'bom', todo: '1' }
  if (code) query.customer = code
  router.push({ path: '/engineering', query })
}

async function refreshEngPending() {
  if (!canSeeEngPending.value) {
    engPendingCount.value = 0
    return
  }
  try {
    const cnt = await fetchEngReviewPendingCount()
    const n = cnt.pending || 0
    engPendingCount.value = n
    engPendingTitle.value = cnt.title || '待处理事项'
    if (lastEngPending >= 0 && n > lastEngPending) {
      maybeAutoOpenEngTodo(n)
    }
    lastEngPending = n
  } catch {
    /* ignore */
  }
}

function startEngPendingPoll() {
  if (engPendingTimer) window.clearInterval(engPendingTimer)
  void refreshEngPending()
  engPendingTimer = window.setInterval(() => void refreshEngPending(), 60000)
}

function labelJobsFingerprint(items: PendingShipLabelJob[]) {
  return items
    .map((x) => x.key || `${x.slip_id || ''}-${x.shipment_id || ''}`)
    .sort()
    .join('|')
}

function openLabelJob(row: PendingShipLabelJob) {
  if (row.slip_id) {
    window.open(`/static/ship_label.html?slip_id=${row.slip_id}`, '_blank')
    return
  }
  if (row.shipment_id) {
    window.open(`/static/ship_label.html?id=${row.shipment_id}`, '_blank')
  }
}

function printAllPendingLabels() {
  window.open('/static/ship_label.html?pending=1', '_blank')
}

function dismissLabelPopup() {
  sessionStorage.setItem(SHIP_LABEL_POPUP_SEEN_KEY, lastLabelFp)
  labelPopupOpen.value = false
}

function dismissShipApprovePopup() {
  sessionStorage.setItem(SHIP_APPROVE_SEEN_KEY, lastShipApproveFp)
  shipApprovePopupOpen.value = false
}

function openShipApprovePage() {
  sessionStorage.setItem(SHIP_APPROVE_SEEN_KEY, lastShipApproveFp || '1')
  shipApprovePopupOpen.value = false
  void router.push({ path: '/warehouse/finished-goods', query: { approve: '1' } })
}

async function refreshShipApprovals() {
  if (!canSeeShipApprove.value) {
    shipPendingCount.value = 0
    shipPendingItems.value = []
    shipApprovePopupOpen.value = false
    return
  }
  try {
    const res = await fetchPendingShipApprovals()
    const items = res.items || []
    const n = items.length
    shipPendingCount.value = n
    shipPendingItems.value = items
    const fp = items
      .map((x) => String(x.id || x.shipment_no || ''))
      .sort()
      .join('|')
    if (!n) {
      lastShipApproveFp = ''
      shipApprovePopupOpen.value = false
      sessionStorage.removeItem(SHIP_APPROVE_SEEN_KEY)
      return
    }
    const onApprovePage = route.path.startsWith('/warehouse/finished-goods')
    if (fp !== lastShipApproveFp && sessionStorage.getItem(SHIP_APPROVE_SEEN_KEY) !== fp) {
      ElNotification({
        title: '待确认发货',
        message: `有 ${n} 单成品发货待确认，请审核后计入已发货`,
        type: 'warning',
        duration: 8000,
        onClick: openShipApprovePage,
      })
      if (!onApprovePage) {
        shipApprovePopupOpen.value = true
      }
    }
    lastShipApproveFp = fp
  } catch {
    /* ignore */
  }
}

function startShipApprovePoll() {
  if (shipApproveTimer) window.clearInterval(shipApproveTimer)
  void refreshShipApprovals()
  shipApproveTimer = window.setInterval(() => void refreshShipApprovals(), 45000)
}

async function refreshShipLabelJobs() {
  if (!isShipLabelPopupUser(auth.user)) {
    labelJobs.value = []
    return
  }
  try {
    const res = await fetchPendingShipLabels()
    const items = res.items || []
    labelJobs.value = items
    const fp = labelJobsFingerprint(items)
    if (!items.length) {
      lastLabelFp = ''
      labelPopupOpen.value = false
      return
    }
    if (fp !== lastLabelFp && sessionStorage.getItem(SHIP_LABEL_POPUP_SEEN_KEY) !== fp) {
      labelPopupOpen.value = true
    }
    lastLabelFp = fp
  } catch {
    /* ignore */
  }
}

function startShipLabelPoll() {
  if (shipLabelTimer) window.clearInterval(shipLabelTimer)
  void refreshShipLabelJobs()
  shipLabelTimer = window.setInterval(() => void refreshShipLabelJobs(), 60000)
}

function onLogout() {
  sessionStorage.removeItem(ENG_TODO_AUTO_NAV_KEY)
  sessionStorage.removeItem('eng_todo_auto_opened_v1')
  sessionStorage.removeItem(SHIP_LABEL_POPUP_SEEN_KEY)
  sessionStorage.removeItem(SHIP_APPROVE_SEEN_KEY)
  auth.logout()
  router.push({ name: 'login' })
}

let engPendingStartTimer: number | undefined

watch(canSeeEngPending, () => {
  if (engPendingStartTimer) window.clearTimeout(engPendingStartTimer)
  // 延后拉待办，避免挡首屏/抢扫码高峰的后端
  engPendingStartTimer = window.setTimeout(() => startEngPendingPoll(), 1800)
}, { immediate: false })
onMounted(() => {
  syncMobile()
  window.addEventListener('resize', syncMobile)
  engPendingStartTimer = window.setTimeout(() => startEngPendingPoll(), 1800)
  window.setTimeout(() => startShipLabelPoll(), 2200)
  window.setTimeout(() => startShipApprovePoll(), 2400)
  // 空闲时预取常用分包，减轻首次点菜单等待
  const scheduleIdle =
    typeof window.requestIdleCallback === 'function'
      ? window.requestIdleCallback.bind(window)
      : (cb: () => void) => window.setTimeout(cb, 1200)
  scheduleIdle(() => {
    void import('@/views/orders/OrdersListView.vue')
    void import('@/views/warehouse/WarehouseView.vue')
    void import('@/views/warehouse/FinishedGoodsView.vue')
    void import('@/views/warehouse/ShipmentRecordsView.vue')
    void import('@/views/laser/LaserRegisterView.vue')
    void import('@/views/DashboardView.vue')
  })
})
onUnmounted(() => {
  window.removeEventListener('resize', syncMobile)
  if (engPendingStartTimer) window.clearTimeout(engPendingStartTimer)
  if (engPendingTimer) window.clearInterval(engPendingTimer)
  if (shipLabelTimer) window.clearInterval(shipLabelTimer)
  if (shipApproveTimer) window.clearInterval(shipApproveTimer)
})
</script>

<style scoped>
.eng-menu-badge {
  margin-left: 8px;
}
.eng-menu-badge :deep(.el-badge__content) {
  position: static;
  transform: none;
}
.eng-menu-badge-hot :deep(.el-badge__content) {
  background-color: #dc2626;
  border: none;
}
.ship-header-badge :deep(.el-badge__content) {
  background-color: #d97706;
  border: none;
  font-weight: 800;
  font-size: 12px;
}
.erp-build {
  margin-top: 4px;
  font-size: 11px;
  opacity: 0.65;
  line-height: 1.2;
}
.erp-mobile-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 52vw;
}
.erp-menu-btn {
  font-weight: 600;
  margin-right: 4px;
}
.erp-aside--drawer {
  height: 100%;
  min-height: 100%;
}
.erp-hub-return {
  flex-shrink: 0;
  padding: 8px 14px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border-bottom: 1px solid #fed7aa;
}
.erp-hub-return:hover {
  background: #ffedd5;
}
.label-popup-lead {
  margin: 0 0 12px;
  font-size: 14px;
  color: #374151;
  line-height: 1.5;
}
</style>
