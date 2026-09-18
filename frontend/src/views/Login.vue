<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="gradient-orb orb-1"></div>
      <div class="gradient-orb orb-2"></div>
      <div class="grid-pattern"></div>
    </div>
    
    <div class="login-container">
      <div class="login-brand">
        <div class="brand-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
            <polyline points="10 9 9 9 8 9"></polyline>
          </svg>
        </div>
        <h1>职称评审管理平台</h1>
        <p>内部业务协作与材料审核系统</p>
      </div>
      
      <div class="login-card">
        <div class="card-header">
          <h2>登录</h2>
          <p>使用您的账号密码登录系统</p>
        </div>
        
        <el-form :model="form" @submit.prevent="handleLogin" label-position="top" class="login-form">
          <el-form-item label="用户名">
            <el-input 
              v-model="form.username" 
              placeholder="请输入用户名" 
              size="large"
              @keyup.enter="handleLogin"
              class="custom-input"
            >
              <template #prefix>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                  <circle cx="12" cy="7" r="4"></circle>
                </svg>
              </template>
            </el-input>
          </el-form-item>
          
          <el-form-item label="密码">
            <el-input 
              v-model="form.password" 
              type="password" 
              placeholder="请输入密码" 
              size="large"
              show-password
              @keyup.enter="handleLogin"
              class="custom-input"
            >
              <template #prefix>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
              </template>
            </el-input>
          </el-form-item>
          
          <el-button 
            type="primary" 
            size="large" 
            :loading="loading" 
            @click="handleLogin"
            class="login-btn"
          >
            登录
          </el-button>
        </el-form>
        
        <div class="progress-entry">
          <span class="progress-entry-text">想了解申报进展？</span>
          <el-link type="primary" :underline="false" @click="router.push('/progress')">查询申报进度</el-link>
        </div>

        <div class="demo-accounts">
          <div class="demo-header">
            <span class="demo-line"></span>
            <span class="demo-label">测试账号</span>
            <span class="demo-line"></span>
          </div>
          <div class="account-grid">
            <button class="account-btn" @click="fillAccount('admin', 'admin123')">
              <span class="account-role admin">管理员</span>
              <span class="account-creds">admin / admin123</span>
            </button>
            <button class="account-btn" @click="fillAccount('salesman1', 'sales123')">
              <span class="account-role salesman">业务员</span>
              <span class="account-creds">salesman1 / sales123</span>
            </button>
            <button class="account-btn" @click="fillAccount('reviewer1', 'review123')">
              <span class="account-role reviewer">审核员</span>
              <span class="account-creds">reviewer1 / review123</span>
            </button>
          </div>
        </div>
      </div>
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
    const data = await authStore.login(form.username, form.password)
    if (data?.user?.must_change_password) {
      ElMessage.warning('首次登录请修改密码')
      router.push('/change-password')
      return
    }
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
  background: #0f172a;
  position: relative;
  overflow: hidden;
}

.login-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.gradient-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.4;
}

.orb-1 {
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, #6366f1 0%, transparent 70%);
  top: -150px;
  right: -100px;
  animation: float 20s ease-in-out infinite;
}

.orb-2 {
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, #8b5cf6 0%, transparent 70%);
  bottom: -100px;
  left: -50px;
  animation: float 25s ease-in-out infinite reverse;
}

.grid-pattern {
  position: absolute;
  inset: 0;
  background-image: 
    linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
  background-size: 60px 60px;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(30px, -30px); }
}

.login-container {
  display: flex;
  align-items: center;
  gap: 80px;
  z-index: 1;
}

.login-brand {
  color: #fff;
  max-width: 340px;
}

.brand-icon {
  width: 56px;
  height: 56px;
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #818cf8;
  margin-bottom: 32px;
}

.login-brand h1 {
  font-size: 32px;
  font-weight: 700;
  margin: 0 0 12px;
  letter-spacing: -0.5px;
  line-height: 1.2;
}

.login-brand p {
  color: #94a3b8;
  font-size: 16px;
  margin: 0;
  line-height: 1.6;
}

.login-card {
  width: 420px;
  background: #fff;
  border-radius: 20px;
  box-shadow: 
    0 0 0 1px rgba(255, 255, 255, 0.05),
    0 25px 50px -12px rgba(0, 0, 0, 0.25);
  padding: 40px;
}

.card-header {
  margin-bottom: 32px;
}

.card-header h2 {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 8px;
  letter-spacing: -0.3px;
}

.card-header p {
  color: #64748b;
  font-size: 14px;
  margin: 0;
}

.login-form :deep(.el-form-item__label) {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  padding-bottom: 6px;
}

.login-form :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 12px;
  box-shadow: 0 0 0 1px #e5e7eb;
  transition: all 0.15s;
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #d1d5db;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
  border-color: transparent;
}

.login-form :deep(.el-input__prefix) {
  color: #94a3b8;
}

.login-btn {
  width: 100%;
  height: 48px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  margin-top: 8px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  transition: all 0.2s;
}

.login-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
}

.login-btn:active {
  transform: translateY(0);
}

.demo-accounts {
  margin-top: 32px;
}

.progress-entry {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px dashed #e5e7eb;
}

.progress-entry-text {
  font-size: 13px;
  color: #94a3b8;
}

.demo-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.demo-line {
  flex: 1;
  height: 1px;
  background: #e5e7eb;
}

.demo-label {
  font-size: 12px;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.account-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.account-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid #f1f5f9;
  border-radius: 10px;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.account-btn:hover {
  background: #f1f5f9;
  border-color: #e2e8f0;
  transform: translateX(4px);
}

.account-role {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}

.account-role.admin {
  background: #fef2f2;
  color: #dc2626;
}

.account-role.salesman {
  background: #eff6ff;
  color: #2563eb;
}

.account-role.reviewer {
  background: #fffbeb;
  color: #d97706;
}

.account-creds {
  font-size: 13px;
  color: #475569;
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
}

@media (max-width: 900px) {
  .login-brand {
    display: none;
  }
  .login-container {
    gap: 0;
  }
}
</style>