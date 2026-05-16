<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="bg-shape bg-shape-1"></div>
      <div class="bg-shape bg-shape-2"></div>
      <div class="bg-shape bg-shape-3"></div>
    </div>
    <div class="login-container">
      <div class="login-brand">
        <div class="brand-icon">
          <el-icon :size="32"><Memo /></el-icon>
        </div>
        <h1>职称服务管理平台</h1>
        <p>内部业务协作与材料审核系统</p>
      </div>
      <el-card class="login-card" :body-style="{ padding: '32px' }">
        <h2 class="login-title">账号登录</h2>
        <el-form :model="form" @submit.prevent="handleLogin" label-position="top">
          <el-form-item label="用户名">
            <el-input v-model="form.username" placeholder="请输入用户名" size="large"
              prefix-icon="User" @keyup.enter="handleLogin" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" type="password" placeholder="请输入密码" size="large"
              prefix-icon="Lock" show-password @keyup.enter="handleLogin" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" size="large" :loading="loading" @click="handleLogin"
              style="width: 100%; margin-top: 8px; border-radius: 10px; height: 44px">
              登 录
            </el-button>
          </el-form-item>
        </el-form>
        <div class="login-accounts">
          <el-divider>测试账号</el-divider>
          <div class="account-list">
            <div class="account-item" @click="fillAccount('admin', 'admin123')">
              <el-tag size="small" type="danger" effect="dark">管理员</el-tag>
              <span>admin / admin123</span>
            </div>
            <div class="account-item" @click="fillAccount('salesman1', 'sales123')">
              <el-tag size="small" type="primary" effect="dark">业务员</el-tag>
              <span>salesman1 / sales123</span>
            </div>
            <div class="account-item" @click="fillAccount('reviewer1', 'review123')">
              <el-tag size="small" type="warning" effect="dark">审核员</el-tag>
              <span>reviewer1 / review123</span>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

function fillAccount(username: string, password: string) {
  form.username = username
  form.password = password
}

async function handleLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.push('/admin/dashboard')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '登录失败')
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
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
  position: relative;
  overflow: hidden;
}
.login-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
}
.bg-shape {
  position: absolute;
  border-radius: 50%;
  opacity: 0.08;
}
.bg-shape-1 {
  width: 600px;
  height: 600px;
  background: #6366f1;
  top: -200px;
  right: -100px;
}
.bg-shape-2 {
  width: 400px;
  height: 400px;
  background: #8b5cf6;
  bottom: -100px;
  left: -50px;
}
.bg-shape-3 {
  width: 200px;
  height: 200px;
  background: #a78bfa;
  top: 40%;
  left: 20%;
}
.login-container {
  display: flex;
  align-items: center;
  gap: 60px;
  z-index: 1;
}
.login-brand {
  color: #fff;
  max-width: 320px;
}
.brand-icon {
  width: 64px;
  height: 64px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  margin-bottom: 24px;
}
.login-brand h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: 1px;
}
.login-brand p {
  color: #94a3b8;
  font-size: 15px;
  margin: 0;
}
.login-card {
  width: 400px;
  border-radius: 16px;
  border: none;
  box-shadow: 0 20px 60px rgba(0,0,0,0.3);
}
.login-title {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 24px;
  text-align: center;
}
.login-accounts {
  margin-top: 4px;
}
.account-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.account-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 13px;
  color: #64748b;
}
.account-item:hover {
  background: #f1f5f9;
  color: #1e293b;
}
.account-item span {
  font-family: monospace;
}
.login-divider {
  text-align: center;
  position: relative;
  margin: 20px 0 16px;
}
.login-divider::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 1px;
  background: #e2e8f0;
}
.login-divider span {
  position: relative;
  background: #fff;
  padding: 0 16px;
  color: #94a3b8;
  font-size: 13px;
}
.apply-link {
  display: block;
  text-decoration: none;
}
@media (max-width: 900px) {
  .login-brand {
    display: none;
  }
}
</style>
