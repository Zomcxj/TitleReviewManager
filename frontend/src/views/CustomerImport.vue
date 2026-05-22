<template>
  <div class="import-page">
    <!-- Word 模板导入 -->
    <el-card class="import-card">
      <template #header>
        <div class="card-header">
          <el-icon><Document /></el-icon>
          <span>Word 模板导入（客户填写）</span>
        </div>
      </template>
      <el-alert type="success" :closable="false" style="margin-bottom: 16px">
        <template #title>
          流程：下载 Word 模板 → 发给客户填写 → 业务员上传解析 → 自动创建客户
        </template>
      </el-alert>
      <div class="word-actions">
        <el-button type="primary" @click="downloadTemplate">
          <el-icon><Download /></el-icon> 下载 Word 模板
        </el-button>
        <el-upload
          ref="wordUploadRef"
          :before-upload="beforeWordUpload"
          :show-file-list="false"
          :limit="1"
          :auto-upload="false"
          accept=".docx"
          :on-change="handleWordChange"
        >
          <template #trigger>
            <el-button type="success">
              <el-icon><Upload /></el-icon> 选择已填写的 Word 文件
            </el-button>
          </template>
        </el-upload>
        <el-input
          v-if="!wordFile"
          class="file-input-placeholder"
          placeholder="请选择一个 .docx 文件"
          :disabled="true"
          :suffix-icon="null"
        />
        <el-input
          v-if="wordFile"
          class="file-input-value"
          :model-value="wordFile.name"
          :disabled="true"
          :prefix-icon="null"
        />
        <el-button type="warning" @click="submitWord" :loading="wordLoading">
          <el-icon><Check /></el-icon> 开始解析导入
        </el-button>
      </div>
    </el-card>

    <!-- Excel 批量导入 -->
    <el-card class="import-card">
      <template #header>
        <div class="card-header">
          <el-icon><Upload /></el-icon>
          <span>Excel 批量导入</span>
        </div>
      </template>
      <el-alert type="info" :closable="false" style="margin-bottom: 16px">
        <template #title>
          Excel 格式要求：第一行为列名，必须包含「客户姓名」「身份证号」，可选「手机号」「学历」「现职称」「工作单位」「岗位」
        </template>
      </el-alert>
      <div class="excel-actions">
        <el-button type="primary" @click="downloadExcelTemplate">
          <el-icon><Download /></el-icon> 下载 Excel 模板
        </el-button>
        <el-upload
          ref="excelUploadRef"
          :before-upload="beforeUpload"
          :show-file-list="false"
          :limit="1"
          :auto-upload="false"
          accept=".xlsx,.xls"
          :on-change="handleExcelChange"
        >
          <template #trigger>
            <el-button type="success">
              <el-icon><Upload /></el-icon> 选择已填写的 Excel 文件
            </el-button>
          </template>
        </el-upload>
        <el-input
          v-if="!excelFile"
          class="file-input-placeholder"
          placeholder="请选择一个 .xlsx / .xls 文件"
          :disabled="true"
          :suffix-icon="null"
        />
        <el-input
          v-if="excelFile"
          class="file-input-value"
          :model-value="excelFile.name"
          :disabled="true"
          :prefix-icon="null"
        />
        <el-button type="warning" @click="submitUpload" :loading="loading">
          <el-icon><Check /></el-icon> 开始解析导入
        </el-button>
      </div>
    </el-card>
    <el-card v-if="result" class="result-card" :class="{ success: result.success > 0, error: result.errors?.length > 0 }">
      <template #header>
        <div class="card-header">
          <el-icon><Finished /></el-icon>
          <span>导入结果</span>
        </div>
      </template>
      <p v-if="result.message">{{ result.message }}</p>
      <p v-if="result.customer_id">客户ID：<strong>{{ result.customer_id }}</strong></p>
      <p v-if="result.batch_number">申报批次：<strong>{{ result.batch_number }}</strong></p>
      <p v-if="result.success !== undefined">成功：<strong>{{ result.success }}</strong> / {{ result.total }}</p>
      <el-collapse v-if="result.errors?.length">
        <el-collapse-item title="查看失败详情（{{ result.errors.length }} 条）">
          <pre class="error-detail">{{ result.errors.join('\n') }}</pre>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <el-card style="margin-top: 16px">
      <template #header>
        <div class="card-header">
          <el-icon><Download /></el-icon>
          <span>导出客户数据</span>
        </div>
      </template>
      <el-space>
        <el-button @click="doExport('customers')">
          <el-icon><Download /></el-icon> 导出客户列表
        </el-button>
        <el-button @click="doExport('applications')">
          <el-icon><Download /></el-icon> 导出申报批次
        </el-button>
      </el-space>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import api from '../api'
import { ElMessage } from 'element-plus'

const wordUploadRef = ref<any>(null)
const excelUploadRef = ref<any>(null)
const wordFile = ref<File | null>(null)
const excelFile = ref<File | null>(null)
const wordLoading = ref(false)
const loading = ref(false)
const result = ref<any>(null)

// Word 模板相关
function downloadTemplate() {
  window.open('/api/word-import/template', '_blank')
}

function beforeWordUpload(file: File) {
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (ext !== 'docx') {
    ElMessage.warning('仅支持 .docx 文件')
    return false
  }
  return true
}

function handleWordChange(file: any) {
  wordFile.value = file.raw
}

async function submitWord() {
  if (!wordFile.value) {
    ElMessage.warning('请先选择 Word 文件')
    return
  }
  wordLoading.value = true
  const formData = new FormData()
  formData.append('file', wordFile.value)
  try {
    const { data } = await api.post('/api/word-import/parse', formData)
    result.value = data
    ElMessage.success(data.message || '导入成功')
    wordFile.value = null
    if (wordUploadRef.value) {
      (wordUploadRef.value as any).clearFiles()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '导入失败')
  } finally {
    wordLoading.value = false
  }
}

// Excel 相关
function downloadExcelTemplate() {
  window.open('/api/exports/template', '_blank')
}

function beforeUpload(file: File) {
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!ext || !['xlsx', 'xls'].includes(ext)) {
    ElMessage.warning('仅支持 .xlsx / .xls 文件')
    return false
  }
  return true
}

function handleExcelChange(file: any) {
  excelFile.value = file.raw
}

async function submitUpload() {
  if (!excelFile.value) {
    ElMessage.warning('请先选择 Excel 文件')
    return
  }
  loading.value = true
  const formData = new FormData()
  formData.append('file', excelFile.value)
  try {
    const { data } = await api.post('/api/imports/customers', formData)
    result.value = data
    ElMessage.success(data.message || '导入完成')
    excelFile.value = null
    if (excelUploadRef.value) {
      (excelUploadRef.value as any).clearFiles()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '导入失败')
  } finally {
    loading.value = false
  }
}

async function doExport(type: string) {
  try {
    const response = await api.post(`/api/exports/${type}`, null, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = type === 'customers' ? '客户列表.xlsx' : '申报批次.xlsx'
    link.click()
    window.URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '导出失败')
  }
}
</script>

<style scoped>
.import-page {
  width: 100%;
}
.import-card, .result-card {
  margin-bottom: 16px;
  border-radius: 12px;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.word-actions,
.excel-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.word-actions :deep(.el-upload),
.excel-actions :deep(.el-upload) {
  display: inline-flex;
  align-items: center;
}

.word-actions .file-input-placeholder,
.word-actions .file-input-value,
.excel-actions .file-input-placeholder,
.excel-actions .file-input-value {
  flex: 1 1 180px;
  min-width: 140px;
  max-width: 320px;
}
</style>
