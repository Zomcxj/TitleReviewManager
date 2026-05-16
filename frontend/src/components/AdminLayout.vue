<template>
  <div class="admin-layout">
    <el-container>
      <el-aside width="240px">
        <div class="logo">
          <div class="logo-icon">
            <el-icon :size="24"><Memo /></el-icon>
          </div>
          <div class="logo-text">
            <h3>职称服务管理</h3>
            <span>Title Service</span>
          </div>
        </div>
        <el-menu :default-active="activeMenu" router>
          <el-menu-item index="/admin/dashboard">
            <el-icon><DataBoard /></el-icon>
            <span>工作台</span>
          </el-menu-item>
          <el-menu-item index="/admin/customers">
            <el-icon><UserFilled /></el-icon>
            <span>客户管理</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isSalesman || authStore.isAdmin" index="/admin/registration-links">
            <el-icon><Link /></el-icon>
            <span>注册链接</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isReviewer || authStore.isAdmin" index="/admin/reviews">
            <el-icon><DocumentChecked /></el-icon>
            <span>审核工作台</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/admin/audit-logs">
            <el-icon><List /></el-icon>
            <span>审计日志</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isSalesman || authStore.isAdmin" index="/admin/public-pool">
            <el-icon><Pool /></el-icon>
            <span>公海池</span>
          </el-menu-item>
        </el-menu>
        <div class="user-bar">
          <NotificationBell />
          <el-avatar :size="28" class="user-avatar">
            {{ (authStore.user?.real_name || authStore.user?.username || 'U').charAt(0) }}
          </el-avatar>
          <div class="user-info">
            <div class="user-name">{{ authStore.user?.real_name || authStore.user?.username }}</div>
            <el-tag :type="roleTagType" size="small" effect="dark" round>{{ roleLabel }}</el-tag>
          </div>
          <el-button text class="logout-btn" @click="handleLogout">
            <el-icon><SwitchButton /></el-icon>
          </el-button>
        </div>
      </el-aside>
      <el-container>
        <el-header class="header">
          <span class="page-title">{{ pageTitle }}</span>
        </el-header>
        <el-main>
          <div class="main-content">
            <router-view />
          </div>
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus'
import NotificationBell from './NotificationBell.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const activeMenu = computed(() => route.path)
const pageTitle = computed(() => {
  const map: Record<string, string> = {
    '/admin/dashboard': '工作台',
    '/admin/customers': '客户管理',
    '/admin/registration-links': '专属注册链接',
    '/admin/reviews': '审核工作台',
    '/admin/audit-logs': '审计日志',
    '/admin/public-pool': '客户公海池',
  }
  return map[route.path] || '职称服务管理'
})
const roleLabel = computed(() => {
  const map: Record<string, string> = { admin: '管理员', salesman: '业务员', reviewer: '审核员' }
  return map[authStore.user?.role] || ''
})
const roleTagType = computed(() => {
  const map: Record<string, string> = { admin: 'danger', salesman: 'primary', reviewer: 'warning' }
  return map[authStore.user?.role] || 'info'
})

async function handleLogout() {
  await authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
.admin-layout {
  height: 100vh;
}
.el-aside {
  background: #1a1c2e;
  display: flex;
  flex-direction: column;
}
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 12px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
}
.logo-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.2);
  border-radius: 10px;
  color: #fff;
}
.logo-text h3 {
  color: #fff;
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.logo-text span {
  color: rgba(255,255,255,0.7);
  font-size: 11px;
  letter-spacing: 1px;
}
.el-menu {
  border-right: none;
  background: #1a1c2e;
  flex: 1;
  padding-top: 8px;
}
.el-menu-item {
  color: #a0a4b8;
  margin: 2px 12px;
  border-radius: 10px;
  height: 44px;
}
.el-menu-item:hover {
  background: rgba(99, 102, 241, 0.15);
  color: #c4b5fd;
}
.el-menu-item.is-active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(139, 92, 246, 0.3));
  color: #fff;
}
.user-bar {
  display: flex;
  align-items: center;
  padding: 16px 20px;
  border-top: 1px solid rgba(255,255,255,0.08);
  gap: 10px;
}
.user-avatar {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
}
.user-info {
  flex: 1;
  min-width: 0;
}
.user-name {
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.logout-btn {
  color: #64748b;
  padding: 4px;
}
.logout-btn:hover {
  color: #f87171;
}
.header {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.page-title {
  font-size: 17px;
  font-weight: 600;
  color: #1e293b;
}
.el-container {
  height: 100vh;
}
.el-header {
  height: 56px !important;
  line-height: 56px;
}
.el-main {
  background: #f1f5f9;
  padding: 0;
  overflow-y: auto;
}
.main-content {
  padding: 16px;
  min-height: calc(100vh - 56px);
}
</style>
