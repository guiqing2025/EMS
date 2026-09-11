<template>
  <div class="login-page">
    <div class="login-card">
      <img class="login-logo" :src="logoUrl" alt="景立创" />
      <div class="login-title">景立创</div>
      <div class="login-sub">销售订单至出货 · ERP</div>
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
  if (loading.value) return
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入账号和密码'
    ElMessage.warning(error.value)
    return
  }
  loading.value = true
  try {
    const data = await auth.login(username.value.trim(), password.value)
    password.value = ''
    if (data.must_change_password) {
      ElMessage.warning('首次登录，请先修改密码')
      await router.replace('/change-password')
      return
    }
    let redirect = (route.query.redirect as string) || defaultHomePath(auth.user)
    if (!route.query.redirect && isEngPushUser(auth.user)) {
      try {
        const cnt = await fetchEngReviewPendingCount()
        if ((cnt.pending || 0) > 0) {
          redirect = '/engineering/material-control'
        }
      } catch {
        /* ignore */
      }
    }
    ElMessage.success('登录成功')
    await router.replace(redirect || '/orders')
  } catch (e) {
    if (e instanceof ApiError) {
      error.value = e.status === 401 ? '账号或密码错误（账号区分大小写，如 WGQ）' : e.message
    } else {
      error.value = e instanceof Error ? e.message : '无法连接服务器，请确认后台服务已启动'
    }
    ElMessage.error(error.value)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(ellipse 80% 60% at 20% 10%, rgba(14, 116, 144, 0.35), transparent 55%),
    radial-gradient(ellipse 70% 50% at 85% 80%, rgba(30, 64, 175, 0.4), transparent 50%),
    linear-gradient(145deg, #0f172a 0%, #1e3a5f 48%, #0e7490 100%);
}
.login-card {
  width: 100%;
  max-width: 400px;
  background: rgba(255, 255, 255, 0.96);
  border-radius: 16px;
  padding: 36px 32px 32px;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.35);
}
.login-logo {
  display: block;
  width: 72px;
  height: auto;
  margin: 0 auto 12px;
}
.login-title {
  text-align: center;
  font-size: 26px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: 0.08em;
}
.login-sub {
  text-align: center;
  margin: 6px 0 24px;
  font-size: 13px;
  color: #64748b;
}
</style>
