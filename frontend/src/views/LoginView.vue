<template>
  <div class="login-page" :style="{ backgroundImage: `linear-gradient(135deg, rgba(21, 42, 69, 0.88), rgba(37, 99, 235, 0.55)), url(${bgUrl})` }">
    <div class="login-card">
      <img class="login-logo" :src="logoUrl" alt="鼎雄" />
      <div class="login-title">深圳鼎雄电子科技有限公司</div>
      <div class="login-sub">EMS 生产管理系统</div>
      <el-form @submit.prevent="onSubmit">
        <el-form-item>
          <el-input v-model="username" placeholder="登录账号" autocomplete="username" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="登录密码"
            autocomplete="current-password"
            size="large"
            show-password
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
        <p v-if="error" style="color: #dc2626; font-size: 13px; margin-top: 12px; text-align: center">{{ error }}</p>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { defaultHomePath, isEngPushUser } from '@/auth/access'
import { fetchEngReviewPendingCount } from '@/api/engineering'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'
import logoUrl from '@/assets/logo.png'
import bgUrl from '@/assets/dx-factory-exterior.jpg'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

onMounted(async () => {
  if (auth.token && (await auth.checkStatus())) {
    router.replace((route.query.redirect as string) || defaultHomePath(auth.user))
  }
})

async function onSubmit() {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入账号和密码'
    return
  }
  loading.value = true
  try {
    const data = await auth.login(username.value.trim(), password.value)
    password.value = ''
    if (data.must_change_password) {
      ElMessage.warning('首次登录，请先修改密码')
      router.replace('/change-password')
      return
    }
    let redirect = (route.query.redirect as string) || defaultHomePath(auth.user)
    // 工程推送账号：有待办时登录后直达工程页并自动弹待办
    if (!route.query.redirect && isEngPushUser(auth.user)) {
      try {
        const cnt = await fetchEngReviewPendingCount()
        if ((cnt.pending || 0) > 0) {
          redirect = '/engineering?tab=bom&todo=1'
        }
      } catch {
        /* ignore */
      }
    }
    router.replace(redirect)
  } catch (e) {
    if (e instanceof ApiError) {
      error.value = e.status === 401 ? '账号或密码错误' : e.message
    } else {
      error.value = '无法连接服务器，请确认后台服务已启动'
    }
  } finally {
    loading.value = false
  }
}
</script>
