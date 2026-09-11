<template>
  <div class="login-page">
    <div class="login-card">
      <img class="login-logo" :src="logoUrl" alt="景立创" />
      <div class="login-title">修改初始密码</div>
      <div class="login-sub">{{ auth.user?.display_name || auth.user?.username }}，首次登录请设置新密码</div>
      <el-form @submit.prevent="onSubmit">
        <el-form-item>
          <el-input v-model="oldPassword" type="password" placeholder="当前密码" show-password size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="newPassword" type="password" placeholder="新密码（至少 6 位）" show-password size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="confirmPassword" type="password" placeholder="确认新密码" show-password size="large" @keyup.enter="onSubmit" />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onSubmit">
          确认修改
        </el-button>
        <p v-if="error" style="color: #dc2626; font-size: 13px; margin-top: 12px; text-align: center">{{ error }}</p>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { defaultHomePath } from '@/auth/access'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'
import logoUrl from '@/assets/logo.png'

const router = useRouter()
const auth = useAuthStore()

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const error = ref('')

async function onSubmit() {
  error.value = ''
  if (!oldPassword.value || !newPassword.value || !confirmPassword.value) {
    error.value = '请填写完整信息'
    return
  }
  if (newPassword.value.length < 6) {
    error.value = '新密码至少 6 位'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  loading.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    ElMessage.success('密码已修改，请继续使用系统')
    router.replace(defaultHomePath(auth.user))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '修改失败'
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
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}
.login-sub {
  text-align: center;
  margin: 6px 0 24px;
  font-size: 13px;
  color: #64748b;
}
</style>
