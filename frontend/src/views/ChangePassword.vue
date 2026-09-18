<template>
  <div class="change-password-page">
    <div class="page-bg">
      <div class="gradient-orb orb-1"></div>
      <div class="gradient-orb orb-2"></div>
      <div class="grid-pattern"></div>
    </div>

    <div class="card-wrapper">
      <div class="brand">
        <div class="brand-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
          </svg>
        </div>
        <h1>修改密码</h1>
        <p>{{ mustChange ? '首次登录（或密码被重置）需要设置新密码' : '设置一个新的登录密码' }}</p>
      </div>

      <el-alert
        v-if="mustChange"
        type="warning"
        :closable="false"
        show-icon
        class="tip-alert"
        title="当前使用的是初始密码或管理员重置的临时密码，请立即修改"
      />

      <div class="card">
        <el-form :model="form" label-position="top" class="pwd-form" @submit.prevent="handleSubmit">
          <el-form-item label="原密码">
            <el-input
              v-model="form.oldPassword"
              type="password"
              placeholder="请输入当前密码"
              size="large"
              show-password
              autocomplete="current-password"
            />
          </el-form-item>

          <el-form-item label="新密码">
            <el-input
              v-model="form.newPassword"
              type="password"
              placeholder="请输入新密码"
              size="large"
              show-password
              autocomplete="new-password"
            />
            <div class="strength-hint">
              <div class="hint-title">密码要求</div>
              <ul>
                <li :class="ruleState.length">至少 8 位字符</li>
                <li :class="ruleState.notWeak">不能是常见弱口令（如 admin123、123456）</li>
                <li :class="ruleState.notPure">不能是纯数字或纯字母</li>
                <li :class="ruleState.different">不能与原密码相同</li>
              </ul>
            </div>
          </el-form-item>

          <el-form-item label="确认新密码">
            <el-input
              v-model="form.confirmPassword"
              type="password"
              placeholder="请再次输入新密码"
              size="large"
              show-password
              autocomplete="new-password"
              @keyup.enter="handleSubmit"
            />
            <div v-if="form.confirmPassword && !rules.match" class="error-hint">两次输入的新密码不一致</div>
          </el-form-item>

          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="submit-btn"
            @click="handleSubmit"
          >
            确认修改
          </el-button>
        </el-form>

        <div class="card-footer">
          <el-link v-if="!mustChange" :underline="false" type="info" @click="router.push('/admin/dashboard')">
            返回工作台
          </el-link>
          <el-link v-else :underline="false" type="info" @click="handleLogout">退出登录</el-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const form = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const mustChange = computed(() => authStore.mustChangePassword)

// 常见弱口令（与后端 utils/validators.py 的 WEAK_PASSWORDS 保持一致）
const WEAK_PASSWORDS = new Set([
  'admin123', 'sales123', 'review123', 'password', '123456', '12345678',
  'qwerty', 'abc123', '111111', '000000', 'admin', 'root', 'test123',
  'password123', 'changeme', 'letmein', 'welcome',
])

const rules = computed(() => ({
  length: form.newPassword.length >= 8,
  notWeak: !!form.newPassword && !WEAK_PASSWORDS.has(form.newPassword.toLowerCase()),
  notPure: !!form.newPassword && !/^\d+$/.test(form.newPassword) && !/^[A-Za-z]+$/.test(form.newPassword),
  different: !!form.newPassword && form.newPassword !== form.oldPassword,
  match: !!form.confirmPassword && form.newPassword === form.confirmPassword,
}))

const ruleState = computed(() => ({
  length: rules.value.length ? 'ok' : '',
  notWeak: rules.value.notWeak ? 'ok' : '',
  notPure: rules.value.notPure ? 'ok' : '',
  different: rules.value.different ? 'ok' : '',
}))

function validate(): string | null {
  if (!form.oldPassword) return '请输入原密码'
  if (!form.newPassword) return '请输入新密码'
  if (form.newPassword.length < 8) return '新密码长度至少 8 位'
  if (!rules.value.notWeak) return '该密码过于常见，请使用更复杂的密码'
  if (!rules.value.notPure) return '密码不能为纯数字或纯字母'
  if (form.newPassword === form.oldPassword) return '新密码不能与原密码相同'
  if (!form.confirmPassword) return '请再次输入新密码'
  if (!rules.value.match) return '两次输入的新密码不一致'
  return null
}

async function handleSubmit() {
  const err = validate()
  if (err) {
    ElMessage.warning(err)
    return
  }
  loading.value = true
  try {
    await api.post('/api/users/change-password', {
      old_password: form.oldPassword,
      new_password: form.newPassword,
    })
    ElMessage.success('密码已修改')
    authStore.clearMustChangePassword()
    // 同步一次用户信息，确保 must_change_password 等字段与后端一致
    await authStore.fetchUser()
    router.push('/admin/dashboard')
  } catch (e: any) {
    const detail = e.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '修改密码失败')
  } finally {
    loading.value = false
  }
}

async function handleLogout() {
  await authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
.change-password-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0f172a;
  position: relative;
  overflow: hidden;
  padding: 40px 16px;
}

.page-bg {
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
  width: 460px;
  height: 460px;
  background: radial-gradient(circle, #6366f1 0%, transparent 70%);
  top: -160px;
  right: -120px;
}

.orb-2 {
  width: 380px;
  height: 380px;
  background: radial-gradient(circle, #8b5cf6 0%, transparent 70%);
  bottom: -120px;
  left: -80px;
}

.grid-pattern {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
  background-size: 60px 60px;
}

.card-wrapper {
  position: relative;
  z-index: 1;
  width: 460px;
  max-width: 100%;
}

.brand {
  color: #fff;
  text-align: center;
  margin-bottom: 24px;
}

.brand-icon {
  width: 48px;
  height: 48px;
  margin: 0 auto 16px;
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #818cf8;
}

.brand h1 {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 6px;
  letter-spacing: -0.3px;
}

.brand p {
  color: #94a3b8;
  font-size: 13px;
  margin: 0;
}

.tip-alert {
  margin-bottom: 16px;
  border-radius: 10px;
}

.card {
  background: #fff;
  border-radius: 18px;
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.05),
    0 25px 50px -12px rgba(0, 0, 0, 0.25);
  padding: 32px;
}

.pwd-form :deep(.el-form-item__label) {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  padding-bottom: 6px;
}

.pwd-form :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 12px;
  box-shadow: 0 0 0 1px #e5e7eb;
  transition: all 0.15s;
}

.pwd-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.strength-hint {
  margin-top: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
  width: 100%;
}

.hint-title {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 6px;
}

.strength-hint ul {
  margin: 0;
  padding-left: 18px;
}

.strength-hint li {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.9;
}

.strength-hint li.ok {
  color: #16a34a;
}

.strength-hint li.ok::marker {
  color: #16a34a;
}

.error-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #ef4444;
  width: 100%;
}

.submit-btn {
  width: 100%;
  height: 46px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  margin-top: 4px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
}

.submit-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
}

.card-footer {
  display: flex;
  justify-content: center;
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px dashed #e5e7eb;
}
</style>
