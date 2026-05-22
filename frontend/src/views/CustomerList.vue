<template>
  <div class="customer-list">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-input v-model="keyword" placeholder="搜索姓名 / 身份证 / 手机号" style="width: 300px" clearable
          @keyup.enter="loadData" @clear="loadData">
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select v-model="statusFilter" placeholder="状态筛选" clearable style="width: 150px; margin-left: 12px"
          @change="loadData">
          <el-option v-for="s in statusOptions" :key="s" :label="s" :value="s" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <span class="result-count">共 {{ total }} 条</span>
        <el-button type="success" icon="Download" @click="handleExport">导出 Excel</el-button>
      </div>
    </div>

    <el-table :data="customers" style="width: 100%; margin-top: 16px" v-loading="loading" row-key="id"
      :row-class-name="getRowClass">
      <el-table-column prop="name" label="姓名" min-width="120">
        <template #default="{ row }">
          <div class="name-cell">
            <div class="name-avatar">{{ row.name.charAt(0) }}</div>
            <span class="name-text">{{ row.name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="phone" label="手机号" min-width="110" />
      <el-table-column prop="education" label="学历" min-width="100" />
      <el-table-column v-if="showSalesman" label="业务员" min-width="100">
        <template #default="{ row }">
          {{ salesmenMap[row.assigned_salesman_id] || '未分配' }}
        </template>
      </el-table-column>
      <el-table-column prop="work_unit" label="工作单位" min-width="180" show-overflow-tooltip />
      <el-table-column label="当前状态" min-width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.current_status)" effect="plain" round size="small">
            {{ row.current_status || '-' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作提示" min-width="120">
        <template #default="{ row }">
          <span class="hint-text">{{ getHint(row.current_status) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <router-link :to="`/admin/customers/${row.id}`">
            <el-button type="primary" text size="small">详情</el-button>
          </router-link>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next" @change="loadData" background />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus'

const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const customers = ref<any[]>([])
const salesmenMap = ref<Record<number, string>>({})
const keyword = ref('')
const statusFilter = ref((route.query.status as string) || '')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const showSalesman = computed(() => authStore.isAdmin || authStore.isReviewer)

const statusOptions = ['初次申报', '资料补充', '完成资料', '提交评审机构审核', '返修', '通过', '不通过', '二次申报']

function statusType(status: string) {
  const map: Record<string, string> = {
    '初次申报': '', '资料补充': 'warning', '完成资料': 'success',
    '提交评审机构审核': '', '返修': 'danger', '通过': 'success',
    '不通过': 'danger', '二次申报': '',
  }
  return map[status] || 'info'
}

function getHint(status: string) {
  if (!status) return '待完善信息'
  const isSalesman = authStore.isSalesman || authStore.isAdmin
  const isReviewer = authStore.isReviewer || authStore.isAdmin
  const hints: Record<string, string> = {
    '初次申报': isSalesman ? '需上传材料' : '待审核',
    '资料补充': isSalesman ? '需联系客户补充' : '等待重新提交',
    '完成资料': isSalesman ? '可提交评审机构' : '-',
    '提交评审机构审核': '等待机构反馈',
    '返修': isSalesman ? '需按意见修改' : '-',
    '通过': '已完成',
    '不通过': isSalesman ? '可发起二次申报' : '-',
    '二次申报': isSalesman ? '需上传材料' : '待审核',
  }
  return hints[status] || '-'
}

function getRowClass({ row }: any) {
  if (row.current_status === '资料补充' || row.current_status === '返修') return 'row-urgent'
  return ''
}

async function loadSalesmen() {
  try {
    const { data } = await api.get('/api/customers/salesmen')
    const map: Record<number, string> = {}
    data.forEach((s: any) => { map[s.id] = s.real_name })
    salesmenMap.value = map
  } catch {}
}

async function loadData() {
  loading.value = true
  try {
    const { data } = await api.get('/api/customers/', {
      params: { page: page.value, page_size: pageSize.value, keyword: keyword.value || undefined, status: statusFilter.value || undefined },
    })
    customers.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function handleExport() {
  try {
    const { data } = await api.post('/api/exports/customers', null, {
      params: { keyword: keyword.value || undefined, status: statusFilter.value || undefined },
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `客户列表_${new Date().getTime()}.xlsx`
    link.click()
    window.URL.revokeObjectURL(url)
  } catch (e: any) {
    console.error(e)
  }
}

onMounted(() => {
  loadSalesmen()
  loadData()
})
</script>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toolbar-left :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 12px;
  box-shadow: 0 0 0 1px #e5e7eb;
}

.toolbar-left :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #d1d5db;
}

.toolbar-left :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.toolbar-left :deep(.el-select .el-input__wrapper) {
  border-radius: 10px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.result-count {
  color: #64748b;
  font-size: 13px;
  font-weight: 500;
}

:deep(.el-table) {
  border-radius: 12px;
  border: 1px solid #f1f5f9;
}

:deep(.el-table__header th) {
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

:deep(.el-table__body td) {
  padding: 16px 0;
  border-bottom: 1px solid #f8fafc;
}

:deep(.el-table__body tr:hover td) {
  background: #f8fafc;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.name-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.name-avatar {
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

.hint-text {
  color: #64748b;
  font-size: 12px;
}

:deep(.el-table .cell) {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pagination {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}

:deep(.el-pagination) {
  --el-pagination-bg-color: transparent;
  --el-pagination-text-color: #64748b;
  --el-pagination-button-bg-color: transparent;
  border-radius: 8px;
}

:deep(.el-pagination .el-pager li) {
  border-radius: 8px;
}

:deep(.el-pagination .el-pager li.is-active) {
  background: #6366f1;
  color: #fff;
}

:deep(.row-urgent) {
  background: linear-gradient(90deg, #fef2f2, transparent);
}

:deep(.el-button--success) {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  border-radius: 10px;
  font-weight: 500;
}

:deep(.el-button--success:hover) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.25);
}
</style>
