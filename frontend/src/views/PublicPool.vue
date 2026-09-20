<template>
  <div class="public-pool-page">
    <div class="page-header">
      <h2>客户公海池</h2>
      <div class="stats-bar">
        <el-statistic title="公海客户数" :value="stats.total_in_pool" />
        <el-statistic title="今日领取" :value="stats.today_claims" />
        <el-statistic title="已超时" :value="stats.overdue" value-style="color: #f56c6c" />
        <el-statistic title="即将超时" :value="stats.expiring_soon" value-style="color: #e6a23c" />
      </div>
    </div>

    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索客户名称/手机号"
        style="width: 300px"
        clearable
        @keyup.enter="loadData"
        @clear="loadData"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button type="primary" @click="loadData">查询</el-button>
    </div>

    <el-table :data="customers" style="width: 100%; margin-top: 16px" v-loading="loading">
      <el-table-column prop="name" label="姓名" width="90">
        <template #default="{ row }">
          <div class="name-cell">
            <div class="name-avatar">{{ row.name.charAt(0) }}</div>
            <span>{{ row.name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="phone" label="手机号" width="120" />
      <el-table-column prop="education" label="学历" width="90" />
      <el-table-column prop="work_unit" label="工作单位" min-width="180" show-overflow-tooltip />
      <el-table-column label="当前状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.current_status)" size="small" round>
            {{ row.current_status || '-' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="days_in_pool" label="在池天数" width="80" />
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" @click="handleClaim(row)">领取</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @change="loadData"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

interface Customer {
  id: number
  name: string
  phone: string
  education: string
  work_unit: string
  current_status: string
  days_in_pool: number
}

const loading = ref(false)
const customers = ref<Customer[]>([])
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const stats = reactive({
  total_in_pool: 0,
  today_claims: 0,
  overdue: 0,
  expiring_soon: 0,
})

async function loadStats() {
  try {
    const { data } = await api.get('/api/public-pool/stats')
    stats.total_in_pool = data.total_in_pool
    stats.today_claims = data.today_claims
    stats.overdue = data.overdue
    stats.expiring_soon = data.expiring_soon
  } catch (e) {
    console.error(e)
  }
}

async function loadData() {
  loading.value = true
  try {
    const { data } = await api.get('/api/public-pool/', {
      params: { page: page.value, page_size: pageSize.value, keyword: keyword.value || undefined },
    })
    customers.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('加载公海池失败')
  } finally {
    loading.value = false
  }
}

async function handleClaim(customer: Customer) {
  try {
    await ElMessageBox.confirm(`确认领取客户 "${customer.name}"？`, '领取客户')
    await api.post(`/api/public-pool/claim/${customer.id}`)
    ElMessage.success('领取成功')
    loadData()
    loadStats()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || '领取失败')
    }
  }
}

function statusType(status: string): string {
  const map: Record<string, string> = {
    '初次申报': '', '资料补充': 'warning', '完成资料': 'success',
    '提交评审机构审核': '', '返修': 'danger', '通过': 'success',
    '不通过': 'danger', '二次申报': '',
  }
  return map[status] || 'info'
}

onMounted(() => {
  loadStats()
  loadData()
})
</script>

<style scoped>
.public-pool-page {
  padding: 20px;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h2 {
  margin-bottom: 16px;
}

.stats-bar {
  display: flex;
  gap: 32px;
}

.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.name-avatar {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}
</style>
