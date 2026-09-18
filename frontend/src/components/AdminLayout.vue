<template>
  <div class="admin-layout">
    <el-container>
      <el-aside :width="sidebarCollapsed ? '64px' : '260px'" class="sidebar">
        <div class="logo" :class="{ collapsed: sidebarCollapsed }">
          <div class="logo-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
          </div>
          <div class="logo-text" v-show="!sidebarCollapsed">
            <span class="logo-title">职称评审</span>
            <span class="logo-subtitle">管理系统</span>
          </div>
        </div>
        
        <el-menu :default-active="activeMenu" :collapse="sidebarCollapsed" :collapse-transition="false" class="nav-menu" @select="handleMenuSelect">
          <el-menu-item index="/admin/dashboard" class="nav-item">
            <el-icon><DataBoard /></el-icon>
            <span>工作台</span>
          </el-menu-item>
          <el-menu-item index="/admin/customers" class="nav-item">
            <el-icon><UserFilled /></el-icon>
            <span>客户管理</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isSalesman || authStore.isAdmin" index="/admin/public-pool" class="nav-item">
            <el-icon><Grid /></el-icon>
            <span>公海池</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isSalesman || authStore.isAdmin" index="/admin/registration-links" class="nav-item">
            <el-icon><Link /></el-icon>
            <span>注册链接</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isReviewer || authStore.isAdmin" index="/admin/reviews" class="nav-item">
            <el-icon><DocumentChecked /></el-icon>
            <span>审核工作台</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/admin/users" class="nav-item">
            <el-icon><User /></el-icon>
            <span>用户管理</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/admin/audit-logs" class="nav-item">
            <el-icon><List /></el-icon>
            <span>审计日志</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isSalesman || authStore.isAdmin" index="/admin/import" class="nav-item">
            <el-icon><Upload /></el-icon>
            <span>批量导入</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/admin/transfer" class="nav-item">
            <el-icon><Switch /></el-icon>
            <span>客户转让</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isSalesman || authStore.isAdmin" index="/admin/finance" class="nav-item">
            <el-icon><Money /></el-icon>
            <span>收费管理</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/admin/system-config" class="nav-item">
            <el-icon><Setting /></el-icon>
            <span>系统配置</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/admin/recycle-bin" class="nav-item">
            <el-icon><Delete /></el-icon>
            <span>回收站</span>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/admin/backup" class="nav-item">
            <el-icon><Download /></el-icon>
            <span>数据备份</span>
          </el-menu-item>
        </el-menu>
        
        <div class="user-bar">
          <div class="user-bar-left">
            <button class="collapse-btn" @click="sidebarCollapsed = !sidebarCollapsed">
              <svg v-if="!sidebarCollapsed" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="11 17 6 12 11 7"></polyline>
                <polyline points="18 17 13 12 18 7"></polyline>
              </svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </button>
          </div>
          <div class="user-bar-right" v-if="!sidebarCollapsed">
            <NotificationBell />
            <div class="user-avatar">
              {{ (authStore.user?.real_name || authStore.user?.username || 'U').charAt(0) }}
            </div>
            <div class="user-info">
              <div class="user-name">{{ authStore.user?.real_name || authStore.user?.username }}</div>
              <div class="user-role">{{ roleLabel }}</div>
            </div>
            <button class="logout-btn" @click="handleLogout" title="退出登录">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                <polyline points="16 17 21 12 16 7"></polyline>
                <line x1="21" y1="12" x2="9" y2="12"></line>
              </svg>
            </button>
          </div>
        </div>
      </el-aside>
      
      <el-container>
        <el-header class="header">
          <div class="header-content">
            <h1 class="page-title">{{ pageTitle }}</h1>
            <div class="header-actions">
              <button class="header-action-btn" title="修改密码" @click="router.push('/change-password')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
                <span>修改密码</span>
              </button>
            </div>
          </div>
        </el-header>
        <el-main class="main-area">
          <div class="main-content">
            <router-view :key="$route.fullPath" />
          </div>
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus'
import NotificationBell from './NotificationBell.vue'
import {
  DataBoard,
  UserFilled,
  Link,
  DocumentChecked,
  User,
  List,
  Upload,
  Switch,
  Grid,
  Money,
  Setting,
  Delete,
  Download,
} from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const sidebarCollapsed = ref(false)

const activeMenu = computed(() => route.path)
const pageTitle = computed(() => {
  const map: Record<string, string> = {
    '/admin/dashboard': '工作台',
    '/admin/customers': '客户管理',
    '/admin/public-pool': '客户公海池',
    '/admin/registration-links': '注册链接管理',
    '/admin/reviews': '审核工作台',
    '/admin/users': '用户管理',
    '/admin/audit-logs': '审计日志',
    '/admin/import': '批量导入',
    '/admin/transfer': '客户转让',
    '/admin/finance': '收费与证书管理',
    '/admin/system-config': '系统配置',
    '/admin/recycle-bin': '回收站',
    '/admin/backup': '数据备份',
  }
  return map[route.path] || '职称评审管理系统'
})
const roleLabel = computed(() => {
  if (!authStore.user) return ''
  const map: Record<string, string> = { admin: '管理员', salesman: '业务员', reviewer: '审核员' }
  return map[authStore.user.role] || ''
})

async function handleLogout() {
  await authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

function handleMenuSelect(index: string) {
  router.push(index)
}
</script>

<style scoped>
.admin-layout {
  height: 100vh;
  background: #f8fafc;
}

.sidebar {
  background: #0f172a;
  display: flex;
  flex-direction: column;
  transition: width 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
}

.logo {
  height: 68px;
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 14px;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  transition: padding 0.2s;
  flex-shrink: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.logo.collapsed {
  padding: 0 22px;
  justify-content: center;
}

.logo-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(99, 102, 241, 0.15);
  border-radius: 10px;
  color: #818cf8;
  flex-shrink: 0;
  transition: all 0.2s;
}

.logo:hover .logo-icon {
  background: rgba(99, 102, 241, 0.25);
  transform: scale(1.05);
}

.logo-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.logo-title {
  color: #f1f5f9;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.3px;
  white-space: nowrap;
}

.logo-subtitle {
  color: #64748b;
  font-size: 11px;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.nav-menu {
  border-right: none;
  background: transparent;
  flex: 1;
  padding: 12px 8px;
  overflow-y: auto;
}

.nav-menu .nav-item {
  color: #94a3b8;
  margin: 2px 0;
  border-radius: 8px;
  height: 44px;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 450;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
}

.nav-menu .nav-item .el-icon {
  margin-right: 12px;
  font-size: 18px;
  display: flex;
  align-items: center;
}

.nav-menu .nav-item:hover {
  background: rgba(99, 102, 241, 0.1);
  color: #e2e8f0;
}

.nav-menu .nav-item.is-active {
  background: rgba(99, 102, 241, 0.15);
  color: #f1f5f9;
  font-weight: 500;
  position: relative;
}

.nav-menu .nav-item.is-active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  background: #818cf8;
  border-radius: 0 3px 3px 0;
}

.sidebar :deep(.el-menu--collapse) .nav-item.is-active::before {
  left: 0;
  width: 3px;
  height: 20px;
}

.sidebar :deep(.el-menu--collapse) .nav-item {
  padding: 0;
  justify-content: center;
  display: flex;
  align-items: center;
}

.sidebar :deep(.el-menu--collapse) .nav-item .el-icon {
  margin: 0;
  font-size: 18px;
}

.user-bar {
  display: flex;
  align-items: center;
  padding: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  gap: 12px;
  flex-shrink: 0;
}

.user-bar-left {
  flex-shrink: 0;
}

.user-bar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.collapse-btn {
  background: none;
  border: none;
  color: #64748b;
  padding: 6px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #94a3b8;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
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

.user-role {
  color: #64748b;
  font-size: 11px;
  margin-top: 1px;
}

.logout-btn {
  background: none;
  border: none;
  color: #64748b;
  padding: 6px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.logout-btn:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.header {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e2e8f0;
  background: #fff;
  padding: 0 32px;
  height: 64px !important;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.page-title {
  font-size: 18px;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
  letter-spacing: -0.3px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: 1px solid #e2e8f0;
  color: #475569;
  padding: 7px 12px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.header-action-btn:hover {
  background: rgba(99, 102, 241, 0.08);
  border-color: #c7d2fe;
  color: #4f46e5;
}

.el-container {
  height: 100vh;
}

.el-header {
  line-height: 64px;
}

.el-main {
  background: #f8fafc;
  padding: 0;
  overflow-y: auto;
}

.main-content {
  padding: 28px 32px;
  min-height: calc(100vh - 64px);
}

/* Responsive */
@media (max-width: 768px) {
  .sidebar {
    width: 64px !important;
  }
  .logo-text,
  .user-bar-right {
    display: none !important;
  }
  .main-content {
    padding: 16px;
  }
}
</style>