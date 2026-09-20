<template>
  <div class="transfer-page">
    <div class="page-header">
      <h3>客户转让管理</h3>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-item">
        <el-select v-model="filterSalesman" placeholder="按业务员筛选" clearable @change="loadData">
          <el-option label="全部" :value="''" />
          <el-option v-for="s in salesmenList" :key="s.id" :label="s.real_name" :value="s.id" />
        </el-select>
      </div>
      <div class="filter-item">
        <el-input v-model="keyword" placeholder="搜索客户姓名/身份证" clearable @keyup.enter="loadData" @clear="loadData">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>
      <el-button @click="loadData">查询</el-button>

      <div class="filter-spacer"></div>

      <div class="filter-item">
        <el-select v-model="transferTargetId" placeholder="转让给..." :disabled="!selectedIds.length">
          <el-option v-for="s in salesmenList" :key="s.id" :label="s.real_name" :value="s.id" />
        </el-select>
      </div>
      <el-button type="warning" :disabled="!selectedIds.length || !transferTargetId" @click="handleBatchTransfer" :loading="transferLoading">
        <el-icon><Switch /></el-icon> 转让选中客户 ({{ selectedIds.length }})
      </el-button>
    </div>

    <!-- 客户表格 -->
    <el-table :data="customers" v-loading="loading" style="width: 100%; margin-top: 16px"
      @selection-change="handleSelectionChange" row-key="id">
      <el-table-column type="selection" width="50" />
      <el-table-column prop="name" label="姓名" min-width="100">
        <template #default="{ row }">
          <div class="name-cell">
            <div class="name-avatar">{{ row.name.charAt(0) }}</div>
            <span>{{ row.name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="phone" label="手机号" min-width="100" />
      <el-table-column prop="education" label="学历" min-width="80" />
      <el-table-column prop="current_salesman" label="当前业务员" min-width="110">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.current_salesman || '未分配' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="当前状态" min-width="100">
        <template #default="{ row }">
          <el-tag size="small">{{ row.current_status || '-' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="work_unit" label="工作单位" min-width="160" show-overflow-tooltip />
    </el-table>

    <div class="pagination">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @change="loadData" background />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const customers = ref<any[]>([])
const salesmenList = ref<any[]>([])
const keyword = ref('')
const filterSalesman = ref<number | ''>('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)

const selectedIds = ref<number[]>([])
const transferTargetId = ref<number | null>(null)
const transferLoading = ref(false)

async function loadSalesmen() {
  try {
    const { data } = await api.get('/api/customers/salesmen')
    salesmenList.value = data || []
  } catch {
    // 转让目标下拉依赖此列表，取不到时保持空列表
  }
}

async function loadData() {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (filterSalesman.value) params.salesman_id = filterSalesman.value

    const { data } = await api.get('/api/customers/', { params })
    customers.value = (data.items || []).map((c: any) => ({
      ...c,
      current_salesman: salesmenList.value.find((s: any) => s.id === c.assigned_salesman_id)?.real_name || '',
    }))
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function handleSelectionChange(rows: any[]) {
  selectedIds.value = rows.map(r => r.id)
}

async function handleBatchTransfer() {
  if (!selectedIds.value.length || !transferTargetId.value) return

  const targetName = salesmenList.value.find((s: any) => s.id === transferTargetId.value)?.real_name || ''
  try {
    await ElMessageBox.confirm(`确认将 ${selectedIds.value.length} 位客户转让给「${targetName}」？`, '批量转让确认')
  } catch {
    return
  }

  transferLoading.value = true
  try {
    const { data } = await api.post('/api/customers/batch-transfer', {
      customer_ids: selectedIds.value,
      salesman_id: transferTargetId.value,
    })
    ElMessage.success(data.message || '转让成功')
    selectedIds.value = []
    transferTargetId.value = null
    loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '转让失败')
  } finally {
    transferLoading.value = false
  }
}

onMounted(() => {
  loadSalesmen().then(() => loadData())
})
</script>

<style scoped>
.transfer-page {
  width: 100%;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #1e293b;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.filter-item {
  flex: 1 1 160px;
  min-width: 140px;
  max-width: 280px;
}
.filter-item > :deep(.el-select),
.filter-item > :deep(.el-input) {
  width: 100%;
}
.filter-bar > .el-button {
  flex: 0 0 auto;
}
.filter-spacer {
  flex: 1;
  min-width: 0;
}
.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
.name-avatar {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

:deep(.el-table .cell) {
  white-space: nowrap;
}
.pagination {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}
</style>
