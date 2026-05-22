<template>
  <el-popover trigger="click" placement="bottom" :width="400" popper-class="notification-popover">
    <template #reference>
      <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99" class="notification-badge">
        <el-icon :size="20"><Bell /></el-icon>
      </el-badge>
    </template>
    
    <div class="notification-panel">
      <div class="notification-header">
        <h4>消息通知</h4>
        <el-button text type="primary" size="small" @click="markAllAsRead" v-if="unreadCount > 0">
          全部已读
        </el-button>
      </div>
      
      <div class="notification-list" v-loading="loading">
        <div v-if="notifications.length === 0" class="empty-state">
          <el-icon :size="40"><Bell /></el-icon>
          <p>暂无通知</p>
        </div>
        
        <div
          v-for="n in notifications"
          :key="n.id"
          class="notification-item"
          :class="{ unread: !n.is_read }"
          @click="markAsRead(n.id)"
        >
          <div class="notification-icon">
            <el-icon :size="20" :class="getTypeIcon(n.type)"></el-icon>
          </div>
          <div class="notification-content">
            <div class="notification-title">{{ n.title }}</div>
            <div class="notification-text">{{ n.content }}</div>
            <div class="notification-time">{{ formatTime(n.created_at) }}</div>
          </div>
        </div>
      </div>
      
      <div class="notification-footer" v-if="notifications.length > 0">
        <router-link to="/admin/notifications">查看全部</router-link>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

interface Notification {
  id: number
  user_id: number
  title: string
  content: string
  type: string
  is_read: boolean
  created_at: string
}

const loading = ref(false)
const notifications = ref<Notification[]>([])
const unreadCount = ref(0)
let intervalId: ReturnType<typeof setInterval> | null = null

async function fetchNotifications() {
  loading.value = true
  try {
    const { data } = await axios.get('/api/notifications/', {
      params: { page: 1, page_size: 10 },
    })
    notifications.value = data.items
    unreadCount.value = data.unread_count
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function markAsRead(id: number) {
  try {
    await axios.post(`/api/notifications/read/${id}`)
    const notif = notifications.value.find(n => n.id === id)
    if (notif) notif.is_read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch (e) {
    console.error(e)
  }
}

async function markAllAsRead() {
  try {
    await axios.post('/api/notifications/read-all')
    notifications.value.forEach(n => n.is_read = true)
    unreadCount.value = 0
  } catch (e) {
    console.error(e)
  }
}

function getTypeIcon(type: string): string {
  const map: Record<string, string> = {
    'status_change': 'el-icon--warning',
    'follow_up_reminder': 'el-icon--primary',
    'system': 'el-icon--info',
  }
  return map[type] || ''
}

function formatTime(time: string): string {
  const date = new Date(time)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const hours = Math.floor(diff / (1000 * 60 * 60))
  const days = Math.floor(hours / 24)
  
  if (days > 0) return `${days}天前`
  if (hours > 0) return `${hours}小时前`
  return '刚刚'
}

onMounted(() => {
  fetchNotifications()
  intervalId = setInterval(fetchNotifications, 30000)
})

onUnmounted(() => {
  if (intervalId) {
    clearInterval(intervalId)
  }
})
</script>

<style scoped>
.notification-badge {
  cursor: pointer;
  padding: 8px;
  color: #606266;
}

.notification-badge:hover {
  color: #409EFF;
}

.notification-panel {
  max-height: 400px;
}

.notification-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 12px;
}

.notification-header h4 {
  margin: 0;
  font-size: 14px;
  color: #303133;
}

.notification-list {
  max-height: 300px;
  overflow-y: auto;
}

.notification-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 8px;
  background: #f5f7fa;
  transition: all 0.2s;
}

.notification-item:hover {
  background: #ecf5ff;
}

.notification-item.unread {
  background: #ecf5ff;
}

.notification-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  color: #909399;
}

.notification-content {
  flex: 1;
  min-width: 0;
}

.notification-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}

.notification-text {
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.notification-time {
  font-size: 11px;
  color: #909399;
  margin-top: 6px;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: #909399;
}

.empty-state .el-icon {
  margin-bottom: 12px;
  opacity: 0.5;
}

.notification-footer {
  text-align: center;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
  margin-top: 12px;
}

.notification-footer a {
  font-size: 13px;
  color: #409EFF;
  text-decoration: none;
}
</style>
