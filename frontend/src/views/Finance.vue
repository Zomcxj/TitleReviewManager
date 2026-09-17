<template>
  <div class="finance-page" v-loading="loading">
    <div class="page-header">
      <div class="header-left">
        <h2>收费与证书管理</h2>
        <p class="header-sub">合同金额、回款登记与证书发放跟踪</p>
      </div>
      <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
    </div>

    <template v-if="isAdmin">
      <div class="stat-grid">
        <el-card class="stat-card" shadow="never">
          <div class="stat-label">总合同额</div>
          <div class="stat-value">¥ {{ formatMoney(summary.total_fee) }}</div>
        </el-card>
        <el-card class="stat-card" shadow="never">
          <div class="stat-label">已收金额</div>
          <div class="stat-value success">¥ {{ formatMoney(summary.total_paid) }}</div>
        </el-card>
        <el-card class="stat-card" shadow="never">
          <div class="stat-label">未收金额</div>
          <div class="stat-value danger">¥ {{ formatMoney(summary.total_unpaid) }}</div>
        </el-card>
      </div>

      <el-row :gutter="16" class="summary-row">
        <el-col :span="14">
          <el-card class="panel-card" shadow="never">
            <template #header>
              <div class="panel-header">
                <span>按业务员汇总</span>
                <span class="panel-hint">{{ summary.by_salesman.length }} 人</span>
              </div>
            </template>
            <el-table :data="summary.by_salesman" size="small" border>
              <el-table-column prop="name" label="业务员" min-width="120" />
              <el-table-column prop="customer_count" label="客户数" width="90" align="center" />
              <el-table-column label="合同额" width="130" align="right">
                <template #default="{ row }">¥ {{ formatMoney(row.total_fee) }}</template>
              </el-table-column>
              <el-table-column label="已收" width="130" align="right">
                <template #default="{ row }">¥ {{ formatMoney(row.total_paid) }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!summary.by_salesman.length" description="暂无数据" :image-size="60" />
          </el-card>
        </el-col>
        <el-col :span="10">
          <el-card class="panel-card" shadow="never">
            <template #header>
              <div class="panel-header"><span>证书状态分布</span></div>
            </template>
            <el-table :data="certificateRows" size="small" border>
              <el-table-column prop="name" label="状态" min-width="120" />
              <el-table-column prop="count" label="批次数量" width="100" align="center" />
            </el-table>
            <el-empty v-if="!certificateRows.length" description="暂无数据" :image-size="60" />
            <div class="status-dist">
              <el-tag v-for="(count, status) in summary.by_status" :key="status" class="status-tag" effect="plain">
                {{ status }}：{{ count }}
              </el-tag>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <el-card class="panel-card" shadow="never">
      <template #header>
        <div class="panel-header">
          <span>待收款提醒</span>
          <span class="panel-hint">共 {{ pendingList.length }} 条，按欠款金额倒序</span>
        </div>
      </template>

      <el-table
        :data="pendingList"
        row-key="application_id"
        style="width: 100%"
        v-loading="loading"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-area">
              <div class="expand-header">
                <span class="expand-title">回款明细</span>
                <span class="expand-sub" v-if="row.payment_records?.length">
                  共 {{ row.payment_records.length }} 条
                </span>
              </div>
              <el-table :data="row.payment_records || []" size="small" border>
                <el-table-column label="金额" width="140">
                  <template #default="{ row: p }">¥ {{ formatMoney(p.amount) }}</template>
                </el-table-column>
                <el-table-column label="回款日期" width="180">
                  <template #default="{ row: p }">{{ formatDate(p.paid_at) }}</template>
                </el-table-column>
                <el-table-column prop="method" label="方式" width="100">
                  <template #default="{ row: p }">{{ p.method || '-' }}</template>
                </el-table-column>
                <el-table-column prop="remark" label="备注" min-width="160">
                  <template #default="{ row: p }">{{ p.remark || '-' }}</template>
                </el-table-column>
                <el-table-column v-if="isAdmin" label="操作" width="90" align="center">
                  <template #default="{ row: p }">
                    <el-button type="danger" link size="small" @click="handleDeletePayment(row, p)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty
                v-if="!row.payment_records?.length"
                description="暂无回款记录"
                :image-size="50"
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="batch_number" label="批次号" min-width="150" />
        <el-table-column prop="customer_name" label="客户名" min-width="100" />
        <el-table-column prop="salesman_name" label="业务员" min-width="100" />
        <el-table-column label="合同额" width="130" align="right">
          <template #default="{ row }">¥ {{ formatMoney(row.fee_amount) }}</template>
        </el-table-column>
        <el-table-column label="已收" width="130" align="right">
          <template #default="{ row }">¥ {{ formatMoney(row.paid_amount) }}</template>
        </el-table-column>
        <el-table-column label="欠款" width="130" align="right">
          <template #default="{ row }">
            <span class="unpaid-amount">¥ {{ formatMoney(row.unpaid_amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="openPaymentDialog(row)">登记回款</el-button>
            <el-button size="small" @click="openEditDialog(row)">编辑收费信息</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无待收款记录" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 登记回款 -->
    <el-dialog v-model="paymentDialogVisible" title="登记回款" width="460px">
      <el-form :model="paymentForm" label-position="top">
        <el-form-item label="批次号">
          <el-input :model-value="currentRow?.batch_number" disabled />
        </el-form-item>
        <el-form-item label="欠款金额">
          <el-input :model-value="'¥ ' + formatMoney(currentRow?.unpaid_amount)" disabled />
        </el-form-item>
        <el-form-item label="回款金额" required>
          <el-input-number v-model="paymentForm.amount" :min="0.01" :precision="2" :step="100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="回款日期" required>
          <el-date-picker
            v-model="paymentForm.paid_at"
            type="date"
            placeholder="选择日期"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 100%"
          />
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
        <el-button @click="paymentDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmitPayment">确认登记</el-button>
      </template>
    </el-dialog>

    <!-- 编辑收费信息 -->
    <el-dialog v-model="editDialogVisible" title="编辑收费信息" width="620px">
      <el-form :model="editForm" label-position="top">
        <el-divider content-position="left">合同与收费</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="合同号">
              <el-input v-model="editForm.contract_no" placeholder="请输入合同号" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="合同签订日期">
              <el-date-picker
                v-model="editForm.contract_signed_at"
                type="date"
                placeholder="选择日期"
                value-format="YYYY-MM-DDTHH:mm:ss"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="合同金额">
              <el-input-number v-model="editForm.fee_amount" :min="0" :precision="2" :step="100" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="收费状态">
              <el-select v-model="editForm.payment_status" style="width: 100%">
                <el-option v-for="s in PAYMENT_STATUSES" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="收费备注">
          <el-input v-model="editForm.payment_remark" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>

        <el-divider content-position="left">证书信息</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="证书状态">
              <el-select v-model="editForm.certificate_status" style="width: 100%">
                <el-option v-for="s in CERTIFICATE_STATUSES" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="证书编号">
              <el-input v-model="editForm.certificate_no" placeholder="请输入证书编号" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="发证日期">
              <el-date-picker
                v-model="editForm.certificate_issued_at"
                type="date"
                placeholder="选择日期"
                value-format="YYYY-MM-DDTHH:mm:ss"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="交付日期">
              <el-date-picker
                v-model="editForm.certificate_delivered_at"
                type="date"
                placeholder="选择日期"
                value-format="YYYY-MM-DDTHH:mm:ss"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const PAYMENT_STATUSES = ['未收费', '部分收费', '已结清', '已退款']
const CERTIFICATE_STATUSES = ['未发证', '已发证', '已交付']

interface PaymentRecord {
  id: number
  application_id: number
  amount: number
  paid_at: string
  method: string | null
  remark: string | null
  created_by_id: number | null
  created_at: string
}

interface PendingRow {
  application_id: number
  batch_number: string
  customer_id: number
  customer_name: string
  salesman_id: number | null
  salesman_name: string
  fee_amount: number
  paid_amount: number
  unpaid_amount: number
  payment_status: string
  created_at: string
  payment_records?: PaymentRecord[]
}

interface SalesmanAgg {
  salesman_id: number | null
  name: string
  customer_count: number
  total_fee: number
  total_paid: number
}

const loading = ref(false)
const submitting = ref(false)
const pendingList = ref<PendingRow[]>([])

const summary = reactive<{
  total_fee: number
  total_paid: number
  total_unpaid: number
  by_status: Record<string, number>
  by_salesman: SalesmanAgg[]
  certificate_by_status: Record<string, number>
}>({
  total_fee: 0,
  total_paid: 0,
  total_unpaid: 0,
  by_status: {},
  by_salesman: [],
  certificate_by_status: {},
})

const certificateRows = computed(() =>
  Object.entries(summary.certificate_by_status || {}).map(([name, count]) => ({ name, count }))
)

const currentRow = ref<PendingRow | null>(null)

const paymentDialogVisible = ref(false)
const paymentForm = reactive({
  amount: 0,
  paid_at: '',
  method: '转账',
  remark: '',
})

const editDialogVisible = ref(false)
const editForm = reactive({
  contract_no: '',
  contract_signed_at: '',
  fee_amount: undefined as number | undefined,
  payment_status: '未收费',
  payment_remark: '',
  certificate_status: '未发证',
  certificate_no: '',
  certificate_issued_at: '',
  certificate_delivered_at: '',
})

function formatMoney(value: number | null | undefined) {
  const num = Number(value ?? 0)
  return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatDate(value: string | null | undefined) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN')
}

function todayString() {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T00:00:00`
}

async function loadSummary() {
  if (!isAdmin.value) return
  try {
    const { data } = await api.get('/api/finance/summary')
    summary.total_fee = data.total_fee ?? 0
    summary.total_paid = data.total_paid ?? 0
    summary.total_unpaid = data.total_unpaid ?? 0
    summary.by_status = data.by_status ?? {}
    summary.by_salesman = data.by_salesman ?? []
    summary.certificate_by_status = data.certificate_by_status ?? {}
  } catch (e: any) {
    if (e.response?.status !== 403) {
      ElMessage.error(e.response?.data?.detail || '加载财务总览失败')
    }
  }
}

async function loadPending() {
  try {
    const { data } = await api.get('/api/finance/pending')
    const rows: PendingRow[] = (data || []).map((row: PendingRow) => ({ ...row, payment_records: [] }))
    pendingList.value = rows
    // 并行拉取每个批次的回款明细，供展开行展示
    await Promise.all(rows.map(async (row) => {
      try {
        const res = await api.get(`/api/finance/application/${row.application_id}`)
        row.payment_records = res.data.payment_records || []
      } catch {
        row.payment_records = []
      }
    }))
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载待收款列表失败')
  }
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadSummary(), loadPending()])
  } finally {
    loading.value = false
  }
}

function openPaymentDialog(row: PendingRow) {
  currentRow.value = row
  paymentForm.amount = Number(row.unpaid_amount || 0)
  paymentForm.paid_at = todayString()
  paymentForm.method = '转账'
  paymentForm.remark = ''
  paymentDialogVisible.value = true
}

async function handleSubmitPayment() {
  if (!currentRow.value) return
  if (!paymentForm.amount || paymentForm.amount <= 0) {
    ElMessage.warning('回款金额必须大于 0')
    return
  }
  submitting.value = true
  try {
    await api.post(`/api/finance/application/${currentRow.value.application_id}/payments`, {
      amount: paymentForm.amount,
      paid_at: paymentForm.paid_at || null,
      method: paymentForm.method || null,
      remark: paymentForm.remark || null,
    })
    ElMessage.success('回款已登记')
    paymentDialogVisible.value = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '登记回款失败')
  } finally {
    submitting.value = false
  }
}

async function openEditDialog(row: PendingRow) {
  currentRow.value = row
  try {
    const { data } = await api.get(`/api/finance/application/${row.application_id}`)
    editForm.contract_no = data.contract_no || ''
    editForm.contract_signed_at = data.contract_signed_at || ''
    editForm.fee_amount = data.fee_amount ?? undefined
    editForm.payment_status = data.payment_status || '未收费'
    editForm.payment_remark = data.payment_remark || ''
    editForm.certificate_status = data.certificate_status || '未发证'
    editForm.certificate_no = data.certificate_no || ''
    editForm.certificate_issued_at = data.certificate_issued_at || ''
    editForm.certificate_delivered_at = data.certificate_delivered_at || ''
    editDialogVisible.value = true
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载收费信息失败')
  }
}

async function handleSubmitEdit() {
  if (!currentRow.value) return
  submitting.value = true
  try {
    await api.put(`/api/finance/application/${currentRow.value.application_id}`, {
      contract_no: editForm.contract_no || null,
      contract_signed_at: editForm.contract_signed_at || null,
      fee_amount: editForm.fee_amount ?? null,
      payment_status: editForm.payment_status || null,
      payment_remark: editForm.payment_remark || null,
      certificate_status: editForm.certificate_status || null,
      certificate_no: editForm.certificate_no || null,
      certificate_issued_at: editForm.certificate_issued_at || null,
      certificate_delivered_at: editForm.certificate_delivered_at || null,
    })
    ElMessage.success('收费信息已保存')
    editDialogVisible.value = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function handleDeletePayment(row: PendingRow, payment: PaymentRecord) {
  try {
    await ElMessageBox.confirm(
      `确认删除该笔回款记录（¥ ${formatMoney(payment.amount)}）？删除后将重新汇总已收金额。`,
      '删除回款记录',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await api.delete(`/api/finance/payments/${payment.id}`)
    ElMessage.success('回款记录已删除')
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(loadAll)
</script>

<style scoped>
.finance-page {
  padding: 4px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.header-sub {
  margin: 0;
  font-size: 13px;
  color: #94a3b8;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.stat-label {
  font-size: 13px;
  color: #94a3b8;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
  margin-top: 6px;
}

.stat-value.success {
  color: #16a34a;
}

.stat-value.danger {
  color: #dc2626;
}

.summary-row {
  margin-bottom: 16px;
}

.panel-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.panel-hint {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 400;
}

.status-dist {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.status-tag {
  margin: 0;
}

.unpaid-amount {
  color: #dc2626;
  font-weight: 600;
}

.expand-area {
  padding: 8px 24px 16px;
  background: #fbfcfe;
}

.expand-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.expand-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.expand-sub {
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 900px) {
  .stat-grid {
    grid-template-columns: 1fr;
  }
}
</style>
