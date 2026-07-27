<template>
  <el-container class="erp-layout">
    <el-aside width="220px" class="erp-aside">
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
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="item.path || item.key">
              {{ item.title }}
            </el-menu-item>
          </template>
        </el-menu>
      </div>
      <div class="erp-aside-footer">
        {{ userLabel }}
      </div>
    </el-aside>

    <el-container>
      <el-header class="erp-header">
        <div class="erp-header-left">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>首页</el-breadcrumb-item>
            <el-breadcrumb-item v-for="(c, i) in breadcrumbs" :key="i">{{ c }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="erp-header-right">
          <el-tag size="small" type="info">{{ userLabel }}</el-tag>
          <el-button type="danger" plain size="small" @click="onLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="erp-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElNotification } from 'element-plus'
import { isEngPushUser } from '@/auth/access'
import { fetchEngReviewPendingCount } from '@/api/engineering'
import { useAuthStore } from '@/stores/auth'
import { breadcrumbFor, filterMenu, menuTree } from '@/menu'
import logoUrl from '@/assets/logo.png'

const ENG_TODO_AUTO_NAV_KEY = 'eng_todo_auto_nav_v1'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const engPendingCount = ref(0)
let lastEngPending = -1
let engPendingTimer: number | undefined

const canSeeEngPending = computed(() => {
  const role = auth.user?.role
  const name = String(auth.user?.username || '').toLowerCase()
  // 黄星/王总待审；邱梦林待导入/退回；WGQ/管理员待审
  return (
    role === 'eng_auditor' ||
    role === 'admin' ||
    role === 'engineering' ||
    name === 'wgq' ||
    name === 'dxgc' ||
    name === 'dxsmt001' ||
    name === 'dx003'
  )
})
const engPendingTitle = ref('待处理事项')

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
  return p
})
/** 默认不展开全部；仅展开当前页所属的一级模块 */
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
    duration: 8000,
  })
  const alreadyOpen =
    route.path.startsWith('/engineering') && String(route.query.todo || '') === '1'
  if (!alreadyOpen) goEngPending()
}

async function pollEngPending() {
  if (!canSeeEngPending.value) {
    engPendingCount.value = 0
    return
  }
  try {
    const data = await fetchEngReviewPendingCount()
    const n = Number(data.pending ?? data.unread ?? 0)
    engPendingTitle.value = data.title || '待处理事项'
    if (lastEngPending >= 0 && n > lastEngPending) {
      ElNotification({
        title: engPendingTitle.value,
        message: `有 ${n - lastEngPending} 条新的${engPendingTitle.value}`,
        type: 'warning',
        duration: 6000,
      })
    }
    lastEngPending = n
    engPendingCount.value = n
    maybeAutoOpenEngTodo(n)
  } catch {
    /* 无审核权限或接口暂不可用时忽略 */
  }
}

function startEngPendingPoll() {
  if (engPendingTimer) window.clearInterval(engPendingTimer)
  if (!canSeeEngPending.value) return
  pollEngPending()
  engPendingTimer = window.setInterval(pollEngPending, 30000)
}

function goEngPending() {
  const customer = sessionStorage.getItem('eng_active_customer_v1')
  let code = ''
  try {
    code = customer ? (JSON.parse(customer).internal_code || '') : ''
  } catch {
    code = ''
  }
  const query: Record<string, string> = { tab: 'bom', todo: '1' }
  if (code) query.customer = code
  router.push({ path: '/engineering', query })
}

function onLogout() {
  sessionStorage.removeItem(ENG_TODO_AUTO_NAV_KEY)
  sessionStorage.removeItem('eng_todo_auto_opened_v1')
  auth.logout()
  router.push({ name: 'login' })
}

watch(canSeeEngPending, () => startEngPendingPoll(), { immediate: false })
onMounted(() => startEngPendingPoll())
onUnmounted(() => {
  if (engPendingTimer) window.clearInterval(engPendingTimer)
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
  font-weight: 800;
  font-size: 12px;
}
</style>
