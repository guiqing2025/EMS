<template>
  <div class="login-page" :style="{ backgroundImage: `linear-gradient(135deg, rgba(21, 42, 69, 0.88), rgba(37, 99, 235, 0.55)), url(${bgUrl})` }">
    <div class="login-card">
      <img class="login-logo" :src="logoUrl" alt="鼎雄" />
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
import bgUrl from '@/assets/dx-factory-exterior.jpg'

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
