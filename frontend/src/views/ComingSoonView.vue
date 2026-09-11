<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">{{ title }}</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            按流程图节点建设中 · {{ phaseLabel }}
          </p>
        </div>
        <el-tag type="info">待开发</el-tag>
      </div>
      <div class="erp-page-body" style="max-width: 640px">
        <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 16px">
          本节点已纳入 ERP 菜单骨架，功能将在对应阶段上线。当前请先维护「主数据」。
        </el-alert>
        <p style="line-height: 1.7; color: var(--erp-text-muted); margin: 0 0 16px">{{ description }}</p>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-button type="primary" @click="router.push('/master/customers')">去客户资料</el-button>
          <el-button @click="router.push('/master/suppliers')">去供应商</el-button>
          <el-button @click="router.push(homePath)">返回首页</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { defaultHomePath } from '@/auth/access'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const homePath = computed(() => defaultHomePath(auth.user))

const title = computed(() => String(route.meta.title || '功能建设中'))
const phaseLabel = computed(() => String(route.meta.phase || '后续阶段'))
const description = computed(
  () =>
    String(route.meta.description || '') ||
    `「${title.value}」对齐销售订单至销售出货流程图，将按执行计划分期交付。`,
)
</script>
