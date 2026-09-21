<template>
  <div class="review-workspace">
    <div class="review-top">
      <div class="review-top-left">
        <h3 class="section-title">审核工作台</h3>
        <p class="section-desc">按审核时效排序的待审队列，只显示仍有待审核材料的批次</p>
      </div>
      <div class="review-filters">
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 140px" @change="loadPendingApps">
          <el-option label="完成资料" value="完成资料" />
          <el-option label="资料补充" value="资料补充" />
          <el-option label="二次申报" value="二次申报" />
        </el-select>
      </div>
    </div>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="9">
        <el-card class="panel">
          <template #header>
            <div class="panel-title">
              <el-icon><List /></el-icon>
              待审核列表
              <el-badge :value="pendingApps.length" :max="99" class="count-badge" />
            </div>
          </template>
          <div v-for="app in pendingApps" :key="app.application_id" class="app-row"
            :class="{ active: selectedApp?.application_id === app.application_id, overdue: app.overdue }"
            @click="selectApp(app)">
            <div class="app-row-main">
              <div class="app-avatar">{{ app.customer_name?.charAt(0) || '?' }}</div>
              <div class="app-row-info">
                <div class="app-row-name">{{ app.customer_name }}</div>
                <div class="app-row-meta">
                  {{ app.batch_number || '-' }} · {{ app.pending_materials || 0 }} 份待审
                  <span v-if="app.overdue" class="sla-overdue">超时 {{ formatHours(app.overdue_hours) }}</span>
                  <span v-else-if="app.hours_remaining != null" class="sla-remain">剩余 {{ formatHours(app.hours_remaining) }}</span>
                </div>
              </div>
              <el-tag :type="statusType(app.status)" size="small" round>
                {{ app.status }}
              </el-tag>
            </div>
          </div>
          <el-empty v-if="!pendingApps.length" description="暂无待审核申报" :image-size="60" />
        </el-card>
      </el-col>

      <el-col :span="15" v-if="selectedApp">
        <el-card class="panel">
          <template #header>
            <div class="review-header">
              <div class="review-title">
                <span class="review-name">{{ selectedApp.customer_name }}</span>
                <span class="review-batch">{{ selectedApp.batch_number }}</span>
              </div>
              <div v-if="materials.length" class="review-actions">
                <span class="review-hint">逐项审核：通过或退回每份材料</span>
              </div>
            </div>
          </template>

          <el-table :data="materials" style="width: 100%"
            v-loading="loadingMaterials" row-key="id">
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.category }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="filename-text">{{ row.filename }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="auditType(row.audit_status)" size="small" round>{{ row.audit_status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button type="primary" text size="small" @click="downloadFile(row.id)">下载</el-button>
                <el-button type="success" text size="small" @click="handleSingleApprove(row)">通过</el-button>
                <el-button type="danger" text size="small" @click="handleSingleReject(row)">退回</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="selectedAppReviews.length" class="review-history">
            <h4 class="history-title">审核历史</h4>
            <el-timeline>
              <el-timeline-item v-for="r in selectedAppReviews" :key="r.id"
                :timestamp="formatDate(r.created_at)" placement="top"
                :type="r.result === '通过' ? 'success' : 'danger'">
                <span class="history-item">{{ r.result }}</span>
                <span v-if="r.issue_type" class="history-issue">{{ r.issue_type }}</span>
                <span v-if="r.description" class="history-desc">{{ r.description }}</span>
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="reviewDialogVisible" title="退回材料" width="480px">
      <div v-if="currentMaterial" class="dialog-material-info">
        <el-tag size="small">{{ currentMaterial.category }}</el-tag>
        <span class="dialog-filename">{{ currentMaterial.filename }}</span>
      </div>
      <el-form label-position="top" style="margin-top: 12px">
        <el-form-item label="问题类型">
          <el-select v-model="reviewForm.issue_type" placeholder="选择问题类型" style="width: 100%">
            <el-option label="材料缺失" value="材料缺失" />
            <el-option label="不清晰" value="不清晰" />
            <el-option label="内容错误" value="内容错误" />
            <el-option label="已过期" value="已过期" />
            <el-option label="内容需修改" value="内容需修改" />
          </el-select>
        </el-form-item>
        <el-form-item label="详细说明">
          <el-input v-model="reviewForm.description" type="textarea" :rows="4"
            placeholder="请详细描述问题及修改要求，业务员将根据此说明联系客户" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialogVisible = false">取消</el-button>
        <el-button type="danger" @click="submitReview">确认退回</el-button>
      </template>
    </el-dialog>


  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'
import { ElMessage } from 'element-plus'
import { List } from '@element-plus/icons-vue'

const router = useRouter()
const authStore = useAuthStore()

// Role check: only reviewer and admin can access (after user is loaded)
async function checkAccess() {
  if (!authStore.user) {
    await authStore.fetchUser()
  }
  if (!authStore.isReviewer && !authStore.isAdmin) {
    ElMessage.error('只有审核员和管理员可以访问审核工作台')
    router.push('/admin/dashboard')
  }
}

const loadingList = ref(false)
const loadingMaterials = ref(false)
const pendingApps = ref<any[]>([])
const materials = ref<any[]>([])
const selectedApp = ref<any>(null)
const selectedAppReviews = ref<any[]>([])
const reviewDialogVisible = ref(false)
const currentMaterial = ref<any>(null)
const reviewForm = ref({ issue_type: '', description: '' })
const filterStatus = ref('')

function statusType(s: string) {
  return s === '资料补充' ? 'warning' : ''
}
function auditType(s: string) {
  return s === '已通过' ? 'success' : s === '已标记问题' ? 'danger' : 'info'
}
function formatDate(d: string) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN')
}

function formatHours(hours: number | null | undefined) {
  if (hours == null) return '-'
  const abs = Math.abs(Number(hours))
  if (abs < 1) return `${Math.round(abs * 60)} 分钟`
  if (abs < 48) return `${Math.round(abs)} 小时`
  return `${Math.round(abs / 24)} 天`
}

async function loadPendingApps() {
  loadingList.value = true
  try {
    const { data } = await api.get('/api/reviews/pending', {
      params: filterStatus.value ? { status: filterStatus.value } : {},
    })
    pendingApps.value = data.items || []
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载待审核列表失败')
    pendingApps.value = []
  } finally {
    loadingList.value = false
  }
}

async function selectApp(app: any) {
  selectedApp.value = app
  const appId = app.application_id
  loadingMaterials.value = true
  try {
    const { data } = await api.get(`/api/applications/${appId}/materials/`)
    const allMats = data.items || data
    materials.value = (Array.isArray(allMats) ? allMats : []).filter(
      (m: any) => !m.audit_status || m.audit_status === '待审核' || m.audit_status === ''
    )
    const { data: reviewData } = await api.get(`/api/reviews/application/${appId}`)
    selectedAppReviews.value = reviewData
  } finally {
    loadingMaterials.value = false
  }
}

function downloadFile(materialId: number) {
  const appId = selectedApp.value?.application_id
  window.open(`/api/applications/${appId}/materials/file/${materialId}`, '_blank')
}

async function handleSingleApprove(material: any) {
  const appId = selectedApp.value.application_id
  try {
    const formData = new FormData()
    formData.append('material_id', String(material.id))
    formData.append('application_id', String(appId))
    formData.append('result', '通过')
    formData.append('description', '审核通过')
    await api.post('/api/reviews/', formData)
    ElMessage.success('已通过')
    materials.value = materials.value.filter((m: any) => m.id !== material.id)
    if (!materials.value.length) {
      pendingApps.value = pendingApps.value.filter((app: any) => app.application_id !== appId)
      selectedApp.value = null
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

function handleSingleReject(material: any) {
  currentMaterial.value = material
  reviewForm.value = { issue_type: '', description: '' }
  reviewDialogVisible.value = true
}

async function submitReview() {
  if (!reviewForm.value.description) {
    ElMessage.warning('请填写退回说明')
    return
  }
  const formData = new FormData()
  formData.append('material_id', String(currentMaterial.value.id))
  const appId = selectedApp.value.application_id
  formData.append('application_id', String(appId))
  formData.append('result', '退回')
  formData.append('issue_type', reviewForm.value.issue_type || '内容问题')
  formData.append('description', reviewForm.value.description)
  try {
    await api.post('/api/reviews/', formData)
    ElMessage.success('已退回')
    reviewDialogVisible.value = false
    materials.value = materials.value.filter((m: any) => m.id !== currentMaterial.value.id)
    if (!materials.value.length) {
      pendingApps.value = pendingApps.value.filter((app: any) => app.application_id !== appId)
      selectedApp.value = null
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

onMounted(async () => {
  await checkAccess()
  loadPendingApps()
})
</script>

<style scoped>
.review-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.section-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.3px;
}

.section-desc {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 14px;
}

.review-filters :deep(.el-select .el-input__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px #e5e7eb;
}

.panel {
  border-radius: 14px;
  border: 1px solid #f1f5f9;
  overflow: hidden;
}

.panel :deep(.el-card__header) {
  border-bottom: 1px solid #f1f5f9;
  padding: 18px 20px;
  background: #fafafa;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 14px;
  color: #0f172a;
}

.count-badge {
  margin-left: 6px;
}

.app-row {
  padding: 14px 16px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
  margin: 4px 8px;
}

.app-row:hover {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.app-row.active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(139, 92, 246, 0.08));
  border-color: rgba(99, 102, 241, 0.3);
}

.app-row.overdue {
  border-color: #fecaca;
  background: #fef2f2;
}

.sla-overdue {
  color: #ef4444;
  font-weight: 600;
  margin-left: 6px;
}

.sla-remain {
  color: #64748b;
  margin-left: 6px;
}

.app-row-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.app-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.app-row-info {
  flex: 1;
  min-width: 0;
}

.app-row-name {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}

.app-row-meta {
  font-size: 12px;
  color: #64748b;
  margin-top: 3px;
}

.review-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.review-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.review-name {
  font-weight: 700;
  font-size: 16px;
  color: #0f172a;
}

.review-batch {
  font-size: 12px;
  color: #64748b;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 500;
}

.review-actions {
  display: flex;
  gap: 8px;
}

.filename-text {
  font-size: 13px;
  color: #374151;
}

.dialog-material-info {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #f1f5f9;
}

.dialog-filename {
  font-size: 13px;
  font-weight: 500;
  color: #0f172a;
}

.review-history {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #f1f5f9;
}

.history-title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  margin: 0 0 16px;
}

.history-item {
  font-weight: 600;
  margin-right: 8px;
  color: #0f172a;
}

.history-issue {
  color: #ef4444;
  font-size: 13px;
  margin-right: 8px;
  font-weight: 500;
}

.history-desc {
  color: #64748b;
  font-size: 13px;
}

:deep(.el-button--success) {
  background: linear-gradient(135deg, #10b981, #059669);
  border: none;
  border-radius: 8px;
  font-weight: 500;
}

:deep(.el-button--success:hover) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

:deep(.el-button--danger) {
  background: #fff;
  border: 1px solid #fecaca;
  color: #ef4444;
  border-radius: 8px;
  font-weight: 500;
}

:deep(.el-button--danger:hover) {
  background: #fef2f2;
  border-color: #ef4444;
}
</style>
