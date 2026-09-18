<template>
  <div class="backup-page">
    <div class="page-header">
      <div class="header-left">
        <h2>数据备份</h2>
        <p class="header-sub">数据库与材料文件的备份记录、手动执行与恢复指引</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
    </div>

    <el-card class="config-card" shadow="never" v-loading="configLoading">
      <template #header>
        <div class="card-header">
          <span class="card-title">备份配置</span>
          <el-tag :type="config?.BACKUP_ENABLED ? 'success' : 'info'" effect="plain" round size="small">
            {{ config?.BACKUP_ENABLED ? '自动备份已启用' : '自动备份已关闭' }}
          </el-tag>
        </div>
      </template>
      <div class="config-grid">
        <div class="config-item">
          <span class="config-label">备份目录</span>
          <span class="config-value mono" :title="config?.BACKUP_DIR">{{ config?.BACKUP_DIR || '-' }}</span>
        </div>
        <div class="config-item">
          <span class="config-label">保留份数</span>
          <span class="config-value">{{ config?.BACKUP_KEEP ?? '-' }} 份</span>
        </div>
        <div class="config-item">
          <span class="config-label">每日执行时间</span>
          <span class="config-value">{{ config?.BACKUP_HOUR ?? '-' }}:00</span>
        </div>
        <div class="config-item">
          <span class="config-label">包含材料文件</span>
          <span class="config-value">{{ config?.BACKUP_INCLUDE_FILES ? '是' : '否' }}</span>
        </div>
        <div class="config-item">
          <span class="config-label">数据库压缩</span>
          <span class="config-value">{{ config?.BACKUP_COMPRESS ? '是' : '否' }}</span>
        </div>
        <div class="config-item">
          <span class="config-label">历史备份</span>
          <span class="config-value">{{ total }} 份</span>
        </div>
      </div>
    </el-card>

    <el-card class="action-card" shadow="never">
      <div class="action-bar">
        <div class="action-left">
          <el-switch v-model="includeFiles" :disabled="running" active-text="包含材料文件" />
          <span class="action-hint">
            备份为同步执行，材料文件较多时可能耗时较久，请勿重复点击
          </span>
        </div>
        <el-button
          type="primary"
          :icon="Download"
          :loading="running"
          @click="handleRunBackup"
        >
          {{ running ? '备份中…' : '立即备份' }}
        </el-button>
      </div>

      <el-alert
        v-if="lastResult"
        :type="lastResult.success ? 'success' : 'error'"
        :closable="true"
        show-icon
        class="result-alert"
        @close="lastResult = null"
      >
        <template #title>
          {{ lastResult.success ? '备份完成' : '备份失败' }}
          <span class="result-duration">耗时 {{ lastResult.duration_seconds }} 秒</span>
        </template>
        <div class="result-body">
          <div>数据库备份：{{ lastResult.db_backup || '未生成' }}</div>
          <div>材料文件备份：{{ lastResult.files_backup || '未包含' }}</div>
          <div v-if="lastResult.error" class="result-error">错误：{{ lastResult.error }}</div>
          <div v-if="lastResult.cleaned?.length" class="result-cleaned">
            已清理 {{ lastResult.cleaned.length }} 个过期备份文件：{{ lastResult.cleaned.join('、') }}
          </div>
        </div>
      </el-alert>
    </el-card>

    <el-card class="table-card" shadow="never">
      <template #header>
        <span class="card-title">备份历史</span>
      </template>
      <el-table :data="items" style="width: 100%" v-loading="loading">
        <el-table-column label="备份时间" width="180">
          <template #default="{ row }">{{ formatTime(row.backup_time) }}</template>
        </el-table-column>
        <el-table-column label="数据库类型" width="120" align="center">
          <template #default="{ row }">
            <el-tag effect="plain" round size="small">{{ dbTypeLabel(row.db_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数据库大小" width="120" align="right">
          <template #default="{ row }">{{ formatSize(row.db_file_size_bytes) }}</template>
        </el-table-column>
        <el-table-column label="材料文件数" width="120" align="right">
          <template #default="{ row }">
            {{ row.files_backup_file ? `${row.files_count ?? 0} 个` : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="材料文件大小" width="130" align="right">
          <template #default="{ row }">
            {{ row.files_backup_file ? formatSize(row.files_backup_size_bytes) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100" align="right">
          <template #default="{ row }">{{ row.duration_seconds != null ? `${row.duration_seconds}s` : '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" effect="plain" round size="small">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.error"
              type="danger"
              link
              size="small"
              @click="showError(row)"
            >
              查看错误
            </el-button>
            <span v-else class="no-error">-</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无备份记录" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <el-card class="restore-card" shadow="never">
      <template #header>
        <span class="card-title">恢复步骤</span>
      </template>
      <ol class="restore-steps">
        <li>停止后端服务，避免恢复过程中仍有数据写入。</li>
        <li>解压数据库备份：SQLite 执行 <code>gzip -dk db_&lt;时间戳&gt;.sqlite.gz</code>；PostgreSQL 执行 <code>gzip -dk db_&lt;时间戳&gt;.sql.gz</code>。</li>
        <li>
          替换数据库：SQLite 用解压出的文件替换 <code>DATABASE_URL</code> 指向的库文件（先备份现有文件）；
          PostgreSQL 执行 <code>psql -U &lt;user&gt; -d &lt;db&gt; -f db_&lt;时间戳&gt;.sql</code>。
        </li>
        <li>解压材料文件到存储根目录：<code>tar -xzf files_&lt;时间戳&gt;.tar.gz -C &lt;存储根目录&gt;</code>。</li>
        <li>重启服务，核对 <code>manifest_&lt;时间戳&gt;.json</code> 中的记录（大小 / 数量 / 是否成功）。</li>
      </ol>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import api from '../api'

interface BackupItem {
  timestamp: string
  backup_time: string | null
  db_type: string
  db_backup_file: string | null
  db_file_size_bytes: number
  files_backup_file: string | null
  files_backup_size_bytes: number
  files_count: number
  files_total_size_bytes: number
  app_version: string | null
  success: boolean
  error: string | null
  duration_seconds: number
  backup_dir: string
  manifest_file?: string
}

interface BackupConfig {
  BACKUP_ENABLED: boolean
  BACKUP_DIR: string
  BACKUP_KEEP: number
  BACKUP_HOUR: number
  BACKUP_INCLUDE_FILES: boolean
  BACKUP_COMPRESS: boolean
}

interface BackupResult {
  success: boolean
  timestamp: string
  db_backup: string | null
  files_backup: string | null
  manifest: string | null
  duration_seconds: number
  error: string | null
  cleaned: string[]
}

const loading = ref(false)
const configLoading = ref(false)
const running = ref(false)
const items = ref<BackupItem[]>([])
const total = ref(0)
const config = ref<BackupConfig | null>(null)
const includeFiles = ref(true)
const lastResult = ref<BackupResult | null>(null)

function dbTypeLabel(type: string) {
  const map: Record<string, string> = { sqlite: 'SQLite', postgresql: 'PostgreSQL', unknown: '未知' }
  return map[type] || type || '-'
}

function formatSize(bytes?: number | null) {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value.toFixed(i === 0 ? 0 : 2)} ${units[i]}`
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('zh-CN')
}

async function loadConfig() {
  configLoading.value = true
  try {
    const { data } = await api.get('/api/backup/config')
    config.value = data
    includeFiles.value = !!data.BACKUP_INCLUDE_FILES
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载备份配置失败')
  } finally {
    configLoading.value = false
  }
}

async function loadList() {
  loading.value = true
  try {
    const { data } = await api.get('/api/backup/')
    items.value = data.items || []
    total.value = data.total ?? items.value.length
    if (data.backup_dir) {
      config.value = { ...(config.value as BackupConfig), BACKUP_DIR: data.backup_dir, BACKUP_ENABLED: data.enabled }
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载备份记录失败')
  } finally {
    loading.value = false
  }
}

async function loadData() {
  await Promise.all([loadConfig(), loadList()])
}

async function handleRunBackup() {
  try {
    await ElMessageBox.confirm(
      includeFiles.value
        ? '将立即同步执行一次备份（含材料文件），数据量较大时可能耗时较久，确认继续？'
        : '将立即同步执行一次备份（不含材料文件），确认继续？',
      '立即备份',
      { type: 'warning', confirmButtonText: '开始备份', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  running.value = true
  try {
    const { data } = await api.post('/api/backup/run', { include_files: includeFiles.value })
    lastResult.value = data
    if (data.success) {
      ElMessage.success(`备份完成，耗时 ${data.duration_seconds} 秒`)
    } else {
      ElMessage.error(data.error || '备份失败')
    }
    await loadList()
  } catch (e: any) {
    const detail = e.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '执行备份失败')
  } finally {
    running.value = false
  }
}

function showError(row: BackupItem) {
  ElMessageBox.alert(row.error || '无错误信息', `备份失败（${formatTime(row.backup_time)}）`, {
    type: 'error',
    confirmButtonText: '知道了',
  })
}

onMounted(loadData)
</script>

<style scoped>
.backup-page {
  padding: 4px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.header-sub {
  margin: 0;
  font-size: 13px;
  color: #94a3b8;
}

.config-card,
.action-card,
.table-card,
.restore-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px 24px;
}

.config-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.config-label {
  font-size: 13px;
  color: #94a3b8;
  flex-shrink: 0;
}

.config-value {
  font-size: 13px;
  color: #0f172a;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-value.mono {
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
  font-weight: 400;
}

.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.action-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.action-hint {
  font-size: 12px;
  color: #94a3b8;
}

.result-alert {
  margin-top: 16px;
  border-radius: 10px;
}

.result-duration {
  font-size: 12px;
  font-weight: 400;
  color: #64748b;
  margin-left: 8px;
}

.result-body {
  font-size: 12px;
  line-height: 1.9;
  word-break: break-all;
}

.result-error {
  color: #dc2626;
}

.result-cleaned {
  color: #d97706;
}

.no-error {
  color: #cbd5e1;
}

.restore-steps {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: #475569;
  line-height: 2;
}

.restore-steps code {
  background: #f1f5f9;
  border-radius: 4px;
  padding: 1px 6px;
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
  font-size: 12px;
  color: #4338ca;
}
</style>
