<template>
  <div class="review-workspace">
    <div class="review-top">
      <div class="review-top-left">
        <h3 class="section-title">审核工作台</h3>
        <p class="section-desc">选择申报批次，逐项审核材料，支持批量通过或退回标记问题</p>
      </div>
      <div class="review-filters">
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 140px" @change="loadPendingApps">
          <el-option label="初次申报" value="初次申报" />
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
          <div v-for="app in pendingApps" :key="app.id || app.application_id" class="app-row"
            :class="{ active: selectedApp?.id === app.id || selectedApp?.application_id === app.application_id }"
            @click="selectApp(app)">
            <div class="app-row-main">
              <div class="app-avatar">{{ app.name?.charAt(0) || '?' }}</div>
              <div class="app-row-info">
                <div class="app-row-name">{{ app.name }}</div>
                <div class="app-row-meta">{{ app.batch_number || app.batch }} · {{ app.materials_count || 0 }} 份材料</div>
              </div>
              <el-tag :type="statusType(app.current_status || app.status)" size="small" round>
                {{ app.current_status || app.status }}
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
                <span class="review-name">{{ selectedApp.name }}</span>
                <span class="review-batch">{{ selectedApp.batch_number || selectedApp.batch }}</span>
              </div>
              <div class="review-actions">
                <el-button type="success" size="small" @click="handleBatchApprove"
                  :disabled="!selectedMaterials.length">
                  <el-icon><Select /></el-icon> 全部通过
                </el-button>
                <el-button type="danger" size="small" @click="handleBatchReject"
                  :disabled="!selectedMaterials.length">
                  <el-icon><CircleCloseFilled /></el-icon> 退回标记
                </el-button>
              </div>
            </div>
          </template>

          <el-table :data="materials" @selection-change="onSelectionChange" style="width: 100%"
            v-loading="loadingMaterials" row-key="id">
            <el-table-column type="selection" width="44" />
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
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <el-button type="primary" text size="small" @click="downloadFile(row.id)">下载</el-button>
                <el-button type="warning" text size="small" @click="showReviewDialog(row)">标记</el-button>
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

    <el-dialog v-model="reviewDialogVisible" :title="currentMaterial ? `标记问题` : '标记问题'" width="480px">
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
        <el-button type="primary" @click="submitReview">提交标记</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="rejectDialogVisible" title="批量退回标记" width="480px">
      <el-alert :title="`已选择 ${selectedMaterials.length} 项材料`" type="warning" :closable="false"
        style="margin-bottom: 16px" />
      <el-form label-position="top">
        <el-form-item label="退回说明">
          <el-input v-model="rejectReason" type="textarea" :rows="4"
            placeholder="请输入退回原因及修改要求，将应用于所有已选材料" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rejectDialogVisible = false">取消</el-button>
        <el-button type="danger" @click="submitBatchReject">确认退回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'
import { ElMessage } from 'element-plus'

const router = useRouter()
const authStore = useAuthStore()

// Role check: only reviewer and admin can access
if (!authStore.isReviewer && !authStore.isAdmin) {
  ElMessage.error('只有审核员和管理员可以访问审核工作台')
  router.push('/admin/dashboard')
}

const loadingList = ref(false)
const loadingMaterials = ref(false)
const pendingApps = ref<any[]>([])
const materials = ref<any[]>([])
const selectedApp = ref<any>(null)
const selectedAppReviews = ref<any[]>([])
const selectedMaterials = ref<any[]>([])
const reviewDialogVisible = ref(false)
const rejectDialogVisible = ref(false)
const currentMaterial = ref<any>(null)
const reviewForm = ref({ issue_type: '', description: '' })
const rejectReason = ref('')
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

async function loadPendingApps() {
  loadingList.value = true
  try {
    const { data } = await api.get('/api/customers/', { params: { page: 1, page_size: 100 } })
    let items = (data.items || []).filter((item: any) =>
      ['初次申报', '资料补充', '二次申报'].includes(item.current_status)
    )
    if (filterStatus.value) {
      items = items.filter((item: any) => item.current_status === filterStatus.value)
    }
    pendingApps.value = items
  } finally {
    loadingList.value = false
  }
}

async function selectApp(app: any) {
  selectedApp.value = app
  const appId = app.application_id || app.id
  loadingMaterials.value = true
  try {
    const { data } = await api.get(`/api/applications/${appId}/materials/`)
    materials.value = data
    const { data: reviewData } = await api.get(`/api/reviews/application/${appId}`)
    selectedAppReviews.value = reviewData
  } finally {
    loadingMaterials.value = false
  }
}

function onSelectionChange(selection: any[]) {
  selectedMaterials.value = selection
}

function downloadFile(materialId: number) {
  const appId = selectedApp.value?.application_id || selectedApp.value?.id
  window.open(`/api/applications/${appId}/materials/file/${materialId}`, '_blank')
}

function showReviewDialog(material: any) {
  currentMaterial.value = material
  reviewForm.value = { issue_type: '', description: '' }
  reviewDialogVisible.value = true
}

async function submitReview() {
  if (!reviewForm.value.description) {
    ElMessage.warning('请填写问题说明')
    return
  }
  const formData = new FormData()
  formData.append('material_id', String(currentMaterial.value.id))
  const appId = selectedApp.value.application_id || selectedApp.value.id
  formData.append('application_id', String(appId))
  formData.append('result', '退回')
  formData.append('issue_type', reviewForm.value.issue_type || '内容问题')
  formData.append('description', reviewForm.value.description)
  try {
    await api.post('/api/reviews/', formData)
    ElMessage.success('已标记问题')
    reviewDialogVisible.value = false
    selectApp(selectedApp.value)
    loadPendingApps()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function handleBatchApprove() {
  const appId = selectedApp.value.application_id || selectedApp.value.id
  try {
    await api.post(`/api/reviews/batch-review`, {
      application_id: appId,
      overall_result: '通过',
      review_details: selectedMaterials.value.map((m: any) => ({
        material_id: m.id,
        description: '审核通过',
      })),
      description: '批量审核通过',
    })
    ElMessage.success('批量通过成功')
    loadPendingApps()
    selectApp(selectedApp.value)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

function handleBatchReject() {
  rejectReason.value = ''
  rejectDialogVisible.value = true
}

async function submitBatchReject() {
  if (!rejectReason.value) {
    ElMessage.warning('请填写退回说明')
    return
  }
  const appId = selectedApp.value.application_id || selectedApp.value.id
  try {
    await api.post(`/api/reviews/batch-review`, {
      application_id: appId,
      overall_result: '退回',
      review_details: selectedMaterials.value.map((m: any) => ({
        material_id: m.id,
        issue_type: '需要补充/修改',
        description: rejectReason.value,
      })),
      description: rejectReason.value,
    })
    ElMessage.success('已退回并标记问题')
    rejectDialogVisible.value = false
    loadPendingApps()
    selectApp(selectedApp.value)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

onMounted(loadPendingApps)
</script>

<style scoped>
.review-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.section-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
}
.section-desc {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}
.panel {
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.panel :deep(.el-card__header) {
  border-bottom: 1px solid #f1f5f9;
  padding: 14px 18px;
}
.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
  color: #1e293b;
}
.count-badge {
  margin-left: 4px;
}
.app-row {
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid transparent;
  margin-bottom: 4px;
}
.app-row:hover {
  background: #f8fafc;
}
.app-row.active {
  background: #f0f0ff;
  border-color: #6366f1;
}
.app-row-main {
  display: flex;
  align-items: center;
  gap: 10px;
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
  font-weight: 500;
  color: #1e293b;
}
.app-row-meta {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 2px;
}
.review-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.review-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.review-name {
  font-weight: 600;
  font-size: 15px;
}
.review-batch {
  font-size: 12px;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}
.review-actions {
  display: flex;
  gap: 8px;
}
.filename-text {
  font-size: 13px;
}
.dialog-material-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
}
.dialog-filename {
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
}
.review-history {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}
.history-title {
  font-size: 14px;
  font-weight: 600;
  color: #475569;
  margin: 0 0 12px;
}
.history-item {
  font-weight: 600;
  margin-right: 8px;
}
.history-issue {
  color: #ef4444;
  font-size: 13px;
  margin-right: 8px;
}
.history-desc {
  color: #64748b;
  font-size: 13px;
}
</style>
