<template>
  <div class="customer-detail" v-loading="loading">
    <div class="detail-header">
      <el-page-header @back="$router.push('/admin/customers')">
        <template #content>
          <div class="header-content">
            <span class="customer-name">{{ customer?.name }}</span>
            <el-tag :type="statusType(currentApp?.status)" effect="plain" round v-if="currentApp">
              {{ currentApp.status }}
            </el-tag>
          </div>
        </template>
      </el-page-header>
      <div class="header-actions" v-if="currentApp">
        <el-button v-if="canSubmitReview" type="success" @click="handleReadyForReview">
          <el-icon><Check /></el-icon> 提交内部审核
        </el-button>
        <el-button v-if="canSubmitToInstitution" type="primary" @click="showSubmitDialog = true">
          <el-icon><Upload /></el-icon> 提交评审机构
        </el-button>
        <el-button v-if="canRecordFeedback" @click="showFeedbackDialog = true">
          <el-icon><ChatDotRound /></el-icon> 录入反馈
        </el-button>
        <el-button v-if="canReapply" type="warning" @click="handleReapply(currentApp.id)">
          <el-icon><RefreshRight /></el-icon> 二次申报
        </el-button>
        <el-button v-if="canReviseToSupplement" @click="handleReviseToSupplement(currentApp.id)">
          转为资料补充
        </el-button>
        <el-button v-if="canReviseToComplete" type="success" @click="handleReviseToComplete(currentApp.id)">
          修改后完成
        </el-button>
      </div>
    </div>

    <el-row :gutter="16" v-if="customer">
      <el-col :span="16">
        <el-tabs v-model="activeTab" class="detail-tabs">
          <el-tab-pane label="基本信息" name="basic">
            <el-descriptions :column="2" border class="info-descriptions">
              <el-descriptions-item label="姓名">{{ customer.name }}</el-descriptions-item>
              <el-descriptions-item label="身份证号">{{ customer.id_number }}</el-descriptions-item>
              <el-descriptions-item label="手机号">{{ customer.phone || '-' }}</el-descriptions-item>
              <el-descriptions-item label="学历">{{ customer.education || '-' }}</el-descriptions-item>
              <el-descriptions-item label="现职称">{{ customer.current_title || '-' }}</el-descriptions-item>
              <el-descriptions-item label="取得年份">{{ customer.current_title_year || '-' }}</el-descriptions-item>
              <el-descriptions-item label="工作单位">{{ customer.work_unit || '-' }}</el-descriptions-item>
              <el-descriptions-item label="职务">{{ customer.position || '-' }}</el-descriptions-item>
              <el-descriptions-item label="工作年限">{{ customer.professional_years ? customer.professional_years + '年' : '-'
                }}</el-descriptions-item>
            </el-descriptions>

            <div v-if="projectExperiences.length" style="margin-top: 20px">
              <h4 class="section-title">项目经历</h4>
              <el-table :data="projectExperiences" border>
                <el-table-column prop="name" label="项目名称" />
                <el-table-column prop="start_date" label="起始" width="100" />
                <el-table-column prop="end_date" label="结束" width="100" />
                <el-table-column prop="role" label="角色" width="120" />
                <el-table-column prop="description" label="描述" show-overflow-tooltip />
              </el-table>
            </div>
          </el-tab-pane>

          <el-tab-pane label="材料管理" name="materials" v-if="currentAppId">
            <MaterialUpload :application-id="currentAppId" :can-submit="canSubmitReview"
              @submit-review="handleReadyForReview" />
          </el-tab-pane>

          <el-tab-pane label="审核记录" name="reviews" v-if="currentAppId">
            <el-timeline>
              <el-timeline-item v-for="review in reviews" :key="review.id"
                :timestamp="formatDate(review.created_at)" placement="top"
                :type="review.result === '通过' ? 'success' : 'danger'">
                <el-card class="review-card" shadow="never">
                  <div class="review-header">
                    <el-tag :type="review.result === '通过' ? 'success' : 'danger'" size="small" round>
                      {{ review.result }}
                    </el-tag>
                    <span class="review-meta">审核员 #{{ review.reviewer_id }}</span>
                  </div>
                  <p v-if="review.issue_type" class="review-issue">
                    <el-icon><WarningFilled /></el-icon> {{ review.issue_type }}
                  </p>
                  <p v-if="review.description" class="review-desc">{{ review.description }}</p>
                </el-card>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-if="!reviews.length" description="暂无审核记录" :image-size="60" />
          </el-tab-pane>

          <el-tab-pane label="操作日志" name="logs" v-if="currentAppId">
            <el-timeline>
              <el-timeline-item v-for="log in logs" :key="log.id" :timestamp="formatDate(log.created_at)"
                placement="top">
                <el-card class="log-card" shadow="never">
                  <p class="log-action">{{ log.action }}</p>
                  <p v-if="log.detail" class="log-detail">{{ log.detail }}</p>
                  <p v-if="log.actor_name" class="log-actor">{{ log.actor_name }}</p>
                </el-card>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-if="!logs.length" description="暂无操作日志" :image-size="60" />
          </el-tab-pane>
          
          <el-tab-pane label="跟进记录" name="followups">
            <FollowUpTimeline :customer-id="customer?.id || 0" />
          </el-tab-pane>
        </el-tabs>
      </el-col>

      <el-col :span="8">
        <el-card class="sidebar-card">
          <template #header>申报批次</template>
          <div v-for="app in applications" :key="app.id" class="app-item"
            :class="{ active: currentAppId === app.id }" @click="selectApp(app)">
            <div class="app-item-header">
              <span class="app-batch">{{ app.batch_number }}</span>
              <el-tag :type="statusType(app.status)" size="small" round>{{ app.status }}</el-tag>
            </div>
            <div class="app-item-info">
              <span>{{ app.professional_category || '未指定专业' }} / {{ app.title_level || '未指定级别' }}</span>
              <span class="app-materials">{{ app.materials_count || 0 }} 份材料</span>
            </div>
          </div>
          <el-empty v-if="!applications.length" description="暂无申报批次" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="showSubmitDialog" title="提交至评审机构" width="420px">
      <el-form label-position="top">
        <el-form-item label="报送机构名称">
          <el-input v-model="institutionName" placeholder="如：XX市人力资源和社会保障局" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSubmitDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmitToInstitution">确认提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showFeedbackDialog" title="录入机构反馈" width="480px">
      <el-form label-position="top">
        <el-form-item label="反馈结果">
          <el-radio-group v-model="feedbackType">
            <el-radio value="通过" border>通过</el-radio>
            <el-radio value="不通过" border>不通过</el-radio>
            <el-radio value="返修" border>返修</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="反馈意见">
          <el-input v-model="feedbackContent" type="textarea" :rows="4" placeholder="请输入机构反馈意见" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showFeedbackDialog = false">取消</el-button>
        <el-button type="primary" @click="handleFeedback">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import MaterialUpload from './MaterialUpload.vue'
import FollowUpTimeline from '../components/FollowUpTimeline.vue'

const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const customer = ref<any>(null)
const applications = ref<any[]>([])
const reviews = ref<any[]>([])
const logs = ref<any[]>([])
const activeTab = ref('basic')
const currentAppId = ref<number | null>(null)

const showSubmitDialog = ref(false)
const showFeedbackDialog = ref(false)
const institutionName = ref('')
const feedbackType = ref('通过')
const feedbackContent = ref('')

const currentApp = computed(() => applications.value.find(a => a.id === currentAppId.value) || null)

const projectExperiences = computed(() => {
  if (!customer.value?.project_experiences) return []
  try { return JSON.parse(customer.value.project_experiences) } catch { return [] }
})

const isSalesman = computed(() => authStore.isSalesman || authStore.isAdmin)

function canOperate() {
  return authStore.isSalesman || authStore.isAdmin
}

const canSubmitReview = computed(() => {
  return isSalesman.value && currentApp.value && ['初次申报', '资料补充', '二次申报'].includes(currentApp.value.status)
})
const canSubmitToInstitution = computed(() => {
  return isSalesman.value && currentApp.value?.status === '完成资料'
})
const canRecordFeedback = computed(() => {
  return isSalesman.value && currentApp.value?.status === '提交评审机构审核'
})
const canReapply = computed(() => {
  return isSalesman.value && currentApp.value?.status === '不通过'
})
const canReviseToSupplement = computed(() => {
  return isSalesman.value && currentApp.value?.status === '返修'
})
const canReviseToComplete = computed(() => {
  return isSalesman.value && currentApp.value?.status === '返修'
})

function statusType(status: string) {
  const map: Record<string, string> = {
    '初次申报': '', '资料补充': 'warning', '完成资料': 'success',
    '提交评审机构审核': '', '返修': 'danger', '通过': 'success',
    '不通过': 'danger', '二次申报': '',
  }
  return map[status] || 'info'
}

function formatDate(d: string) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN')
}

watch(() => route.params.id, () => loadData(), { immediate: true })
watch(activeTab, (tab) => {
  if (tab === 'reviews' && currentAppId.value) loadReviews(currentAppId.value)
  if (tab === 'logs' && currentAppId.value) loadLogs(currentAppId.value)
})

async function loadData() {
  loading.value = true
  try {
    const { data } = await api.get(`/api/customers/${route.params.id}`)
    customer.value = data
    applications.value = data.applications || []
    if (applications.value.length && !currentAppId.value) {
      currentAppId.value = applications.value[0].id
    }
  } finally {
    loading.value = false
  }
}

function selectApp(app: any) {
  currentAppId.value = app.id
  reviews.value = []
  logs.value = []
}

async function loadReviews(appId: number) {
  const { data } = await api.get(`/api/reviews/application/${appId}`)
  reviews.value = data
}

async function loadLogs(appId: number) {
  const { data } = await api.get(`/api/feedback/application/${appId}/logs`)
  logs.value = data
}

async function handleReadyForReview() {
  if (!currentAppId.value) return
  try {
    await api.put(`/api/applications/${currentAppId.value}`, { status: '完成资料' })
    ElMessage.success('已提交内部审核，状态变更为完成资料')
    loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交失败')
  }
}

async function handleReapply(appId: number) {
  try {
    await ElMessageBox.confirm('确认基于此批次发起二次申报？', '二次申报')
    await api.post(`/api/applications/${appId}/reapply`)
    ElMessage.success('二次申报已创建')
    loadData()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || '操作失败')
    }
  }
}

async function handleSubmitToInstitution() {
  try {
    await api.post(`/api/applications/${currentApp.value.id}/submit-to-institution`, {
      institution_name: institutionName.value,
    })
    ElMessage.success('已提交至评审机构')
    showSubmitDialog.value = false
    loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交失败')
  }
}

async function handleFeedback() {
  if (!feedbackContent.value) {
    ElMessage.warning('请填写反馈意见')
    return
  }
  const formData = new FormData()
  formData.append('application_id', String(currentApp.value.id))
  formData.append('feedback_type', feedbackType.value)
  formData.append('content', feedbackContent.value)
  try {
    await api.post('/api/feedback/', formData)
    ElMessage.success('反馈已录入')
    showFeedbackDialog.value = false
    loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function handleReviseToSupplement(appId: number) {
  try {
    await api.put(`/api/applications/${appId}`, { status: '资料补充' })
    ElMessage.success('已转为资料补充')
    loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function handleReviseToComplete(appId: number) {
  try {
    await api.put(`/api/applications/${appId}`, { status: '完成资料' })
    ElMessage.success('已回到完成资料状态')
    loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}
</script>

<style scoped>
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.header-content {
  display: flex;
  align-items: center;
  gap: 12px;
}
.customer-name {
  font-size: 20px;
  font-weight: 700;
}
.header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.detail-tabs {
  background: #fff;
  border-radius: 12px;
  padding: 0 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.info-descriptions {
  margin-top: 8px;
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 12px;
}
.sidebar-card {
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.app-item {
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid transparent;
  margin-bottom: 8px;
}
.app-item:hover {
  background: #f8fafc;
}
.app-item.active {
  background: #f0f0ff;
  border-color: #6366f1;
}
.app-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.app-batch {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}
.app-item-info {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #94a3b8;
}
.app-materials {
  color: #6366f1;
  font-weight: 500;
}
.review-card, .log-card {
  border: none;
  background: #f8fafc;
}
.review-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.review-meta {
  color: #94a3b8;
  font-size: 12px;
}
.review-issue {
  color: #ef4444;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 4px 0;
}
.review-desc {
  color: #475569;
  font-size: 13px;
  margin: 0;
}
.log-action {
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 4px;
}
.log-detail {
  color: #64748b;
  font-size: 13px;
  margin: 0 0 4px;
}
.log-actor {
  color: #94a3b8;
  font-size: 12px;
  margin: 0;
}
</style>
