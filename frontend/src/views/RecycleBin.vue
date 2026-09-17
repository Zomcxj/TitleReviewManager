<template>
  <div class="recycle-bin-page" v-loading="loading">
    <div class="page-header">
      <div class="header-left">
        <h2>回收站</h2>
        <p class="header-sub">已软删除的客户、申报批次与用户，可恢复或彻底删除</p>
      </div>
      <el-button :icon="Refresh" @click="loadData">刷新</el-button>
    </div>

    <el-card class="filter-card" shadow="never">
      <el-radio-group v-model="resourceType" @change="loadData">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="customer">客户</el-radio-button>
        <el-radio-button value="application">申报批次</el-radio-button>
        <el-radio-button value="user">用户</el-radio-button>
      </el-radio-group>
      <span class="total-hint">共 {{ total }} 条记录</span>
    </el-card>

    <el-card class="table-card" shadow="never">
      <el-table :data="items" style="width: 100%" v-loading="loading">
        <el-table-column label="类型" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="typeTag(row.resource_type)" effect="plain" round size="small">
              {{ typeLabel(row.resource_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.detail || '-' }}</template>
        </el-table-column>
        <el-table-column label="删除时间" width="180">
          <template #default="{ row }">{{ formatDate(row.deleted_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="handleRestore(row)">恢复</el-button>
            <el-button type="danger" size="small" @click="handlePurge(row)">彻底删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="回收站为空" :image-size="80" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

interface RecycleItem {
  resource_type: 'customer' | 'application' | 'user'
  id: number
  name: string
  deleted_at: string | null
  detail: string | null
}

const loading = ref(false)
const items = ref<RecycleItem[]>([])
const total = ref(0)
const resourceType = ref('')

const TYPE_LABELS: Record<string, string> = {
  customer: '客户',
  application: '申报批次',
  user: '用户',
}

function typeLabel(type: string) {
  return TYPE_LABELS[type] || type
}

function typeTag(type: string) {
  const map: Record<string, string> = {
    customer: 'primary',
    application: 'success',
    user: 'warning',
  }
  return map[type] || 'info'
}

function formatDate(value: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN')
}

async function loadData() {
  loading.value = true
  try {
    const params = resourceType.value ? { resource_type: resourceType.value } : {}
    const { data } = await api.get('/api/recycle-bin/', { params })
    items.value = data.items || []
    total.value = data.total ?? items.value.length
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载回收站失败')
  } finally {
    loading.value = false
  }
}

async function handleRestore(row: RecycleItem) {
  try {
    await ElMessageBox.confirm(
      `确认恢复${typeLabel(row.resource_type)}「${row.name}」？`,
      '恢复记录',
      { type: 'info', confirmButtonText: '确认恢复', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await api.post('/api/recycle-bin/restore', {
      resource_type: row.resource_type,
      id: row.id,
    })
    ElMessage.success('已恢复')
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '恢复失败')
  }
}

async function handlePurge(row: RecycleItem) {
  try {
    await ElMessageBox.confirm(
      `此操作不可恢复，确定彻底删除${typeLabel(row.resource_type)}「${row.name}」？`,
      '彻底删除',
      { type: 'warning', confirmButtonText: '彻底删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await api.delete(`/api/recycle-bin/purge/${row.resource_type}/${row.id}`)
    ElMessage.success('已彻底删除')
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '彻底删除失败')
  }
}

onMounted(loadData)
</script>

<style scoped>
.recycle-bin-page {
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

.filter-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  margin-bottom: 16px;
}

.filter-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.total-hint {
  font-size: 13px;
  color: #94a3b8;
}

.table-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
</style>
