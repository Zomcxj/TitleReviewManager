<template>
  <div class="follow-up-page">
    <!-- 统计卡 -->
    <div class="stats-grid">
      <div class="stat-card overdue" :class="{ active: scope === 'overdue' }" @click="switchScope('overdue')">
        <div class="stat-header">
          <span class="stat-label">已逾期</span>
          <div class="stat-icon overdue">
            <el-icon><WarningFilled /></el-icon>
          </div>
        </div>
        <div class="stat-value">{{ summary.overdue }}</div>
        <div class="stat-trend">需要尽快联系</div>
      </div>

      <div class="stat-card today" :class="{ active: scope === 'today' }" @click="switchScope('today')">
        <div class="stat-header">
          <span class="stat-label">今天待跟进</span>
          <div class="stat-icon today">
            <el-icon><AlarmClock /></el-icon>
          </div>
        </div>
        <div class="stat-value">{{ summary.today }}</div>
        <div class="stat-trend">含已逾期客户</div>
      </div>

      <div class="stat-card week" :class="{ active: scope === 'week' }" @click="switchScope('week')">
        <div class="stat-header">
          <span class="stat-label">未来一周</span>
          <div class="stat-icon week">
            <el-icon><Calendar /></el-icon>
          </div>
        </div>
        <div class="stat-value">{{ summary.week }}</div>
        <div class="stat-trend">7 天内计划</div>
      </div>
    </div>

    <!-- 列表 -->
    <div class="card">
      <div class="card-header">
        <h3>待跟进日程</h3>
        <div class="header-right">
          <el-radio-group v-model="scope" size="small" @change="loadSchedule">
            <el-radio-button value="overdue">逾期</el-radio-button>
            <el-radio-button value="today">今天</el-radio-button>
            <el-radio-button value="week">本周</el-radio-button>
          </el-radio-group>
          <el-button text size="small" :loading="loading" @click="loadAll">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="items"
        :row-class-name="rowClassName"
        style="width: 100%"
      >
        <el-table-column prop="customer_name" label="客户姓名" min-width="120">
          <template #default="{ row }">
            <span class="customer-name" @click="goCustomer(row.customer_id)">{{ row.customer_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="手机号" min-width="130">
          <template #default="{ row }">{{ row.phone || '-' }}</template>
        </el-table-column>
        <el-table-column label="上次跟进内容" min-width="220">
          <template #default="{ row }">
            <el-tooltip v-if="row.last_content" :content="row.last_content" placement="top" :show-after="400">
              <span class="content-cell">{{ truncate(row.last_content, 30) }}</span>
            </el-tooltip>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="跟进方式" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.follow_up_type)" effect="plain">
              {{ typeLabel(row.follow_up_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="showSalesman" label="归属业务员" width="120">
          <template #default="{ row }">
            {{ salesmanName(row.assigned_salesman_id) }}
          </template>
        </el-table-column>
        <el-table-column label="计划跟进时间" width="170">
          <template #default="{ row }">{{ formatTime(row.next_follow_up_at) }}</template>
        </el-table-column>
        <el-table-column label="逾期天数" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.overdue" type="danger" size="small" effect="dark">
              {{ row.overdue_days }} 天
            </el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" text size="small" @click="goCustomer(row.customer_id)">
              查看客户
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && !items.length"
        description="暂无待跟进事项"
        :image-size="90"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AlarmClock, Calendar, WarningFilled, Refresh } from '@element-plus/icons-vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'

interface ScheduleItem {
  customer_id: number
  customer_name: string
  phone: string | null
  assigned_salesman_id: number | null
  follow_up_id: number
  follow_up_type: string
  last_content: string
  next_follow_up_at: string | null
  overdue: boolean
  overdue_days: number
}

const router = useRouter()
const authStore = useAuthStore()

const scope = ref<'overdue' | 'today' | 'week'>('overdue')
const loading = ref(false)
const items = ref<ScheduleItem[]>([])
const summary = ref({ overdue: 0, today: 0, week: 0 })
const salesmenMap = ref<Record<number, string>>({})

const showSalesman = computed(() => authStore.isAdmin || authStore.isReviewer)

function typeLabel(type: string): string {
  const map: Record<string, string> = {
    phone: '电话',
    wechat: '微信',
    email: '邮件',
    meeting: '面谈',
    other: '其他',
  }
  return map[type] || type || '其他'
}

function typeTag(type: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info'> = {
    phone: 'primary',
    wechat: 'success',
    email: 'info',
    meeting: 'warning',
  }
  return map[type] || 'info'
}

/** 截断长文本 */
function truncate(text: string, len: number): string {
  if (!text) return ''
  return text.length > len ? `${text.slice(0, len)}…` : text
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

/** 时间格式化（不引 dayjs），后端返回 naive UTC，按 UTC 解析后转本地展示 */
function formatTime(time: string | null): string {
  if (!time) return '-'
  const iso = /(Z|[+-]\d{2}:?\d{2})$/.test(time) ? time : `${time}Z`
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '-'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function salesmanName(id: number | null): string {
  if (!id) return '-'
  return salesmenMap.value[id] || `用户${id}`
}

function rowClassName({ row }: { row: ScheduleItem }): string {
  return row.overdue ? 'row-overdue' : ''
}

function goCustomer(customerId: number) {
  router.push(`/admin/customers/${customerId}`)
}

function switchScope(next: 'overdue' | 'today' | 'week') {
  if (scope.value === next) return
  scope.value = next
  loadSchedule()
}

async function loadSchedule() {
  loading.value = true
  try {
    const { data } = await api.get('/api/follow-ups/schedule', {
      params: { scope: scope.value },
    })
    items.value = data.items || []
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载待跟进日程失败')
    items.value = []
  } finally {
    loading.value = false
  }
}

async function loadSummary() {
  try {
    const { data } = await api.get('/api/follow-ups/summary')
    summary.value = {
      overdue: data.overdue || 0,
      today: data.today || 0,
      week: data.week || 0,
    }
  } catch (e) {
    console.error('Failed to load follow-up summary:', e)
  }
}

async function loadSalesmen() {
  try {
    const { data } = await api.get('/api/customers/salesmen')
    const map: Record<number, string> = {}
    data.forEach((s: any) => {
      map[s.id] = s.real_name || s.username
    })
    salesmenMap.value = map
  } catch {
    salesmenMap.value = {}
  }
}

function loadAll() {
  loadSummary()
  loadSchedule()
}

onMounted(() => {
  loadSummary()
  loadSchedule()
  if (showSalesman.value) loadSalesmen()
})
</script>

<style scoped>
.follow-up-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.stat-card {
  background: #fff;
  border-radius: 14px;
  padding: 22px 24px;
  border: 1px solid #f1f5f9;
  cursor: pointer;
  transition: all 0.2s ease;
}

.stat-card:hover {
  border-color: #e2e8f0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}

.stat-card.active {
  border-color: #c7d2fe;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.08);
}

.stat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.stat-label {
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.stat-icon.overdue {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.stat-icon.today {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.stat-icon.week {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1;
  margin-bottom: 8px;
  letter-spacing: -1px;
}

.stat-card.overdue .stat-value { color: #ef4444; }
.stat-card.today .stat-value { color: #f59e0b; }
.stat-card.week .stat-value { color: #3b82f6; }

.stat-trend {
  font-size: 12px;
  color: #94a3b8;
}

.card {
  background: #fff;
  border-radius: 14px;
  border: 1px solid #f1f5f9;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid #f1f5f9;
}

.card-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.customer-name {
  color: #4f46e5;
  font-weight: 500;
  cursor: pointer;
}

.customer-name:hover {
  text-decoration: underline;
}

.content-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #475569;
  vertical-align: middle;
}

.muted {
  color: #cbd5e1;
}

:deep(.el-table .row-overdue > td.el-table__cell) {
  background: #fef2f2;
}

:deep(.el-table .row-overdue:hover > td.el-table__cell) {
  background: #fee2e2;
}

@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
