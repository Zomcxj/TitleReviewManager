<template>
  <div class="registration-links">
    <div class="page-header">
      <h3>专属注册链接管理</h3>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon> 生成新链接
      </el-button>
    </div>

    <el-table :data="tokens" v-loading="loading" style="width: 100%">
      <el-table-column label="专属链接" min-width="300">
        <template #default="{ row }">
          <div class="link-cell">
            <el-input :model-value="row.full_link || getFullLink(row.token)" readonly size="small" style="width: 100%">
              <template #append>
                <el-button @click="copyLink(row)">
                  <el-icon><CopyDocument /></el-icon>
                </el-button>
              </template>
            </el-input>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="业务员" width="120">
        <template #default="{ row }">
          {{ row.salesman_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="过期时间" width="180">
        <template #default="{ row }">
          <span :class="{ expired: isExpired(row.expires_at) }">
            {{ formatDate(row.expires_at) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="使用次数" width="120">
        <template #default="{ row }">
          <span v-if="row.max_uses === 0">{{ row.use_count }} / ∞</span>
          <span v-else>{{ row.use_count }} / {{ row.max_uses }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="getStatusType(row)" size="small" round>{{ getStatusText(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.is_active" type="danger" text size="small" @click="deactivateToken(row.id)">
            停用
          </el-button>
          <template v-else>
            <el-button type="danger" text size="small" @click="deleteToken(row.id)">删除</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showCreateDialog" title="生成专属注册链接" width="480px">
      <el-form label-position="top">
        <el-form-item label="使用次数限制">
          <el-radio-group v-model="createForm.max_uses">
            <el-radio :value="1">1次</el-radio>
            <el-radio :value="5">5次</el-radio>
            <el-radio :value="10">10次</el-radio>
            <el-radio :value="50">50次</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="有效期">
          <el-select v-model="createForm.expires_days" style="width: 100%">
            <el-option :value="1" label="1天" />
            <el-option :value="3" label="3天" />
            <el-option :value="7" label="7天" />
            <el-option :value="14" label="14天" />
            <el-option :value="30" label="30天" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const tokens = ref<any[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const createForm = ref({ max_uses: 1, expires_days: 7 })

function getFullLink(token: string) {
  return `${window.location.origin}/apply?token=${token}`
}

function formatDate(d: string) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN')
}

function isExpired(d: string) {
  return new Date(d) < new Date()
}

function getStatusType(row: any) {
  if (!row.is_active) return 'info'
  if (isExpired(row.expires_at)) return 'danger'
  if (row.max_uses > 0 && row.use_count >= row.max_uses) return 'warning'
  return 'success'
}

function getStatusText(row: any) {
  if (!row.is_active) return '已停用'
  if (isExpired(row.expires_at)) return '已过期'
  if (row.max_uses > 0 && row.use_count >= row.max_uses) return '已达上限'
  return '有效'
}

async function loadTokens() {
  loading.value = true
  try {
    const { data } = await api.get('/api/registration-links/')
    tokens.value = data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  try {
    await api.post('/api/registration-links/', createForm.value)
    ElMessage.success('链接已生成')
    showCreateDialog.value = false
    loadTokens()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  }
}

async function deactivateToken(id: number) {
  try {
    await ElMessageBox.confirm('确认停用此链接？停用后客户将无法再通过此链接注册。', '停用确认')
    await api.delete(`/api/registration-links/${id}`)
    ElMessage.success('链接已停用')
    loadTokens()
  } catch {
    // 用户取消确认属正常流程；接口失败由 api 拦截器统一提示
  }
}

function copyLink(row: any) {
  const url = row.full_link || getFullLink(row.token)
  navigator.clipboard.writeText(url).then(() => {
    ElMessage.success('链接已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败，请手动复制')
  })
}

async function deleteToken(id: number) {
  try {
    await ElMessageBox.confirm('确认彻底删除此链接？此操作不可恢复。', '删除确认')
    await api.delete(`/api/registration-links/${id}/hard`)
    ElMessage.success('链接已删除')
    loadTokens()
  } catch {
    // 用户取消确认属正常流程；接口失败由 api 拦截器统一提示
  }
}

onMounted(loadTokens)
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #1e293b;
}
.link-cell {
  padding: 2px 0;
}
.expired {
  color: #ef4444;
  text-decoration: line-through;
}
</style>
