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
      <div class="header-actions">
        <el-button v-if="isSalesman" type="warning" @click="showTransferDialog = true">
          <el-icon><Switch /></el-icon> 转让客户
        </el-button>
        <el-button v-if="canSubmitReview" type="success" @click="handleReadyForReview">
          <el-icon><Check /></el-icon> 提交审核员审核
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
              <el-descriptions-item label="报考职称">
                <template v-if="isSalesman">
                  <el-select v-model="inlineTargetTitle" placeholder="请选择或输入报考职称" size="small" filterable allow-create
                    style="width: 160px" @change="handleSaveTargetTitle">
                    <el-option label="初级工程师" value="初级工程师" />
                    <el-option label="中级工程师" value="中级工程师" />
                    <el-option label="高级工程师" value="高级工程师" />
                  </el-select>
                </template>
                <span v-else>{{ customer.target_title || '-' }}</span>
              </el-descriptions-item>
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

          <el-tab-pane label="收费与证书" name="finance" v-if="currentAppId">
            <div class="finance-tab" v-loading="financeLoading">
              <div class="finance-section">
                <div class="finance-section-header">
                  <h4 class="section-title">收费信息</h4>
                  <el-button v-if="canEditFinance" type="primary" size="small" @click="openFinanceEdit">
                    编辑收费信息
                  </el-button>
                </div>
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="合同号">{{ finance.contract_no || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="合同签订日期">{{ formatDate(finance.contract_signed_at) }}</el-descriptions-item>
                  <el-descriptions-item label="合同金额">
                    {{ finance.fee_amount != null ? '¥ ' + formatMoney(finance.fee_amount) : '-' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="已收金额">
                    <span class="paid-amount">¥ {{ formatMoney(finance.paid_amount) }}</span>
                  </el-descriptions-item>
                  <el-descriptions-item label="收费状态">
                    <el-tag :type="paymentStatusType(finance.payment_status)" effect="plain" round size="small">
                      {{ finance.payment_status || '-' }}
                    </el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="收费备注">{{ finance.payment_remark || '-' }}</el-descriptions-item>
                </el-descriptions>
              </div>

              <div class="finance-section">
                <div class="finance-section-header">
                  <h4 class="section-title">回款记录</h4>
                  <el-button v-if="canEditFinance" type="primary" size="small" @click="openPaymentDialog">
                    登记回款
                  </el-button>
                </div>
                <el-table :data="finance.payment_records || []" size="small" border>
                  <el-table-column label="金额" width="140">
                    <template #default="{ row }">¥ {{ formatMoney(row.amount) }}</template>
                  </el-table-column>
                  <el-table-column label="回款日期" width="180">
                    <template #default="{ row }">{{ formatDate(row.paid_at) }}</template>
                  </el-table-column>
                  <el-table-column prop="method" label="方式" width="100">
                    <template #default="{ row }">{{ row.method || '-' }}</template>
                  </el-table-column>
                  <el-table-column prop="remark" label="备注" min-width="160">
                    <template #default="{ row }">{{ row.remark || '-' }}</template>
                  </el-table-column>
                  <el-table-column v-if="authStore.isAdmin" label="操作" width="90" align="center">
                    <template #default="{ row }">
                      <el-button type="danger" link size="small" @click="handleDeletePayment(row)">删除</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-if="!(finance.payment_records || []).length" description="暂无回款记录" :image-size="60" />
              </div>

              <div class="finance-section">
                <div class="finance-section-header">
                  <h4 class="section-title">证书信息</h4>
                  <el-button v-if="canEditFinance" type="primary" size="small" @click="openCertificateEdit">
                    编辑证书信息
                  </el-button>
                </div>
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="证书状态">
                    <el-tag :type="certificateStatusType(finance.certificate_status)" effect="plain" round size="small">
                      {{ finance.certificate_status || '-' }}
                    </el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="证书编号">{{ finance.certificate_no || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="发证日期">{{ formatDate(finance.certificate_issued_at) }}</el-descriptions-item>
                  <el-descriptions-item label="交付日期">{{ formatDate(finance.certificate_delivered_at) }}</el-descriptions-item>
                </el-descriptions>
              </div>
            </div>
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
            <div v-if="app.cycle_year || app.cycle_deadline" class="app-item-cycle">
              <el-tag v-if="app.cycle_year" size="small" effect="plain" type="info">{{ app.cycle_year }}年度</el-tag>
              <el-tag v-if="app.cycle_deadline" size="small" effect="plain" type="warning">
                截止 {{ formatMonthDay(app.cycle_deadline) }}
              </el-tag>
            </div>
            <div v-if="canEditCycle" class="app-item-actions">
              <el-button type="primary" text size="small" @click.stop="openCycleDialog(app)">
                <el-icon><Calendar /></el-icon> 设置申报周期
              </el-button>
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

    <el-dialog v-model="showFinanceEditDialog" title="编辑收费信息" width="560px">
      <el-form :model="financeEditForm" label-position="top">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="合同号">
              <el-input v-model="financeEditForm.contract_no" placeholder="请输入合同号" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="合同签订日期">
              <el-date-picker v-model="financeEditForm.contract_signed_at" type="date" placeholder="选择日期"
                value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="合同金额">
              <el-input-number v-model="financeEditForm.fee_amount" :min="0" :precision="2" :step="100"
                style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="收费状态">
              <el-select v-model="financeEditForm.payment_status" style="width: 100%">
                <el-option v-for="s in PAYMENT_STATUSES" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="收费备注">
          <el-input v-model="financeEditForm.payment_remark" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showFinanceEditDialog = false">取消</el-button>
        <el-button type="primary" :loading="financeSubmitting" @click="handleSaveFinance">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCertificateEditDialog" title="编辑证书信息" width="480px">
      <el-form :model="certificateEditForm" label-position="top">
        <el-form-item label="证书状态">
          <el-select v-model="certificateEditForm.certificate_status" style="width: 100%">
            <el-option v-for="s in CERTIFICATE_STATUSES" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="证书编号">
          <el-input v-model="certificateEditForm.certificate_no" placeholder="请输入证书编号" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="发证日期">
              <el-date-picker v-model="certificateEditForm.certificate_issued_at" type="date" placeholder="选择日期"
                value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="交付日期">
              <el-date-picker v-model="certificateEditForm.certificate_delivered_at" type="date" placeholder="选择日期"
                value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="showCertificateEditDialog = false">取消</el-button>
        <el-button type="primary" :loading="financeSubmitting" @click="handleSaveCertificate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showPaymentDialog" title="登记回款" width="460px">
      <el-form :model="paymentForm" label-position="top">
        <el-form-item label="回款金额" required>
          <el-input-number v-model="paymentForm.amount" :min="0.01" :precision="2" :step="100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="回款日期" required>
          <el-date-picker v-model="paymentForm.paid_at" type="date" placeholder="选择日期"
            value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
        </el-form-item>
        <el-form-item label="回款方式">
          <el-select v-model="paymentForm.method" placeholder="请选择回款方式" style="width: 100%">
            <el-option label="现金" value="现金" />
            <el-option label="转账" value="转账" />
            <el-option label="微信" value="微信" />
            <el-option label="支付宝" value="支付宝" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="paymentForm.remark" type="textarea" :rows="3" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPaymentDialog = false">取消</el-button>
        <el-button type="primary" :loading="financeSubmitting" @click="handleSubmitPayment">确认登记</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCycleDialog" title="设置申报周期" width="420px">
      <el-form label-position="top">
        <el-form-item label="申报年度">
          <el-input-number v-model="cycleForm.cycle_year" :min="2000" :max="2100" :controls="false"
            placeholder="如 2026" style="width: 100%" />
        </el-form-item>
        <el-form-item label="申报截止时间">
          <el-date-picker v-model="cycleForm.cycle_deadline" type="datetime" placeholder="选择截止时间"
            value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCycleDialog = false">取消</el-button>
        <el-button type="primary" :loading="cycleSubmitting" @click="handleSaveCycle">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showTransferDialog" title="转让客户" width="400px">
      <el-form label-position="top">
        <el-form-item label="转让给">
          <el-select v-model="transferTargetId" placeholder="请选择业务员" style="width: 100%">
            <el-option v-for="s in salesmenList" :key="s.id" :label="`${s.real_name} (${s.username})`" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTransferDialog = false">取消</el-button>
        <el-button type="warning" @click="handleTransfer" :loading="transferLoading">确认转让</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import MaterialUpload from './MaterialUpload.vue'
import FollowUpTimeline from '../components/FollowUpTimeline.vue'
import { Calendar, ChatDotRound, Check, RefreshRight, Switch, Upload, WarningFilled } from '@element-plus/icons-vue'

const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const customer = ref<any>(null)
const applications = ref<any[]>([])
const reviews = ref<any[]>([])
const logs = ref<any[]>([])
const materials = ref<any[]>([])
const activeTab = ref('basic')
const currentAppId = ref<number | null>(null)

const showSubmitDialog = ref(false)
const showFeedbackDialog = ref(false)
const showTransferDialog = ref(false)
const showCycleDialog = ref(false)
const cycleSubmitting = ref(false)
const cycleForm = reactive({
  application_id: null as number | null,
  cycle_year: undefined as number | undefined,
  cycle_deadline: '',
})
const institutionName = ref('')
const feedbackType = ref('通过')
const feedbackContent = ref('')
const inlineTargetTitle = ref('')
const salesmenList = ref<any[]>([])
const transferTargetId = ref<number | null>(null)
const transferLoading = ref(false)

// ---------- 收费与证书 ----------
const PAYMENT_STATUSES = ['未收费', '部分收费', '已结清', '已退款']
const CERTIFICATE_STATUSES = ['未发证', '已发证', '已交付']

const finance = ref<any>({
  contract_no: null,
  contract_signed_at: null,
  fee_amount: null,
  paid_amount: 0,
  payment_status: null,
  payment_remark: null,
  certificate_status: null,
  certificate_no: null,
  certificate_issued_at: null,
  certificate_delivered_at: null,
  payment_records: [],
})
const financeLoading = ref(false)
const financeSubmitting = ref(false)
const showFinanceEditDialog = ref(false)
const showCertificateEditDialog = ref(false)
const showPaymentDialog = ref(false)

const financeEditForm = reactive({
  contract_no: '',
  contract_signed_at: '',
  fee_amount: undefined as number | undefined,
  payment_status: '未收费',
  payment_remark: '',
})

const certificateEditForm = reactive({
  certificate_status: '未发证',
  certificate_no: '',
  certificate_issued_at: '',
  certificate_delivered_at: '',
})

const paymentForm = reactive({
  amount: 0,
  paid_at: '',
  method: '转账',
  remark: '',
})

const canEditFinance = computed(() => authStore.isAdmin || authStore.isSalesman)

function formatMoney(value: number | null | undefined) {
  const num = Number(value ?? 0)
  return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function paymentStatusType(status: string | null) {
  const map: Record<string, string> = {
    '未收费': 'info',
    '部分收费': 'warning',
    '已结清': 'success',
    '已退款': 'danger',
  }
  return map[status || ''] || 'info'
}

function certificateStatusType(status: string | null) {
  const map: Record<string, string> = {
    '未发证': 'info',
    '已发证': 'warning',
    '已交付': 'success',
  }
  return map[status || ''] || 'info'
}

function todayString() {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T00:00:00`
}

async function loadFinance(appId: number) {
  financeLoading.value = true
  try {
    const { data } = await api.get(`/api/finance/application/${appId}`)
    finance.value = data
  } catch (e: any) {
    if (e.response?.status !== 403) {
      ElMessage.error(e.response?.data?.detail || '加载收费信息失败')
    }
  } finally {
    financeLoading.value = false
  }
}

function openFinanceEdit() {
  financeEditForm.contract_no = finance.value.contract_no || ''
  financeEditForm.contract_signed_at = finance.value.contract_signed_at || ''
  financeEditForm.fee_amount = finance.value.fee_amount ?? undefined
  financeEditForm.payment_status = finance.value.payment_status || '未收费'
  financeEditForm.payment_remark = finance.value.payment_remark || ''
  showFinanceEditDialog.value = true
}

function openCertificateEdit() {
  certificateEditForm.certificate_status = finance.value.certificate_status || '未发证'
  certificateEditForm.certificate_no = finance.value.certificate_no || ''
  certificateEditForm.certificate_issued_at = finance.value.certificate_issued_at || ''
  certificateEditForm.certificate_delivered_at = finance.value.certificate_delivered_at || ''
  showCertificateEditDialog.value = true
}

function openPaymentDialog() {
  paymentForm.amount = 0
  paymentForm.paid_at = todayString()
  paymentForm.method = '转账'
  paymentForm.remark = ''
  showPaymentDialog.value = true
}

async function handleSaveFinance() {
  if (!currentAppId.value) return
  financeSubmitting.value = true
  try {
    const { data } = await api.put(`/api/finance/application/${currentAppId.value}`, {
      contract_no: financeEditForm.contract_no || null,
      contract_signed_at: financeEditForm.contract_signed_at || null,
      fee_amount: financeEditForm.fee_amount ?? null,
      payment_status: financeEditForm.payment_status || null,
      payment_remark: financeEditForm.payment_remark || null,
    })
    finance.value = data
    ElMessage.success('收费信息已保存')
    showFinanceEditDialog.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    financeSubmitting.value = false
  }
}

async function handleSaveCertificate() {
  if (!currentAppId.value) return
  financeSubmitting.value = true
  try {
    const { data } = await api.put(`/api/finance/application/${currentAppId.value}`, {
      certificate_status: certificateEditForm.certificate_status || null,
      certificate_no: certificateEditForm.certificate_no || null,
      certificate_issued_at: certificateEditForm.certificate_issued_at || null,
      certificate_delivered_at: certificateEditForm.certificate_delivered_at || null,
    })
    finance.value = data
    ElMessage.success('证书信息已保存')
    showCertificateEditDialog.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    financeSubmitting.value = false
  }
}

async function handleSubmitPayment() {
  if (!currentAppId.value) return
  if (!paymentForm.amount || paymentForm.amount <= 0) {
    ElMessage.warning('回款金额必须大于 0')
    return
  }
  financeSubmitting.value = true
  try {
    const { data } = await api.post(`/api/finance/application/${currentAppId.value}/payments`, {
      amount: paymentForm.amount,
      paid_at: paymentForm.paid_at || null,
      method: paymentForm.method || null,
      remark: paymentForm.remark || null,
    })
    finance.value = data
    ElMessage.success('回款已登记')
    showPaymentDialog.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '登记回款失败')
  } finally {
    financeSubmitting.value = false
  }
}

async function handleDeletePayment(record: any) {
  try {
    await ElMessageBox.confirm(
      `确认删除该笔回款记录（¥ ${formatMoney(record.amount)}）？删除后将重新汇总已收金额。`,
      '删除回款记录',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await api.delete(`/api/finance/payments/${record.id}`)
    ElMessage.success('回款记录已删除')
    if (currentAppId.value) await loadFinance(currentAppId.value)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

const currentApp = computed(() => applications.value.find(a => a.id === currentAppId.value) || null)

const projectExperiences = computed(() => {
  if (!customer.value?.project_experiences) return []
  try { return JSON.parse(customer.value.project_experiences) } catch { return [] }
})

const isSalesman = computed(() => authStore.isSalesman || authStore.isAdmin)

// 申报周期设置：仅管理员/业务员
const canEditCycle = computed(() => authStore.isAdmin || authStore.isSalesman)

const canSubmitReview = computed(() => {
  return isSalesman.value && currentApp.value && ['初次申报', '资料补充', '二次申报'].includes(currentApp.value.status)
})
const canSubmitToInstitution = computed(() => {
  if (!isSalesman.value || !currentApp.value) return false
  // 只有所有材料都已通过时才显示"提交评审机构"
  if (materials.value.length === 0) return false
  return materials.value.every((m: any) => m.audit_status === '已通过')
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
  if (tab === 'finance' && currentAppId.value) loadFinance(currentAppId.value)
})
// 每 10 秒自动刷新状态（审核员通过后按钮自动变为"提交评审机构"）
let statusPollTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  statusPollTimer = setInterval(() => {
    if (route.params.id) {
      api.get(`/api/customers/${route.params.id}`).then(({ data }) => {
        if (data.applications) {
          applications.value = data.applications
        }
      }).catch(() => {})
      // 同步刷新材料状态以更新按钮
      if (currentAppId.value) {
        loadMaterials(currentAppId.value)
      }
    }
  }, 10000)
})
onUnmounted(() => {
  if (statusPollTimer) clearInterval(statusPollTimer)
})

async function loadData() {
  loading.value = true
  try {
    const { data } = await api.get(`/api/customers/${route.params.id}`)
    customer.value = data
    applications.value = data.applications || []
    if (applications.value.length && !currentAppId.value) {
      currentAppId.value = applications.value[0].id
      loadMaterials(applications.value[0].id)
    }
    // 初始化报考职称输入框
    inlineTargetTitle.value = data.target_title || ''
  } finally {
    loading.value = false
  }
}

function selectApp(app: any) {
  currentAppId.value = app.id
  reviews.value = []
  logs.value = []
  loadMaterials(app.id)
  if (activeTab.value === 'finance') loadFinance(app.id)
}

async function loadMaterials(appId: number) {
  try {
    const { data } = await api.get(`/api/applications/${appId}/materials/`)
    materials.value = data.items || []
  } catch {
    materials.value = []
  }
}

async function loadReviews(appId: number) {
  const { data } = await api.get(`/api/reviews/application/${appId}`)
  reviews.value = data
}

async function loadLogs(appId: number) {
  const { data } = await api.get(`/api/feedback/application/${appId}/logs`)
  logs.value = data
}

/** 提交前材料清单校验：缺料时弹窗提示并返回 false（中止提交） */
async function ensureMaterialsComplete(appId: number): Promise<boolean> {
  try {
    const { data } = await api.get(`/api/applications/${appId}/material-checklist`)
    if (!data.is_complete) {
      const missing = (data.missing || []).join('、')
      ElMessageBox.alert(
        `缺少必传材料：${missing}，请补齐后再提交`,
        '材料不齐全',
        { type: 'warning', confirmButtonText: '我知道了' }
      ).catch(() => {})
      return false
    }
    return true
  } catch {
    // 清单接口异常时放行，由后端兜底校验
    return true
  }
}

async function handleReadyForReview() {
  if (!currentAppId.value) return
  if (!(await ensureMaterialsComplete(currentAppId.value))) return
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
  if (!currentApp.value) return
  // 提交前先校验材料清单：缺料直接中止，避免后端 400
  if (!(await ensureMaterialsComplete(currentApp.value.id))) return
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

function formatMonthDay(d: string) {
  if (!d) return '-'
  const date = new Date(d)
  if (Number.isNaN(date.getTime())) return '-'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function openCycleDialog(app: any) {
  cycleForm.application_id = app.id
  cycleForm.cycle_year = app.cycle_year ?? undefined
  cycleForm.cycle_deadline = app.cycle_deadline ? String(app.cycle_deadline).slice(0, 19) : ''
  showCycleDialog.value = true
}

async function handleSaveCycle() {
  if (!cycleForm.application_id) return
  cycleSubmitting.value = true
  try {
    await api.put(`/api/applications/${cycleForm.application_id}/cycle`, {
      cycle_year: cycleForm.cycle_year ?? null,
      cycle_deadline: cycleForm.cycle_deadline || null,
    })
    ElMessage.success('申报周期已保存')
    showCycleDialog.value = false
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    cycleSubmitting.value = false
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

async function handleSaveTargetTitle() {
  if (!customer.value) return
  try {
    const val = inlineTargetTitle.value || null
    const { data } = await api.put(`/api/customers/${customer.value.id}`, { target_title: val })
    customer.value.target_title = data.target_title || val
    ElMessage.success('报考职称已保存')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
}

async function loadSalesmen() {
  try {
    const { data } = await api.get('/api/customers/salesmen')
    salesmenList.value = data || []
  } catch (e: any) {
    console.error('加载业务员失败', e)
  }
}

async function handleTransfer() {
  if (!transferTargetId.value || !customer.value) {
    ElMessage.warning('请选择目标业务员')
    return
  }
  transferLoading.value = true
  try {
    await api.put(`/api/customers/${customer.value.id}/transfer`, null, {
      params: { salesman_id: transferTargetId.value },
    })
    ElMessage.success('客户转让成功')
    showTransferDialog.value = false
    transferTargetId.value = null
    loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '转让失败')
  } finally {
    transferLoading.value = false
  }
}

watch(() => showTransferDialog.value, (val) => {
  if (val) {
    loadSalesmen()
    transferTargetId.value = null
  }
})
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
.app-item-cycle {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.app-item-actions {
  margin-top: 4px;
  text-align: right;
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
.info-descriptions :deep(.el-descriptions__label) {
  background: #6366f1;
  color: #fff;
  font-weight: 600;
}
.info-descriptions :deep(.el-descriptions__content) {
  color: #1e293b;
  font-weight: 500;
  background: #f8fafc;
}
.finance-tab {
  padding: 8px 0 16px;
}
.finance-section {
  margin-bottom: 24px;
}
.finance-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.finance-section-header .section-title {
  margin: 0;
}
.paid-amount {
  color: #16a34a;
  font-weight: 600;
}
</style>
