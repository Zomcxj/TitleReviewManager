<template>
  <div class="material-upload">
    <!-- Upload Bar -->
    <div class="upload-bar">
      <div class="upload-left">
        <el-select v-model="selectedCategory" placeholder="选择材料类型" style="width: 160px">
          <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
        </el-select>
        <el-upload
          ref="uploadRef"
          :action="`/api/applications/${applicationId}/materials`"
          :data="{ category: selectedCategory }"
          :before-upload="beforeUpload"
          :on-success="handleSuccess"
          :on-error="handleError"
          :show-file-list="false"
          drag
          style="margin-left: 12px"
        >
          <template #trigger>
            <el-button type="primary">
              <el-icon><Upload /></el-icon> 上传材料
            </el-button>
          </template>
          <template #tip>
            <div class="drag-hint">拖拽文件到此处或点击上传</div>
          </template>
        </el-upload>
      </div>
      <el-button v-if="canSubmit" type="success" @click="handleSubmitReview" :disabled="materials.length === 0">
        <el-icon><Check /></el-icon> 材料已齐，提交审核
      </el-button>
    </div>

    <!-- Issues Panel -->
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

    <!-- Main layout: file list + tree sidebar -->
    <div class="material-layout">
      <!-- Left: material grid -->
      <div class="material-main">
        <div class="material-grid" v-if="groupedMaterials.length">
          <div v-for="group in groupedMaterials" :key="group.category" class="material-group">
            <div class="group-header">
              <div class="group-left">
                <el-tag>{{ group.category }}</el-tag>
                <span class="group-count">{{ group.items.length }} 份</span>
              </div>
              <el-button
                v-if="group.items.length > 1" type="primary" text size="small"
                @click="toggleGroupVersions(group.category)"
              >
                <el-icon><component :is="group.showVersions ? ArrowUp : ArrowDown" /></el-icon>
                {{ group.showVersions ? '收起' : '版本历史' }}
              </el-button>
            </div>
            <div class="file-list">
              <div
                v-for="item in (group.showVersions ? group.items : group.items.slice(-1))" :key="item.id"
                class="file-item"
                :class="{
                  flagged: item.audit_status === '已标记问题',
                  isOld: group.showVersions && item !== group.items[group.items.length - 1]
                }"
              >
                <div class="file-info">
                  <el-icon class="file-icon" @click="previewFile(item)"><Document /></el-icon>
                  <span class="file-name" @click="previewFile(item)">{{ item.filename }}</span>
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

      <!-- Right: file tree sidebar -->
      <div class="material-sidebar" v-if="fileTree.length">
        <div class="sidebar-title">
          <el-icon><FolderOpened /></el-icon>
          <span>NAS 文件目录</span>
        </div>
        <el-tree
          :data="fileTree"
          :props="{ children: 'children', label: 'name' }"
          node-key="path"
          default-expand-all
          highlight-current
          @node-click="handleTreeNodeClick"
        />
      </div>
    </div>

    <!-- Image preview dialog -->
    <el-dialog v-model="previewVisible" :title="previewMaterial?.filename || '预览'" width="90%" destroy-on-close class="preview-dialog" top="3vh" :close-on-click-modal="true">
      <div class="preview-wrapper" v-if="previewType === 'image'">
        <img :src="previewSrc" class="preview-img" />
      </div>
      <div v-else-if="previewType === 'pdf'" class="pdf-preview">
        <el-button type="primary" @click="openPdfTab">在新标签页中打开 PDF</el-button>
      </div>
    </el-dialog>
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
const fileTree = ref<any[]>([])
const reviews = ref<any[]>([])
const loading = ref(false)
const expandedGroups = ref<Set<string>>(new Set())
const previewVisible = ref(false)
const previewSrc = ref('')
const previewType = ref<'image' | 'pdf' | ''>('')
const previewMaterial = ref<any>(null)

const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
const PDF_EXTS = ['.pdf']

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
      return { ...m, description: relatedReview?.description || '', issue_type: relatedReview?.issue_type || '' }
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
    materials.value = data.items || []
    fileTree.value = data.tree || []
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

function handleError(err: any) {
  ElMessage.error(err?.message || '上传失败')
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
  } catch {}
}

function previewFile(item: any) {
  const ext = '.' + (item.filename || '').split('.').pop()?.toLowerCase()
  if (IMAGE_EXTS.includes(ext)) {
    previewType.value = 'image'
    previewMaterial.value = item
    previewSrc.value = `/api/applications/${props.applicationId}/materials/file/${item.id}`
    previewVisible.value = true
  } else if (PDF_EXTS.includes(ext)) {
    previewType.value = 'pdf'
    previewMaterial.value = item
    previewVisible.value = true
  }
}

function openPdfTab() {
  if (previewMaterial.value) {
    window.open(`/api/applications/${props.applicationId}/materials/file/${previewMaterial.value.id}`, '_blank')
  }
  previewVisible.value = false
}

function handleTreeNodeClick(node: any) {
  if (!node.isLeaf) return
  const matching = materials.value.find(m => m.filename === node.name && m.file_path === node.path)
  if (matching) {
    previewFile(matching)
  }
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
.drag-hint {
  font-size: 12px;
  color: #94a3b8;
  margin-left: 8px;
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
.material-layout {
  display: flex;
  gap: 16px;
}
.material-main {
  flex: 1;
  min-width: 0;
}
.material-sidebar {
  width: 260px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  padding: 12px;
  max-height: 500px;
  overflow-y: auto;
}
.sidebar-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e2e8f0;
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
  cursor: pointer;
}
.file-icon:hover {
  color: #4f46e5;
}
.file-name {
  font-size: 13px;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
  cursor: pointer;
}
.file-name:hover {
  color: #6366f1;
  text-decoration: underline;
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

.preview-dialog :deep(.el-dialog__body) {
  padding: 0;
  background: #0f172a;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 500px;
}

.preview-wrapper {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 85vh;
  overflow: auto;
}

.preview-img {
  max-width: 100%;
  max-height: 85vh;
  object-fit: contain;
  display: block;
  margin: 0 auto;
}

.pdf-preview {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 40px;
}
</style>
