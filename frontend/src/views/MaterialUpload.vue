<template>
  <div class="material-upload">
    <div class="upload-bar">
      <div class="upload-left">
        <el-select v-model="selectedCategory" placeholder="选择材料类型" style="width: 160px">
          <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
        </el-select>
        <el-upload :action="`/api/applications/${applicationId}/materials`" :data="{ category: selectedCategory }"
          :before-upload="beforeUpload" :on-success="handleSuccess" :on-error="handleError" :show-file-list="false"
          style="margin-left: 12px">
          <template #trigger>
            <el-button type="primary">
              <el-icon><Upload /></el-icon> 上传材料
            </el-button>
          </template>
        </el-upload>
      </div>
      <el-button v-if="canSubmit" type="success" @click="handleSubmitReview" :disabled="materials.length === 0">
        <el-icon><Check /></el-icon> 材料已齐，提交审核
      </el-button>
    </div>

    <div v-if="flaggedIssues.length" class="issues-panel">
      <div class="issues-header">
        <el-icon color="#ef4444"><WarningFilled /></el-icon>
        <span>待处理问题（{{ flaggedIssues.length }} 项）</span>
      </div>
      <div v-for="issue in flaggedIssues" :key="issue.id" class="issue-item">
        <el-tag type="danger" size="small" round>{{ issue.category }}</el-tag>
        <span class="issue-file">{{ issue.filename }}</span>
        <span class="issue-desc">{{ issue.description }}</span>
        <el-tag v-if="issue.issue_type" type="warning" size="small" round>{{ issue.issue_type }}</el-tag>
      </div>
    </div>

    <div class="material-grid" v-if="groupedMaterials.length">
      <div v-for="group in groupedMaterials" :key="group.category" class="material-group">
        <div class="group-header">
          <div class="group-left">
            <el-tag>{{ group.category }}</el-tag>
            <span class="group-count">{{ group.items.length }} 份</span>
          </div>
          <el-button v-if="group.items.length > 1" type="primary" text size="small" @click="toggleGroupVersions(group.category)">
            <el-icon><component :is="group.showVersions ? ArrowUp : ArrowDown" /></el-icon>
            {{ group.showVersions ? '收起' : '版本历史' }}
          </el-button>
        </div>
        <div class="file-list">
          <div v-for="item in (group.showVersions ? group.items : group.items.slice(-1))" :key="item.id" class="file-item"
            :class="{ flagged: item.audit_status === '已标记问题', isOld: group.showVersions && item !== group.items[group.items.length - 1] }">
            <div class="file-info">
              <el-icon class="file-icon"><Document /></el-icon>
              <span class="file-name">{{ item.filename }}</span>
              <span class="file-size">{{ formatSize(item.file_size) }}</span>
              <el-tag size="small" type="info" round class="version-tag">v{{ item.version }}</el-tag>
              <el-tag v-if="item === group.items[group.items.length - 1]" size="small" type="success" round class="latest-tag">最新</el-tag>
            </div>
            <div class="file-status">
              <el-tag :type="auditType(item.audit_status)" size="small" round>{{ item.audit_status }}</el-tag>
            </div>
            <div class="file-actions">
              <el-button type="primary" text size="small" @click="downloadFile(item.id)">
                <el-icon><Download /></el-icon>
              </el-button>
              <el-button type="danger" text size="small" @click="deleteMaterial(item.id, item.version)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-empty v-if="!loading && !materials.length" description="暂无材料，请上传" :image-size="80" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowUp, ArrowDown } from '@element-plus/icons-vue'

const props = defineProps<{ applicationId: number; canSubmit?: boolean }>()
const emit = defineEmits(['submit-review'])

const categories = ['身份证明', '学历学位', '职称证书', '聘用/劳动合同', '业绩成果', '论文著作', '继续教育', '其他材料']
const selectedCategory = ref('身份证明')
const materials = ref<any[]>([])
const reviews = ref<any[]>([])
const loading = ref(false)
const expandedGroups = ref<Set<string>>(new Set())

const groupedMaterials = computed(() => {
  const groups: Record<string, any[]> = {}
  materials.value.forEach(m => {
    if (!groups[m.category]) groups[m.category] = []
    groups[m.category].push(m)
  })
  return Object.entries(groups).map(([category, items]) => ({
    category,
    items: items.sort((a, b) => a.version - b.version),
    showVersions: expandedGroups.value.has(category),
  }))
})

const flaggedIssues = computed(() => {
  return materials.value
    .filter(m => m.audit_status === '已标记问题')
    .map(m => {
      const relatedReview = reviews.value.find(r => r.material_id === m.id && r.result === '退回')
      return {
        ...m,
        description: relatedReview?.description || '',
        issue_type: relatedReview?.issue_type || '',
      }
    })
})

function auditType(status: string) {
  const map: Record<string, string> = { '待审核': 'info', '已通过': 'success', '已标记问题': 'danger' }
  return map[status] || 'info'
}

function formatSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function toggleGroupVersions(category: string) {
  if (expandedGroups.value.has(category)) {
    expandedGroups.value.delete(category)
  } else {
    expandedGroups.value.add(category)
  }
  expandedGroups.value = new Set(expandedGroups.value)
}

async function loadMaterials() {
  loading.value = true
  try {
    const { data } = await api.get(`/api/applications/${props.applicationId}/materials/`)
    materials.value = data
    const { data: reviewData } = await api.get(`/api/reviews/application/${props.applicationId}`)
    reviews.value = reviewData
  } finally {
    loading.value = false
  }
}

function beforeUpload(file: File) {
  if (!selectedCategory.value) {
    ElMessage.warning('请先选择材料类型')
    return false
  }
  return true
}

function handleSuccess() {
  ElMessage.success('上传成功')
  loadMaterials()
}

function handleError() {
  ElMessage.error('上传失败')
}

async function downloadFile(materialId: number) {
  window.open(`/api/applications/${props.applicationId}/materials/file/${materialId}`, '_blank')
}

async function deleteMaterial(materialId: number, version: number) {
  try {
    await ElMessageBox.confirm(`确认删除版本 v${version} 的材料？`, '删除确认')
    await api.delete(`/api/applications/${props.applicationId}/materials/${materialId}`)
    ElMessage.success('已删除')
    loadMaterials()
  } catch { }
}

function handleSubmitReview() {
  emit('submit-review')
}

watch(() => props.applicationId, loadMaterials, { immediate: true })
</script>

<style scoped>
.upload-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.upload-left {
  display: flex;
  align-items: center;
}
.issues-panel {
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.issues-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #dc2626;
  margin-bottom: 10px;
  font-size: 14px;
}
.issue-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed #fecaca;
  font-size: 13px;
}
.issue-item:last-child {
  border-bottom: none;
}
.issue-file {
  font-weight: 500;
  color: #1e293b;
}
.issue-desc {
  color: #64748b;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.material-grid {
  display: grid;
  gap: 16px;
}
.material-group {
  background: #fff;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}
.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.group-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.group-count {
  color: #94a3b8;
  font-size: 12px;
}
.file-list {
  padding: 4px;
}
.file-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 6px;
  gap: 12px;
  transition: background 0.15s;
}
.file-item:hover {
  background: #f8fafc;
}
.file-item.flagged {
  background: #fef2f2;
}
.file-item.isOld {
  opacity: 0.6;
  background: #f1f5f9;
}
.file-item.isOld:hover {
  opacity: 0.85;
}
.file-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.file-icon {
  color: #6366f1;
  flex-shrink: 0;
}
.file-name {
  font-size: 13px;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}
.file-size {
  font-size: 12px;
  color: #94a3b8;
}
.version-tag {
  font-size: 11px;
  flex-shrink: 0;
}
.latest-tag {
  font-size: 11px;
  flex-shrink: 0;
}
.file-status {
  flex-shrink: 0;
}
.file-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
</style>
