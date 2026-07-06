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
      </div>
    </div>

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
  } catch {}
  try {
    const oldVal = typeof row.old_value === 'string' ? JSON.parse(row.old_value) : row.old_value
    if (oldVal?.name) return oldVal.name
  } catch {}
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
