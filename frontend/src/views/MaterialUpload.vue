<template>
  <div class="material-upload">
    <!-- Upload Bar -->
    <div class="upload-bar">
      <div class="upload-left">
        <el-select v-model="selectedCategory" placeholder="选择材料类型" clearable style="width: 160px">
          <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
        </el-select>
        <el-upload
          ref="uploadRef"
          :http-request="customUpload"
          :before-upload="beforeUpload"
          :on-success="handleSuccess"
          :on-error="handleError"
          :show-file-list="false"
        >
          <template #trigger>
            <el-button type="primary" size="small">
              <el-icon><Upload /></el-icon> 上传材料
            </el-button>
          </template>
        </el-upload>
      </div>
      <div class="upload-right">
        <el-tooltip
          content="打包下载每类材料的最新版本；未选择材料类型时下载全部类别"
          placement="top"
          :show-after="400"
        >
          <el-button
            type="success"
            size="small"
            :loading="batchDownloading"
            @click="batchDownload"
          >
            <el-icon v-if="!batchDownloading"><Download /></el-icon>
            {{ batchDownloadLabel }}
          </el-button>
        </el-tooltip>
      </div>
    </div>

    <!-- Material checklist hint -->
    <div v-if="checklist" class="checklist-bar">
      <el-alert
        v-if="!checklist.is_complete"
        type="warning"
        :closable="false"
        show-icon
        class="checklist-alert"
      >
        <template #title>
          <div class="checklist-alert-title">
            <span>还需补充材料：{{ (checklist.missing || []).join('、') }}</span>
            <el-button type="warning" text size="small" @click="showChecklist = !showChecklist">
              {{ showChecklist ? '收起清单' : '查看完整清单' }}
            </el-button>
          </div>
        </template>
        <el-collapse-transition>
          <div v-show="showChecklist" class="checklist-detail">
            <div v-for="item in checklist.required" :key="item.category" class="checklist-row">
              <span class="checklist-cat">{{ item.category }}</span>
              <el-tag :type="item.provided ? 'success' : 'danger'" size="small" round>
                {{ item.provided ? `已传 ${item.count} 份` : '未传' }}
              </el-tag>
            </div>
          </div>
        </el-collapse-transition>
      </el-alert>
      <el-tag v-else type="success" effect="plain" round size="small" class="checklist-ok">
        <el-icon><CircleCheck /></el-icon> 材料齐全
      </el-tag>
    </div>

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
                  <el-tag
                    :type="auditType(item.audit_status)"
                    size="small"
                    round
                    :class="{ 'clickable-tag': item.audit_status === '已标记问题' }"
                    @click="item.audit_status === '已标记问题' ? showRejectDetail(item) : undefined"
                  >{{ item.audit_status }}</el-tag>
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

      <!-- Right: file tree sidebar - always show -->
      <div class="material-sidebar">
        <div class="sidebar-title">
          <el-icon><FolderOpened /></el-icon>
          <span>文件目录</span>
        </div>
        <el-tree
          v-if="fileTree.length"
          :data="fileTree"
          :props="{ children: 'children', label: 'name' }"
          node-key="path"
          default-expand-all
          highlight-current
          @node-click="handleTreeNodeClick"
        />
        <div v-else class="sidebar-empty">
          <el-icon size="24" color="#94a3b8"><Folder /></el-icon>
          <span>暂无文件目录</span>
        </div>
    </div>

    <!-- Reject detail dialog -->
    <el-dialog v-model="rejectDetailVisible" title="退回原因" width="480px" destroy-on-close>
      <div v-if="rejectDetailItem" style="padding: 8px 0">
        <div style="margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
          <el-tag size="small">{{ rejectDetailItem.category }}</el-tag>
          <span style="font-weight: 500; color: #1e293b;">{{ rejectDetailItem.filename }}</span>
        </div>
        <div v-if="rejectDetailData.issue_type" style="margin-bottom: 10px;">
          <span style="color: #64748b; font-size: 13px;">问题类型：</span>
          <el-tag type="warning" size="small" round>{{ rejectDetailData.issue_type }}</el-tag>
        </div>
        <div v-if="rejectDetailData.description" style="background: #f8fafc; border-radius: 8px; padding: 12px; font-size: 14px; color: #334155; line-height: 1.6;">
          {{ rejectDetailData.description }}
        </div>
        <div v-if="!rejectDetailData.issue_type && !rejectDetailData.description" style="color: #94a3b8; font-size: 13px;">
          暂无详细退回说明
        </div>
        <div v-if="rejectDetailData.reviewer" style="margin-top: 10px; font-size: 12px; color: #94a3b8;">
          审核员：{{ rejectDetailData.reviewer }} · {{ rejectDetailData.date }}
        </div>
      </div>
      <template #footer>
        <el-button @click="rejectDetailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- File preview dialog -->
    <el-dialog
      v-model="previewVisible"
      :title="previewMaterial?.filename || '预览'"
      width="90%"
      destroy-on-close
      class="preview-dialog"
      top="3vh"
      :close-on-click-modal="true"
      @closed="resetDocxPreview"
    >
      <div class="preview-wrapper" v-if="previewType === 'image'">
        <img :src="previewSrc" class="preview-img" />
      </div>
      <div v-else-if="previewType === 'pdf'" class="pdf-preview">
        <el-button type="primary" @click="openPdfTab">在新标签页中打开 PDF</el-button>
      </div>
      <!-- docx 纯前端本地解析预览 -->
      <div
        v-else-if="previewType === 'docx'"
        class="docx-preview"
        v-loading="docxLoading"
        element-loading-text="文档解析中…"
        element-loading-background="rgba(15, 23, 42, 0.85)"
      >
        <div v-if="docxError" class="docx-tip">
          <el-icon class="docx-tip-icon"><WarningFilled /></el-icon>
          <span>{{ docxError }}</span>
          <el-button type="primary" size="small" @click="downloadFile(previewMaterial?.id)">
            <el-icon><Download /></el-icon> 下载文件
          </el-button>
        </div>
        <div v-else-if="docxHtml" class="docx-body" v-html="docxHtml"></div>
        <div v-else-if="!docxLoading" class="docx-tip">
          <el-icon class="docx-tip-icon"><WarningFilled /></el-icon>
          <span>文档内容为空</span>
        </div>
      </div>
      <!-- .doc 旧二进制格式 / 其他不支持的类型：无法本地解析 -->
      <div v-else-if="previewType === 'doc'" class="docx-preview">
        <div class="docx-tip">
          <el-icon class="docx-tip-icon"><WarningFilled /></el-icon>
          <span>{{ unsupportedTip }}</span>
          <el-button type="primary" size="small" @click="downloadFile(previewMaterial?.id)">
            <el-icon><Download /></el-icon> 下载文件
          </el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowUp, CircleCheck, Delete, Document, Download, Folder, FolderOpened, Upload, WarningFilled } from '@element-plus/icons-vue'
import { docxToHtml, fetchMaterialBuffer, getFileExt } from '../utils/docPreview'

const props = defineProps<{ applicationId: number; canSubmit?: boolean }>()

const categories = ['身份证明', '学历学位', '职称证书', '聘用/劳动合同', '业绩成果', '论文著作', '继续教育', '其他材料']
const selectedCategory = ref('身份证明')
const materials = ref<any[]>([])
const fileTree = ref<any[]>([])
const reviews = ref<any[]>([])
const loading = ref(false)
const expandedGroups = ref<Set<string>>(new Set())
const previewVisible = ref(false)
const previewSrc = ref('')
const previewType = ref<'image' | 'pdf' | 'docx' | 'doc' | ''>('')
const previewMaterial = ref<any>(null)
const docxHtml = ref('')
const docxLoading = ref(false)
const docxError = ref('')
/** 不支持预览类型（.doc / 未知类型）的提示文案 */
const unsupportedTip = ref('')
/** 递增请求序号，避免快速切换文件时旧请求的结果覆盖新内容 */
let docxRequestSeq = 0
const rejectDetailVisible = ref(false)
const rejectDetailItem = ref<any>(null)
const rejectDetailData = ref<any>({})
const checklist = ref<any>(null)
const showChecklist = ref(false)
/** 批量打包下载中（打包可能耗时） */
const batchDownloading = ref(false)

const batchDownloadLabel = computed(() =>
  batchDownloading.value
    ? '打包中…'
    : selectedCategory.value
      ? `下载「${selectedCategory.value}」`
      : '批量下载'
)

const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
const PDF_EXTS = ['.pdf']
const DOCX_EXTS = ['.docx']
const DOC_EXTS = ['.doc']

/** .doc 为旧版 Word 二进制格式，mammoth 无法解析，只提供下载 */
const DOC_UNSUPPORTED_TIP = '.doc 为旧版 Word 二进制格式，暂不支持在线预览，请下载查看'
const UNSUPPORTED_TIP = '该文件类型不支持在线预览，请下载查看'

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

function showRejectDetail(item: any) {
  rejectDetailItem.value = item
  const relatedReview = reviews.value.find((r: any) => r.material_id === item.id && r.result === '退回')
  if (relatedReview) {
    rejectDetailData.value = {
      issue_type: relatedReview.issue_type || '',
      description: relatedReview.description || '',
      reviewer: relatedReview.reviewer_id ? `审核员 #${relatedReview.reviewer_id}` : '',
      date: relatedReview.created_at ? new Date(relatedReview.created_at).toLocaleString('zh-CN') : '',
    }
  } else {
    rejectDetailData.value = { issue_type: '', description: '', reviewer: '', date: '' }
  }
  rejectDetailVisible.value = true
}

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
    // 转换后端树格式为 el-tree 格式
    const rawTree = data.tree || []
    if (rawTree.length && rawTree[0].category !== undefined) {
      // 后端格式: [{category, files: [{name, path, size, modified}]}]
      // 转换为: [{name, path, children: [{name, path, isLeaf}]}]
      fileTree.value = rawTree.map((cat: any) => ({
        name: cat.category,
        path: cat.category,
        children: (cat.files || []).map((f: any) => ({
          name: f.name,
          path: f.path,
          isLeaf: true,
        })),
      }))
    } else {
      fileTree.value = rawTree
    }
    const { data: reviewData } = await api.get(`/api/reviews/application/${props.applicationId}`)
    reviews.value = reviewData
    // 材料清单完备性：上传/删除材料后随材料列表一并刷新
    loadChecklist()
  } finally {
    loading.value = false
  }
}

async function loadChecklist() {
  try {
    const { data } = await api.get(`/api/applications/${props.applicationId}/material-checklist`)
    checklist.value = data
  } catch {
    checklist.value = null
  }
}

function beforeUpload() {
  if (!selectedCategory.value) {
    ElMessage.warning('请先选择材料类型')
    return false
  }
  return true
}

async function customUpload(options: any) {
  const formData = new FormData()
  formData.append('category', selectedCategory.value)
  formData.append('file', options.file)
  try {
    const { data } = await api.post(`/api/applications/${props.applicationId}/materials/`, formData)
    options.onSuccess(data, options.file)
  } catch (err: any) {
    options.onError(err)
  }
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

/** 从 Content-Disposition 解析文件名（优先 RFC 5987 的 filename*=UTF-8''） */
function parseFilename(disposition: string | undefined): string {
  if (!disposition) return ''
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  return match ? match[1] : ''
}

/** 批量下载：按当前选中的类别过滤，未选择则打包全部类别 */
async function batchDownload() {
  if (batchDownloading.value) return
  batchDownloading.value = true
  try {
    const params: Record<string, any> = {}
    if (selectedCategory.value) params.category = selectedCategory.value
    const response = await api.get(
      `/api/applications/${props.applicationId}/materials/download-zip`,
      { params, responseType: 'blob' }
    )
    const disposition = response.headers?.['content-disposition'] as string | undefined
    const filename = parseFilename(disposition) || `材料打包_${props.applicationId}.zip`
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('打包下载已开始')
  } catch (e: any) {
    // blob 响应下错误体也是 blob，需要异步解析出 detail
    let detail = ''
    const blob = e.response?.data
    if (blob instanceof Blob) {
      try {
        detail = JSON.parse(await blob.text())?.detail || ''
      } catch {
        detail = ''
      }
    } else {
      detail = e.response?.data?.detail || ''
    }
    if (e.response?.status === 403) {
      ElMessage.error(detail || '无权限下载该批次材料')
    } else if (e.response?.status === 404) {
      ElMessage.warning(detail || '该批次没有可下载的材料')
    } else {
      ElMessage.error(detail || '批量下载失败')
    }
  } finally {
    batchDownloading.value = false
  }
}

async function deleteMaterial(materialId: number, version: number) {
  try {
    await ElMessageBox.confirm(`确认删除版本 v${version} 的材料？`, '删除确认')
    await api.delete(`/api/applications/${props.applicationId}/materials/${materialId}`)
    ElMessage.success('已删除')
    loadMaterials()
  } catch {
    // 用户点「取消」走这里，属正常流程；接口失败已由 api 拦截器统一提示
  }
}

function materialFileUrl(materialId: number) {
  return `/api/applications/${props.applicationId}/materials/file/${materialId}`
}

function resetDocxPreview() {
  docxHtml.value = ''
  docxError.value = ''
  docxLoading.value = false
  docxRequestSeq++
}

async function loadDocxPreview(item: any) {
  const seq = ++docxRequestSeq
  docxLoading.value = true
  docxError.value = ''
  docxHtml.value = ''
  try {
    // 同源 + Cookie 鉴权本地取回，交给 mammoth 在浏览器内解析，不上传任何第三方
    const buffer = await fetchMaterialBuffer(materialFileUrl(item.id))
    const html = await docxToHtml(buffer)
    if (seq !== docxRequestSeq) return
    docxHtml.value = html
  } catch (err) {
    if (seq !== docxRequestSeq) return
    console.error('[docx preview] 解析失败', err)
    docxError.value = '文档解析失败，请下载查看'
  } finally {
    if (seq === docxRequestSeq) docxLoading.value = false
  }
}

function previewFile(item: any) {
  // 切换文件时清理上一次的 docx 解析状态与在途请求
  resetDocxPreview()
  const ext = getFileExt(item.filename)
  if (IMAGE_EXTS.includes(ext)) {
    previewType.value = 'image'
    previewMaterial.value = item
    previewSrc.value = materialFileUrl(item.id)
    previewVisible.value = true
  } else if (PDF_EXTS.includes(ext)) {
    previewType.value = 'pdf'
    previewMaterial.value = item
    previewVisible.value = true
  } else if (DOCX_EXTS.includes(ext)) {
    previewType.value = 'docx'
    previewMaterial.value = item
    previewVisible.value = true
    loadDocxPreview(item)
  } else if (DOC_EXTS.includes(ext)) {
    previewType.value = 'doc'
    unsupportedTip.value = DOC_UNSUPPORTED_TIP
    previewMaterial.value = item
    previewVisible.value = true
  } else {
    // 其他未知类型（含无扩展名）：同样给出下载引导
    previewType.value = 'doc'
    unsupportedTip.value = UNSUPPORTED_TIP
    previewMaterial.value = item
    previewVisible.value = true
  }
}

function openPdfTab() {
  if (previewMaterial.value) {
    window.open(materialFileUrl(previewMaterial.value.id), '_blank')
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
  gap: 12px;
}
.upload-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.upload-right :deep(.el-button) {
  height: 36px !important;
  padding: 8px 12px !important;
  line-height: 1 !important;
}
.upload-right :deep(.el-button .el-icon) {
  margin-right: 4px;
}
.upload-left :deep(.el-select .el-input__wrapper) {
  padding: 0 8px;
}
.upload-left :deep(.el-select .el-input__inner) {
  font-size: 14px;
}
.upload-left :deep(.el-upload .el-button) {
  height: 36px !important;
  padding: 8px 12px !important;
  line-height: 1 !important;
}
.upload-left :deep(.el-upload .el-button .el-icon) {
  margin-right: 4px;
}
.checklist-bar {
  margin-bottom: 16px;
}
.checklist-alert {
  border-radius: 10px;
}
.checklist-alert-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.checklist-detail {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
}
.checklist-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.checklist-cat {
  color: #475569;
}
.checklist-ok {
  display: inline-flex;
  align-items: center;
  gap: 4px;
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
  min-width: 0;
  flex: 1;
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
.clickable-tag {
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}
.clickable-tag:hover {
  transform: scale(1.1);
  box-shadow: 0 0 0 2px rgba(239,68,68,0.3);
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

/* ---------- docx 本地解析预览 ---------- */
.docx-preview {
  width: 100%;
  height: 85vh;
  overflow: auto;
  background: #0f172a;
  padding: 24px 16px;
  box-sizing: border-box;
}

.docx-body {
  max-width: 820px;
  margin: 0 auto;
  background: #fff;
  border-radius: 6px;
  padding: 48px 56px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
  color: #1e293b;
  font-size: 15px;
  line-height: 1.8;
  font-family: "Microsoft YaHei", "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.docx-body :deep(p) {
  margin: 0 0 0.9em;
}

.docx-body :deep(h1),
.docx-body :deep(h2),
.docx-body :deep(h3),
.docx-body :deep(h4),
.docx-body :deep(h5),
.docx-body :deep(h6) {
  margin: 1.2em 0 0.6em;
  font-weight: 600;
  line-height: 1.4;
  color: #0f172a;
}
.docx-body :deep(h1) { font-size: 22px; }
.docx-body :deep(h2) { font-size: 19px; }
.docx-body :deep(h3) { font-size: 17px; }
.docx-body :deep(h4),
.docx-body :deep(h5),
.docx-body :deep(h6) { font-size: 15px; }

.docx-body :deep(strong),
.docx-body :deep(b) {
  font-weight: 600;
}

.docx-body :deep(ul),
.docx-body :deep(ol) {
  margin: 0 0 0.9em;
  padding-left: 2em;
}

.docx-body :deep(li) {
  margin: 0.25em 0;
}

.docx-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0 0 1em;
  font-size: 14px;
}

.docx-body :deep(th),
.docx-body :deep(td) {
  border: 1px solid #cbd5e1;
  padding: 6px 10px;
  text-align: left;
  vertical-align: top;
}

.docx-body :deep(th) {
  background: #f1f5f9;
  font-weight: 600;
}

.docx-body :deep(img) {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 0.5em auto;
}

.docx-body :deep(a) {
  color: #4f46e5;
  text-decoration: underline;
}

.docx-body :deep(blockquote) {
  margin: 0 0 1em;
  padding: 4px 14px;
  border-left: 3px solid #cbd5e1;
  color: #475569;
}

.docx-body :deep(pre),
.docx-body :deep(code) {
  font-family: Consolas, Monaco, "Courier New", monospace;
  background: #f8fafc;
  border-radius: 4px;
}
.docx-body :deep(pre) {
  padding: 10px 12px;
  overflow-x: auto;
  font-size: 13px;
}

.docx-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  min-height: 320px;
  color: #cbd5e1;
  font-size: 14px;
  text-align: center;
  padding: 24px;
}

.docx-tip-icon {
  font-size: 34px;
  color: #f59e0b;
}
</style>
