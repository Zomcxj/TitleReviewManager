<template>
  <div class="dashboard-page">
    <!-- Stats Cards -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">客户总数</span>
          <div class="stat-icon customers">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
              <circle cx="9" cy="7" r="4"></circle>
              <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
              <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
            </svg>
          </div>
        </div>
        <div class="stat-value">{{ stats.total_customers }}</div>
        <div class="stat-trend up">较昨日</div>
      </div>
      
      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">申报总数</span>
          <div class="stat-icon applications">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
          </div>
        </div>
        <div class="stat-value">{{ stats.total_applications }}</div>
        <div class="stat-trend up">较昨日</div>
      </div>
      
      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">今日新增</span>
          <div class="stat-icon today">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="20" x2="12" y2="10"></line>
              <line x1="18" y1="20" x2="18" y2="4"></line>
              <line x1="6" y1="20" x2="6" y2="16"></line>
            </svg>
          </div>
        </div>
        <div class="stat-value">{{ stats.today_new }}</div>
        <div class="stat-trend neutral">今日数据</div>
      </div>
      
      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">本周新增</span>
          <div class="stat-icon week">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
            </svg>
          </div>
        </div>
        <div class="stat-value">{{ stats.week_new }}</div>
        <div class="stat-trend up">较上周</div>
      </div>
    </div>

    <!-- 今日待办 -->
    <div class="card workbench-card" v-loading="workbenchLoading">
      <div class="card-header">
        <h3>今日待办</h3>
        <span class="card-hint">按角色过滤，点条目可跳转处理</span>
      </div>
      <div class="workbench-metrics">
        <div class="wb-metric" :class="{ danger: (workbench.summary?.follow_ups_overdue || 0) > 0 }" @click="go('/admin/follow-ups')">
          <div class="wb-value">{{ workbench.summary?.follow_ups_overdue || 0 }}</div>
          <div class="wb-label">跟进逾期</div>
        </div>
        <div class="wb-metric" @click="go('/admin/follow-ups')">
          <div class="wb-value">{{ workbench.summary?.follow_ups_today || 0 }}</div>
          <div class="wb-label">今天待跟进</div>
        </div>
        <div
          class="wb-metric"
          :class="{ danger: (workbench.summary?.overdue_reviews || 0) > 0 }"
          @click="go(authStore.isReviewer || authStore.isAdmin ? '/admin/reviews' : '/admin/customers')"
        >
          <div class="wb-value">{{ workbench.summary?.pending_reviews || 0 }}</div>
          <div class="wb-label">待审核批次</div>
        </div>
        <div class="wb-metric" :class="{ danger: (workbench.summary?.overdue_deadlines || 0) > 0 }" @click="go('/admin/customers')">
          <div class="wb-value">{{ workbench.summary?.overdue_deadlines || 0 }}</div>
          <div class="wb-label">申报已截止</div>
        </div>
        <div
          v-if="!authStore.isReviewer"
          class="wb-metric"
          @click="go('/admin/finance')"
        >
          <div class="wb-value">{{ workbench.summary?.pending_payments || 0 }}</div>
          <div class="wb-label">待收款</div>
        </div>
      </div>
      <div class="workbench-lists">
        <div class="wb-list">
          <div class="wb-list-title">跟进</div>
          <div v-if="workbench.follow_ups?.length" class="wb-items">
            <div
              v-for="item in workbench.follow_ups.slice(0, 5)"
              :key="'fu-' + item.follow_up_id"
              class="wb-item"
              @click="go(`/admin/customers/${item.customer_id}`)"
            >
              <span class="wb-name">{{ item.customer_name }}</span>
              <el-tag v-if="item.overdue" type="danger" size="small" effect="plain">逾期 {{ item.overdue_days }} 天</el-tag>
              <span v-else class="wb-meta">{{ formatShort(item.next_follow_up_at) }}</span>
            </div>
          </div>
          <div v-else class="wb-empty">暂无待跟进</div>
        </div>
        <div class="wb-list">
          <div class="wb-list-title">审核积压</div>
          <div v-if="workbench.reviews?.length" class="wb-items">
            <div
              v-for="item in workbench.reviews.slice(0, 5)"
              :key="'rv-' + item.application_id"
              class="wb-item"
              @click="go(authStore.isReviewer || authStore.isAdmin ? '/admin/reviews' : `/admin/customers/${item.customer_id}`)"
            >
              <span class="wb-name">{{ item.customer_name }}</span>
              <el-tag v-if="item.overdue" type="danger" size="small" effect="plain">超时</el-tag>
              <span class="wb-meta">{{ item.pending_materials }} 份待审</span>
            </div>
          </div>
          <div v-else class="wb-empty">暂无待审材料</div>
        </div>
        <div class="wb-list">
          <div class="wb-list-title">申报截止</div>
          <div v-if="workbench.deadlines?.length" class="wb-items">
            <div
              v-for="item in workbench.deadlines.slice(0, 5)"
              :key="'dl-' + item.application_id"
              class="wb-item"
              @click="go(`/admin/customers/${item.customer_id}`)"
            >
              <span class="wb-name">{{ item.customer_name }}</span>
              <el-tag v-if="item.overdue" type="danger" size="small" effect="plain">已逾期</el-tag>
              <span class="wb-meta">{{ formatShort(item.cycle_deadline) }}</span>
            </div>
          </div>
          <div v-else class="wb-empty">近 7 天无截止</div>
        </div>
      </div>
    </div>
    
    <!-- Content Grid -->
    <div class="content-grid">
      <div class="card status-card">
        <div class="card-header">
          <h3>申报状态分布</h3>
        </div>
        <div class="status-table">
          <div 
            v-for="item in statusData" 
            :key="item.status" 
            class="status-row"
          >
            <div class="status-name">
              <span class="status-dot" :class="getStatusClass(item.status)"></span>
              <span>{{ item.status }}</span>
            </div>
            <div class="status-count">{{ item.count }}</div>
          </div>
        </div>
      </div>
      
      <div class="card actions-card">
        <div class="card-header">
          <h3>快速操作</h3>
        </div>
        <div class="actions-grid">
          <router-link to="/admin/customers" class="action-item">
            <div class="action-icon customers">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                <circle cx="9" cy="7" r="4"></circle>
              </svg>
            </div>
            <span>客户管理</span>
          </router-link>
          
          <router-link to="/admin/reviews" v-if="authStore.isReviewer || authStore.isAdmin" class="action-item">
            <div class="action-icon reviews">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="9 11 12 14 22 4"></polyline>
                <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
              </svg>
            </div>
            <span>审核工作台</span>
          </router-link>
          
          <router-link to="/admin/public-pool" v-if="authStore.isSalesman || authStore.isAdmin" class="action-item">
            <div class="action-icon pool">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <path d="M8 14s1.5 2 4 2 4-2 4-2"></path>
                <line x1="9" y1="9" x2="9.01" y2="9"></line>
                <line x1="15" y1="9" x2="15.01" y2="9"></line>
              </svg>
            </div>
            <span>公海池</span>
          </router-link>
          
          <router-link to="/admin/audit-logs" v-if="authStore.isAdmin" class="action-item">
            <div class="action-icon logs">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="8" y1="6" x2="21" y2="6"></line>
                <line x1="8" y1="12" x2="21" y2="12"></line>
                <line x1="8" y1="18" x2="21" y2="18"></line>
                <line x1="3" y1="6" x2="3.01" y2="6"></line>
                <line x1="3" y1="12" x2="3.01" y2="12"></line>
                <line x1="3" y1="18" x2="3.01" y2="18"></line>
              </svg>
            </div>
            <span>审计日志</span>
          </router-link>
        </div>
      </div>
    </div>

    <!-- 转化漏斗 + 退回统计 -->
    <div class="analytics-grid">
      <!-- 转化漏斗 -->
      <div class="card funnel-card">
        <div class="card-header">
          <h3>转化漏斗</h3>
          <span class="card-hint">近 {{ funnel.period_days || 180 }} 天</span>
        </div>
        <div class="card-body" v-loading="funnelLoading">
          <template v-if="funnel.total_customers">
            <div class="funnel-list">
              <div v-for="(stage, idx) in funnelStages" :key="stage.name" class="funnel-row">
                <div class="funnel-label">{{ stage.name }}</div>
                <div class="funnel-bar-wrap">
                  <div
                    class="funnel-bar"
                    :class="'stage-' + idx"
                    :style="{ width: Math.max(stage.rate_from_start || 0, stage.count > 0 ? 4 : 0) + '%' }"
                  ></div>
                </div>
                <div class="funnel-count">{{ stage.count }}</div>
                <div class="funnel-rate">
                  <span class="rate-from-prev">{{ stage.rate_from_prev === null || stage.rate_from_prev === undefined ? '-' : stage.rate_from_prev + '%' }}</span>
                  <span class="rate-from-start">累计 {{ stage.rate_from_start }}%</span>
                </div>
              </div>
            </div>
            <div class="funnel-footer">
              <div class="funnel-summary">
                <span class="summary-label">整体转化率</span>
                <span class="summary-value">{{ funnel.overall_rate ?? 0 }}%</span>
              </div>
              <div v-if="funnel.drop_off" class="funnel-dropoff">
                流失最多：{{ funnel.drop_off.from_stage }} → {{ funnel.drop_off.to_stage }}，
                流失 <b>{{ funnel.drop_off.lost }}</b> 人（{{ funnel.drop_off.lost_rate }}%）
              </div>
              <div v-else class="funnel-dropoff muted">暂无流失数据</div>
            </div>
          </template>
          <el-empty v-else-if="!funnelLoading" description="暂无转化数据" :image-size="70" />
        </div>
      </div>

      <!-- 退回原因统计 -->
      <div class="card rejection-card">
        <div class="card-header">
          <h3>材料退回统计</h3>
          <span class="card-hint">近 {{ rejection.period_days || 90 }} 天</span>
        </div>
        <div class="card-body" v-loading="rejectionLoading">
          <template v-if="rejection.total_rejected > 0">
            <div class="rejection-metrics">
              <div class="metric">
                <div class="metric-value">{{ rejection.total_reviews }}</div>
                <div class="metric-label">审核总数</div>
              </div>
              <div class="metric">
                <div class="metric-value danger">{{ rejection.total_rejected }}</div>
                <div class="metric-label">退回总数</div>
              </div>
              <div class="metric">
                <div class="metric-value" :class="{ danger: rejection.reject_rate >= 30 }">
                  {{ rejection.reject_rate }}%
                </div>
                <div class="metric-label">退回率</div>
              </div>
            </div>

            <div class="rejection-section">
              <div class="section-title">按材料类别</div>
              <el-table :data="rejection.by_category" size="small" style="width: 100%">
                <el-table-column prop="category" label="类别" min-width="110" />
                <el-table-column prop="rejected" label="退回" width="70" align="center" />
                <el-table-column prop="total" label="总数" width="70" align="center" />
                <el-table-column label="退回率" width="90" align="right">
                  <template #default="{ row }">
                    <span :class="{ 'rate-danger': row.rate >= 30 }">{{ row.rate }}%</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div class="rejection-section">
              <div class="section-title">按问题类型</div>
              <el-table :data="rejection.by_issue_type" size="small" style="width: 100%">
                <el-table-column prop="issue_type" label="问题类型" min-width="110" />
                <el-table-column prop="count" label="次数" width="70" align="center" />
                <el-table-column label="占比" width="90" align="right">
                  <template #default="{ row }">{{ row.rate }}%</template>
                </el-table-column>
              </el-table>
            </div>
          </template>
          <el-empty v-else-if="!rejectionLoading" description="暂无退回记录" :image-size="70" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const router = useRouter()
function go(path: string) {
  router.push(path)
}

const authStore = useAuthStore()
const stats = ref({
  total_customers: 0,
  total_applications: 0,
  today_new: 0,
  week_new: 0,
  status_distribution: {},
})

const statusData = computed(() => {
  return Object.entries(stats.value.status_distribution || {}).map(([name, count]) => ({
    status: name,
    count: count as number,
  }))
})

function getStatusClass(status: string) {
  const map: Record<string, string> = {
    '初次申报': 'initial',
    '资料补充': 'supplement',
    '完成资料': 'completed',
    '提交评审机构审核': 'submitted',
    '返修': 'revise',
    '通过': 'approved',
    '不通过': 'rejected',
    '二次申报': 'reapply',
  }
  return map[status] || 'default'
}

async function loadStats() {
  try {
    const { data } = await api.get('/api/dashboard/stats')
    stats.value = data
  } catch (e) {
    console.error('Failed to load stats:', e)
  }
}

// ---------- 转化漏斗 ----------
interface FunnelStage {
  name: string
  count: number
  rate_from_prev: number | null
  rate_from_start: number
}

interface FunnelData {
  period_days: number
  total_customers: number
  stages: FunnelStage[]
  drop_off: { from_stage: string; to_stage: string; lost: number; lost_rate: number } | null
  overall_rate: number
}

const funnelLoading = ref(false)
const funnel = ref<Partial<FunnelData>>({})
const funnelStages = computed<FunnelStage[]>(() => funnel.value.stages || [])

async function loadFunnel() {
  funnelLoading.value = true
  try {
    const { data } = await api.get('/api/dashboard/funnel', { params: { days: 180 } })
    funnel.value = data
  } catch (e) {
    console.error('Failed to load funnel:', e)
    funnel.value = {}
  } finally {
    funnelLoading.value = false
  }
}

// ---------- 退回统计 ----------
interface RejectionCategory {
  category: string
  total: number
  rejected: number
  rate: number
}

interface RejectionIssue {
  issue_type: string
  count: number
  rate: number
}

interface RejectionData {
  period_days: number
  total_reviews: number
  total_rejected: number
  reject_rate: number
  by_category: RejectionCategory[]
  by_issue_type: RejectionIssue[]
}

const rejectionLoading = ref(false)
const rejection = ref<Partial<RejectionData>>({
  total_reviews: 0,
  total_rejected: 0,
  reject_rate: 0,
  by_category: [],
  by_issue_type: [],
})

async function loadRejectionStats() {
  rejectionLoading.value = true
  try {
    const { data } = await api.get('/api/dashboard/rejection-stats', { params: { days: 90 } })
    rejection.value = data
  } catch (e) {
    console.error('Failed to load rejection stats:', e)
    rejection.value = { total_reviews: 0, total_rejected: 0, reject_rate: 0, by_category: [], by_issue_type: [] }
  } finally {
    rejectionLoading.value = false
  }
}

interface WorkbenchSummary {
  follow_ups_today: number
  follow_ups_overdue: number
  pending_reviews: number
  overdue_reviews: number
  upcoming_deadlines: number
  overdue_deadlines: number
  pending_payments: number
  pending_unpaid_amount: number
}

const workbenchLoading = ref(false)
const workbench = ref<{
  summary?: Partial<WorkbenchSummary>
  follow_ups?: any[]
  reviews?: any[]
  deadlines?: any[]
}>({})

function formatShort(value?: string | null) {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

async function loadWorkbench() {
  workbenchLoading.value = true
  try {
    const { data } = await api.get('/api/dashboard/workbench')
    workbench.value = data
  } catch (e) {
    console.error('Failed to load workbench:', e)
    workbench.value = {}
  } finally {
    workbenchLoading.value = false
  }
}

onMounted(() => {
  loadStats()
  loadWorkbench()
  loadFunnel()
  loadRejectionStats()
})
</script>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.stat-card {
  background: #fff;
  border-radius: 14px;
  padding: 24px;
  border: 1px solid #f1f5f9;
  transition: all 0.2s ease;
}

.stat-card:hover {
  border-color: #e2e8f0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}

.stat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
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
}

.stat-icon.customers {
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
}

.stat-icon.applications {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
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

.stat-trend {
  font-size: 12px;
  color: #94a3b8;
}

.stat-trend.up {
  color: #10b981;
}

.stat-trend.down {
  color: #ef4444;
}

.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.card {
  background: #fff;
  border-radius: 14px;
  border: 1px solid #f1f5f9;
  overflow: hidden;
}

.card-header {
  padding: 20px 24px;
  border-bottom: 1px solid #f1f5f9;
}

.card-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.status-table {
  padding: 8px 16px;
}

.status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 8px;
  border-bottom: 1px solid #f8fafc;
}

.status-row:last-child {
  border-bottom: none;
}

.status-name {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #374151;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-dot.initial { background: #94a3b8; }
.status-dot.supplement { background: #f59e0b; }
.status-dot.completed { background: #10b981; }
.status-dot.submitted { background: #3b82f6; }
.status-dot.revise { background: #f97316; }
.status-dot.approved { background: #10b981; }
.status-dot.rejected { background: #ef4444; }
.status-dot.reapply { background: #8b5cf6; }
.status-dot.default { background: #94a3b8; }

.status-count {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}

.actions-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 20px;
}

.action-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 10px;
  background: #f8fafc;
  text-decoration: none;
  color: #374151;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.action-item:hover {
  background: #f1f5f9;
  border-color: #e2e8f0;
  transform: translateY(-1px);
}

.action-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-icon.customers {
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
}

.action-icon.reviews {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.action-icon.pool {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.action-icon.logs {
  background: rgba(107, 114, 128, 0.1);
  color: #6b7280;
}

.workbench-card .card-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.workbench-metrics {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  padding: 16px 24px 8px;
}

.wb-metric {
  background: #f8fafc;
  border-radius: 10px;
  padding: 14px 12px;
  text-align: center;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s ease;
}

.wb-metric:hover {
  border-color: #e2e8f0;
  transform: translateY(-1px);
}

.wb-metric.danger .wb-value {
  color: #ef4444;
}

.wb-value {
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}

.wb-label {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
}

.workbench-lists {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 8px 24px 20px;
}

.wb-list-title {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 8px;
}

.wb-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f8fafc;
  cursor: pointer;
  font-size: 13px;
}

.wb-item:hover .wb-name {
  color: #6366f1;
}

.wb-name {
  font-weight: 600;
  color: #0f172a;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wb-meta {
  color: #94a3b8;
  font-size: 12px;
}

.wb-empty {
  font-size: 12px;
  color: #cbd5e1;
  padding: 8px 0;
}

@media (max-width: 1024px) {
  .workbench-metrics,
  .workbench-lists {
    grid-template-columns: 1fr;
  }
}

/* ---------- 转化漏斗 + 退回统计 ---------- */
.analytics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.card-hint {
  font-size: 12px;
  color: #94a3b8;
}

.card-body {
  padding: 20px 24px;
}

.funnel-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.funnel-row {
  display: grid;
  grid-template-columns: 76px 1fr 56px 108px;
  align-items: center;
  gap: 12px;
}

.funnel-label {
  font-size: 13px;
  color: #374151;
  font-weight: 500;
}

.funnel-bar-wrap {
  height: 22px;
  background: #f1f5f9;
  border-radius: 6px;
  overflow: hidden;
}

.funnel-bar {
  height: 100%;
  border-radius: 6px;
  transition: width 0.4s ease;
  min-width: 2px;
}

.funnel-bar.stage-0 { background: linear-gradient(90deg, #6366f1, #818cf8); }
.funnel-bar.stage-1 { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.funnel-bar.stage-2 { background: linear-gradient(90deg, #0ea5e9, #38bdf8); }
.funnel-bar.stage-3 { background: linear-gradient(90deg, #10b981, #34d399); }

.funnel-count {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  text-align: right;
}

.funnel-rate {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.3;
}

.rate-from-prev {
  font-size: 12px;
  color: #475569;
  font-weight: 500;
}

.rate-from-start {
  font-size: 11px;
  color: #94a3b8;
}

.funnel-footer {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.funnel-summary {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.summary-label {
  font-size: 13px;
  color: #64748b;
}

.summary-value {
  font-size: 22px;
  font-weight: 700;
  color: #10b981;
}

.funnel-dropoff {
  font-size: 13px;
  color: #64748b;
}

.funnel-dropoff b {
  color: #ef4444;
}

.funnel-dropoff.muted {
  color: #cbd5e1;
}

.rejection-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.metric {
  background: #f8fafc;
  border-radius: 10px;
  padding: 14px 12px;
  text-align: center;
}

.metric-value {
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}

.metric-value.danger {
  color: #ef4444;
}

.metric-label {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
}

.rejection-section {
  margin-bottom: 18px;
}

.rejection-section:last-child {
  margin-bottom: 0;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 8px;
}

.rate-danger {
  color: #ef4444;
  font-weight: 600;
}

@media (max-width: 1024px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .content-grid {
    grid-template-columns: 1fr;
  }

  .analytics-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>