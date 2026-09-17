<template>
  <div class="progress-page">
    <div class="progress-header">
      <div class="brand">
        <div class="brand-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
          </svg>
        </div>
        <div class="brand-text">
          <h2>申报进度查询</h2>
          <p>输入您的身份证号与手机号后 4 位，自助查询申报批次进度</p>
        </div>
      </div>
    </div>

    <el-card class="query-card" shadow="never">
      <el-form :model="form" :rules="rules" ref="formRef" label-position="top" @submit.prevent="handleQuery">
        <el-form-item label="身份证号" prop="id_number">
          <el-input
            v-model="form.id_number"
            placeholder="请输入完整 18 位身份证号"
            maxlength="18"
            size="large"
            clearable
            @keyup.enter="handleQuery"
          />
        </el-form-item>
        <el-form-item label="手机号后 4 位" prop="phone_tail">
          <el-input
            v-model="form.phone_tail"
            placeholder="请输入手机号后 4 位数字"
            maxlength="4"
            size="large"
            clearable
            @input="onPhoneTailInput"
            @keyup.enter="handleQuery"
          />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="query-btn" @click="handleQuery">
          查询进度
        </el-button>
      </el-form>

      <el-alert
        v-if="errorMessage"
        type="error"
        :title="errorMessage"
        show-icon
        :closable="false"
        class="error-alert"
      />
    </el-card>

    <div v-if="result" class="result-area">
      <el-card class="result-header-card" shadow="never">
        <div class="result-header">
          <div class="result-avatar">{{ (result.customer_name || '客').charAt(0) }}</div>
          <div class="result-info">
            <div class="result-name">{{ result.customer_name }}</div>
            <div class="result-sub">共 {{ result.items.length }} 个申报批次</div>
          </div>
        </div>
      </el-card>

      <el-empty v-if="!result.items.length" description="暂无申报批次" :image-size="80" />

      <el-card v-for="(item, idx) in result.items" :key="idx" class="batch-card" shadow="never">
        <template #header>
          <div class="batch-header">
            <div class="batch-title">
              <span class="batch-number">{{ item.batch_number }}</span>
              <el-tag :type="statusType(item.status)" effect="plain" round size="small">
                {{ item.status }}
              </el-tag>
            </div>
            <span class="batch-year">{{ item.cycle_year ? item.cycle_year + ' 年度' : '年度未设置' }}</span>
          </div>
        </template>

        <el-descriptions :column="3" border size="small" class="batch-descriptions">
          <el-descriptions-item label="专业类别">{{ item.professional_category || '-' }}</el-descriptions-item>
          <el-descriptions-item label="职称级别">{{ item.title_level || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当前状态">{{ item.status || '-' }}</el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatDate(item.submitted_at) }}</el-descriptions-item>
          <el-descriptions-item label="最近更新" :span="2">{{ formatDate(item.updated_at) }}</el-descriptions-item>
        </el-descriptions>

        <div class="section-block">
          <h4 class="section-title">进度时间线</h4>
          <el-steps :active="activeStep(item.progress_steps)" align-center finish-status="success" class="progress-steps">
            <el-step v-for="step in item.progress_steps" :key="step.name" :title="step.name" />
          </el-steps>
        </div>

        <div class="section-block">
          <h4 class="section-title">材料统计</h4>
          <div class="material-stats">
            <div class="stat-item">
              <span class="stat-value">{{ item.materials_summary?.total ?? 0 }}</span>
              <span class="stat-label">材料总数</span>
            </div>
            <div class="stat-item passed">
              <span class="stat-value">{{ item.materials_summary?.passed ?? 0 }}</span>
              <span class="stat-label">已通过</span>
            </div>
            <div class="stat-item flagged">
              <span class="stat-value">{{ item.materials_summary?.flagged ?? 0 }}</span>
              <span class="stat-label">已标记问题</span>
            </div>
            <div class="stat-item pending">
              <span class="stat-value">{{ item.materials_summary?.pending ?? 0 }}</span>
              <span class="stat-label">待审核</span>
            </div>
          </div>
        </div>

        <div v-if="item.latest_feedback" class="section-block">
          <h4 class="section-title">机构反馈</h4>
          <el-alert type="info" :closable="false" show-icon>
            <template #title>最新反馈</template>
            {{ item.latest_feedback }}
          </el-alert>
        </div>
      </el-card>
    </div>

    <div class="footer-link">
      <el-link type="primary" :underline="false" @click="$router.push('/login')">返回登录</el-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import api from '../api'

interface ProgressStep {
  name: string
  done: boolean
}

interface MaterialsSummary {
  total: number
  passed: number
  flagged: number
  pending: number
}

interface ProgressItem {
  batch_number: string
  professional_category: string | null
  title_level: string | null
  status: string
  cycle_year: number | null
  submitted_at: string | null
  updated_at: string | null
  progress_steps: ProgressStep[]
  materials_summary: MaterialsSummary
  latest_feedback: string | null
}

const formRef = ref()
const loading = ref(false)
const errorMessage = ref('')
const result = ref<{ customer_name: string; items: ProgressItem[] } | null>(null)

const form = reactive({
  id_number: '',
  phone_tail: '',
})

const rules = {
  id_number: [
    { required: true, message: '请输入身份证号', trigger: 'blur' },
    { pattern: /^\d{17}[\dXx]$/, message: '请输入正确的 18 位身份证号', trigger: 'blur' },
  ],
  phone_tail: [
    { required: true, message: '请输入手机号后 4 位', trigger: 'blur' },
    { pattern: /^\d{4}$/, message: '手机号后 4 位必须为 4 位数字', trigger: 'blur' },
  ],
}

function onPhoneTailInput(value: string) {
  form.phone_tail = (value || '').replace(/\D/g, '').slice(0, 4)
}

function statusType(status: string) {
  const map: Record<string, string> = {
    '初次申报': '',
    '资料补充': 'warning',
    '完成资料': 'success',
    '提交评审机构审核': '',
    '返修': 'danger',
    '通过': 'success',
    '不通过': 'danger',
    '二次申报': '',
  }
  return map[status] || 'info'
}

function formatDate(value: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN')
}

function activeStep(steps: ProgressStep[] | undefined) {
  if (!steps || !steps.length) return 0
  let active = 0
  steps.forEach((step, index) => {
    if (step.done) active = index + 1
  })
  return active
}

async function handleQuery() {
  errorMessage.value = ''
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  result.value = null
  try {
    const { data } = await api.post('/api/public-progress/query', {
      id_number: form.id_number.trim(),
      phone_tail: form.phone_tail.trim(),
    })
    result.value = data
  } catch (e: any) {
    const status = e.response?.status
    const detail = e.response?.data?.detail
    if (status === 404) {
      errorMessage.value = detail || '未查询到申报记录，请核对身份证号与手机号后4位'
    } else if (status === 429) {
      errorMessage.value = detail || '查询过于频繁，请稍后再试'
    } else {
      errorMessage.value = detail || '查询失败，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.progress-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 32px 16px 60px;
  min-height: 100vh;
  background: #f8fafc;
  box-sizing: border-box;
}

.progress-header {
  margin-bottom: 24px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-icon {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}

.brand-text h2 {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.3px;
}

.brand-text p {
  margin: 0;
  color: #64748b;
  font-size: 14px;
}

.query-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.query-btn {
  width: 100%;
  height: 44px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
}

.error-alert {
  margin-top: 16px;
}

.result-area {
  margin-top: 24px;
}

.result-header-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  margin-bottom: 16px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 14px;
}

.result-avatar {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 600;
}

.result-name {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.result-sub {
  font-size: 13px;
  color: #64748b;
  margin-top: 2px;
}

.batch-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  margin-bottom: 16px;
}

.batch-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.batch-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.batch-number {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.batch-year {
  font-size: 13px;
  color: #94a3b8;
}

.batch-descriptions {
  margin-bottom: 20px;
}

.section-block {
  margin-top: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 12px;
}

.progress-steps {
  padding: 8px 0;
}

.material-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 8px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #334155;
}

.stat-label {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
}

.stat-item.passed .stat-value {
  color: #16a34a;
}

.stat-item.flagged .stat-value {
  color: #dc2626;
}

.stat-item.pending .stat-value {
  color: #d97706;
}

.footer-link {
  margin-top: 32px;
  text-align: center;
}

@media (max-width: 640px) {
  .material-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
