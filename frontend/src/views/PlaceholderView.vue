<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">{{ title }}</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">{{ subtitle }}</p>
        </div>
      </div>
      <div class="erp-page-body" style="text-align: center; padding: 48px 24px">
        <el-empty :description="`${title}模块开发中`">
          <template #image>
            <el-icon :size="64" color="#94a3b8"><Setting /></el-icon>
          </template>
        </el-empty>
        <p style="color: var(--erp-text-muted); max-width: 520px; margin: 0 auto 20px; line-height: 1.7">
          {{ description }}
        </p>
        <el-button type="primary" @click="router.push(homePath)">返回首页</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Setting } from '@element-plus/icons-vue'
import { defaultHomePath } from '@/auth/access'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const homePath = computed(() => defaultHomePath(auth.user))

const module = computed(() => String(route.meta.module || 'quality'))

const metaMap: Record<string, { title: string; subtitle: string; description: string }> = {
  quality: {
    title: '品质管理',
    subtitle: '来料检 / 过程检 / 出货检 / 不良台账',
    description: '品质模块将在第二期开发，与来料入账、包装发货联动。',
  },
  hr: {
    title: '人事管理',
    subtitle: '员工档案 / 考勤 / 计件统计',
    description: '人事模块将在第三期开发，与系统账号、排产产量联动。',
  },
  settings: {
    title: '系统设置',
    subtitle: '同步日志 / 参数配置',
    description: '同步日志与系统参数配置功能后续在本模块补充；订单同步可在「订单列表」页面操作。',
  },
}

const info = computed(() => metaMap[module.value] || metaMap.quality)
const title = computed(() => info.value.title)
const subtitle = computed(() => info.value.subtitle)
const description = computed(() => info.value.description)
</script>
