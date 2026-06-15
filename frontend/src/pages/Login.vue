<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)

async function submit() {
  if (!username.value || !password.value) return
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    router.push('/skus')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-bg">
    <el-card style="width: 380px">
      <h2 style="text-align: center">ProductHub 产品中台</h2>
      <p style="text-align: center; color: var(--el-text-color-secondary)">北京合胜 · 配置选型与报价</p>
      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input v-model="username" placeholder="用户名" size="large" autofocus />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password" type="password" placeholder="密码" size="large"
            show-password @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">
          登 录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-bg {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--ph-brand-700) 0%, var(--ph-brand-500) 100%);
}
</style>
