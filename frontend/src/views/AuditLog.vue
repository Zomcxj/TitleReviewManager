<template>
  <div class="audit-log-page">
    <div class="page-header">
      <h2>操作审计日志</h2>
      <div class="filters">
        <el-input
          v-model="filters.username"
          placeholder="用户名"
          clearable
          style="width: 150px"
          @clear="handleSearch"
        />
        <el-input
          v-model="filters.action"
          placeholder="操作类型"
          clearable
          style="width: 150px"
          @clear="handleSearch"
        />
        <el-select
          v-model="filters.resource_type"
          placeholder="资源类型"
          clearable
          style="width: 150px"
          @clear="handleSearch"
        >
          <el-option label="客户" value="customer" />
          <el-option label="申报批次" value="application" />
          <el-option label="材料" value="material" />
          <el-option label="审核" value="review" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 240px"
          @change="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button type="success" :loading="exporting" @click="handleExport">
          <el-icon><Download /></el-icon> 导出 Excel
        </el-button>
        <el-button type="warning" :loading="verifying" @click="handleVerifyChain">
          <el-icon><Lock /></el-icon> 校验完整性
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="chainResult"
      :type="chainResult.valid ? 'success' : 'error'"
      :closable="true"
      show-icon
      class="chain-alert"
      @close="chainResult = null"
    >
      <template #title>
        {{ chainResult.valid ? '审计日志完整性校验通过' : '警告：审计日志可能被篡改' }}
      </template>
      <div class="chain-detail">
        已校验 {{ chainResult.checked }} 条记录<template v-if="chainResult.unchained > 0">（其中 {{ chainResult.unchained }} 条为历史数据，未纳入校验）</template>
        <div v-if="!chainResult.valid">
          <p>原因：{{ chainResult.reason }}</p>
          <p>异常记录 ID：{{ chainResult.broken_at.join('、') }}</p>
        </div>
      </div>
    </el-alert>

    <el-table :data="logs" style="width: 100%" v-loading="loading">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="username" label="操作人" width="120" />
      <el-table-column prop="action" label="操作类型" width="100">
        <template #default="{ row }">
          <el-tag :type="getActionType(row.action)">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="resource_type" label="资源类型" width="100" />
      <el-table-column prop="resource_id" label="资源 ID" width="80" />
      <el-table-column label="变更详情" min-width="350">
        <template #default="{ row }">
          <div class="change-detail-wrap">
            <div v-if="row.resource_type === 'customer' && getCustomerName(row)" class="customer-badge">
              <el-tag size="small" type="info">{{ getCustomerName(row) }}</el-tag>
            </div>
            <div v-if="row.old_value || row.new_value" class="change-detail">
              <div v-if="row.old_value" class="old-value">
                <span class="label">变更前:</span>
                <code>{{ formatJson(row.old_value) }}</code>
              </div>
              <div v-if="row.new_value" class="new-value">
                <span class="label">变更后:</span>
                <code>{{ formatJson(row.new_value) }}</code>
              </div>
            </div>
            <span v-else class="no-detail">-</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="ip_address" label="IP 地址" width="140" />
      <el-table-column prop="created_at" label="操作时间" width="180">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="fetchLogs"
        @current-change="fetchLogs"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import api from '../api'
import { ElMessage } from 'element-plus'
import { Download, Lock } from '@element-plus/icons-vue'

interface Log {
  id: number
  username: string
  action: string
  resource_type: string
  resource_id: number
  old_value: any
  new_value: any
  ip_address: string
  user_agent: string
  created_at: string
}

const loading = ref(false)
const exporting = ref(false)
const verifying = ref(false)
const chainResult = ref<any>(null)
const logs = ref<Log[]>([])
const filters = reactive({
  username: '',
  action: '',
  resource_type: '',
})
const dateRange = ref<[Date, Date] | null>(null)

const pagination = reactive({
  page: 1,
  page_size: 20,
  total: 0,
})

async function fetchLogs() {
  loading.value = true
  try {
    const params: any = {
      page: pagination.page,
      page_size: pagination.page_size,
    }
    if (filters.username) params.username = filters.username
    if (filters.action) params.action = filters.action
    if (filters.resource_type) params.resource_type = filters.resource_type
    if (dateRange.value) {
      params.start_date = dateRange.value[0].toISOString()
      params.end_date = dateRange.value[1].toISOString()
    }

    const { data } = await api.get('/api/audit/logs', { params })
    logs.value = data.items
    pagination.total = data.total
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载日志失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  pagination.page = 1
  fetchLogs()
}

function buildFilterParams(): Record<string, any> {
  const params: Record<string, any> = {}
  if (filters.username) params.username = filters.username
  if (filters.action) params.action = filters.action
  if (filters.resource_type) params.resource_type = filters.resource_type
  if (dateRange.value) {
    params.start_date = dateRange.value[0].toISOString()
    params.end_date = dateRange.value[1].toISOString()
  }
  return params
}

function parseFilename(disposition: string | undefined): string {
  if (!disposition) return ''
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  return match ? match[1] : ''
}

async function handleVerifyChain() {
  verifying.value = true
  try {
    const { data } = await api.get('/api/audit/verify-chain')
    chainResult.value = data
    if (data.valid) {
      ElMessage.success(`完整性校验通过（${data.checked} 条记录）`)
    } else {
      ElMessage.error('检测到审计日志异常，请立即排查')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '校验失败')
  } finally {
    verifying.value = false
  }
}

async function handleExport() {
  exporting.value = true
  try {
    const response = await api.get('/api/audit/export', {
      params: buildFilterParams(),
      responseType: 'blob',
    })
    const disposition = response.headers?.['content-disposition'] as string | undefined
    const filename = parseFilename(disposition) || `操作审计日志_${new Date().getTime()}.xlsx`
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (e: any) {
    // blob 响应下错误体也是 blob，需要异步解析出 detail
    let detail = ''
    const blob = e.response?.data
    if (blob instanceof Blob) {
      try {
        detail = JSON.parse(await blob.text())?.detail || ''
      } catch {
        detail = ''
      }
    } else {
      detail = e.response?.data?.detail || ''
    }
    ElMessage.error(detail || '导出失败')
  } finally {
    exporting.value = false
  }
}

function getActionType(action: string): 'success' | 'warning' | 'danger' | 'info' {
  if (action === 'CREATE') return 'success'
  if (action === 'UPDATE') return 'warning'
  if (action === 'DELETE') return 'danger'
  return 'info'
}

function getCustomerName(row: Log): string {
  try {
    const newVal = typeof row.new_value === 'string' ? JSON.parse(row.new_value) : row.new_value
    if (newVal?.name) return newVal.name
  } catch {
    // 历史数据可能不是合法 JSON，解析失败时尝试下一个来源
  }
  try {
    const oldVal = typeof row.old_value === 'string' ? JSON.parse(row.old_value) : row.old_value
    if (oldVal?.name) return oldVal.name
  } catch {
    // 两个来源都取不到，返回空串由调用方展示占位
  }
  return ''
}

function formatJson(obj: any): string {
  if (!obj) return ''
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

function formatTime(time: string): string {
  return new Date(time).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

onMounted(fetchLogs)
</script>

<style scoped>
.chain-alert {
  margin-bottom: 16px;
}
.chain-detail {
  font-size: 13px;
  line-height: 1.8;
}
.chain-detail p {
  margin: 4px 0 0;
}

.audit-log-page {
  padding: 20px;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin-bottom: 16px;
}

.filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.change-detail {
  font-size: 12px;
}

.old-value {
  margin-bottom: 4px;
}

.new-value {
  color: #67c23a;
}

.label {
  font-weight: bold;
  margin-right: 4px;
}

code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
}

.no-detail {
  color: #909399;
}
.change-detail-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.customer-badge {
  margin-bottom: 2px;
}
</style>
