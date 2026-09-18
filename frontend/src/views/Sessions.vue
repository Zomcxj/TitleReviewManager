<template>
  <div class="sessions-page">
    <div class="page-header">
      <div class="page-header-text">
        <h2>登录设备管理</h2>
        <p class="page-desc">以下设备当前已登录您的账号。如发现陌生设备，请立即下线并修改密码。</p>
      </div>
      <div class="page-header-actions">
        <el-button
          type="danger"
          :disabled="otherSessions.length === 0"
          :loading="revokingOthers"
          @click="handleRevokeOthers"
        >
          下线其他所有设备
        </el-button>
      </div>
    </div>

    <el-table :data="sessions" style="width: 100%" v-loading="loading">
      <el-table-column label="设备" min-width="200">
        <template #default="{ row }">
          <div class="device-cell">
            <span class="device-label">{{ row.device_label || '未知设备' }}</span>
            <el-tag v-if="row.is_current" type="success" size="small" effect="light">当前设备</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="ip_address" label="IP 地址" width="160" />
      <el-table-column label="登录时间" width="180">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="最后活动" width="180">
        <template #default="{ row }">
          {{ formatTime(row.last_seen_at) }}
        </template>
      </el-table-column>
      <el-table-column label="过期时间" width="180">
        <template #default="{ row }">
          {{ formatTime(row.expires_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <span v-if="row.is_current" class="no-action">—</span>
          <el-button
            v-else
            type="danger"
            text
            :loading="revokingId === row.session_id"
            @click="handleRevokeOne(row)"
          >
            下线
          </el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无其他登录设备" />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

interface Session {
  session_id: string
  ip_address: string
  device_label: string
  created_at: string
  last_seen_at: string
  expires_at: string
  is_current: boolean
}

const sessions = ref<Session[]>([])
const loading = ref(false)
const revokingOthers = ref(false)
const revokingId = ref<string | null>(null)

const otherSessions = computed(() => sessions.value.filter((s) => !s.is_current))

// 后端返回不带时区的 ISO 字符串，直接 new Date(str) 解析后手动格式化
function formatTime(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0 && typeof detail[0]?.msg === 'string') {
    return detail[0].msg
  }
  return fallback
}

async function fetchSessions() {
  loading.value = true
  try {
    const { data } = await api.get('/api/auth/sessions')
    sessions.value = data.items || []
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '获取登录设备列表失败'))
  } finally {
    loading.value = false
  }
}

async function handleRevokeOthers() {
  try {
    await ElMessageBox.confirm('将下线除当前设备外的所有登录设备，确定继续？', '确认下线', {
      type: 'warning',
    })
  } catch {
    return
  }
  revokingOthers.value = true
  try {
    const { data } = await api.post('/api/auth/sessions/revoke-others')
    ElMessage.success(data.message || '已下线其他设备')
    await fetchSessions()
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '下线其他设备失败'))
  } finally {
    revokingOthers.value = false
  }
}

async function handleRevokeOne(row: Session) {
  try {
    await ElMessageBox.confirm('确定下线该设备？该设备需重新登录。', '确认下线', {
      type: 'warning',
    })
  } catch {
    return
  }
  revokingId.value = row.session_id
  try {
    const { data } = await api.delete(`/api/auth/sessions/${row.session_id}`)
    ElMessage.success(data.message || '该设备已下线')
    await fetchSessions()
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '下线设备失败'))
  } finally {
    revokingId.value = null
  }
}

onMounted(fetchSessions)
</script>

<style scoped>
.sessions-page {
  width: 100%;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.page-header-text h2 {
  font-size: 20px;
  font-weight: 600;
  color: #0f172a;
  margin: 0 0 6px;
  letter-spacing: -0.3px;
}

.page-desc {
  font-size: 13px;
  color: #64748b;
  margin: 0;
}

.page-header-actions {
  flex-shrink: 0;
}

.device-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.device-label {
  color: #0f172a;
  font-weight: 500;
}

.no-action {
  color: #94a3b8;
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
