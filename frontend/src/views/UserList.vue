<template>
  <div class="user-management">
    <div class="page-toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="showCreateDialog = true">
          <el-icon><Plus /></el-icon> 新增用户
        </el-button>
      </div>
    </div>

    <el-table :data="users" border stripe v-loading="loading" style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" align="center" />
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column prop="real_name" label="姓名" min-width="120">
        <template #default="{ row }">
          {{ row.real_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="role" label="角色" width="120" align="center">
        <template #default="{ row }">
          <el-tag :type="roleTagType(row.role)" size="small" effect="dark" round>
            {{ roleLabel(row.role) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="密码" min-width="120">
        <template #default>
          ******
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="170">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" align="center" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" text size="small" @click="handleEdit(row)">
            <el-icon><Edit /></el-icon> 编辑
          </el-button>
          <el-button type="warning" text size="small" @click="openPasswordDialog(row)">
            <el-icon><Key /></el-icon> 改密
          </el-button>
          <el-button type="danger" text size="small" @click="handleDelete(row)" :disabled="row.id === currentUserId">
            <el-icon><Delete /></el-icon> 删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create User Dialog -->
    <el-dialog v-model="showCreateDialog" title="新增用户" width="480px" @close="resetForm">
      <el-form :model="form" label-position="top" :rules="rules" ref="formRef">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="字母、数字、下划线" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少6位" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="业务员" value="salesman" />
            <el-option label="审核员" value="reviewer" />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名" prop="real_name">
          <el-input v-model="form.real_name" placeholder="真实姓名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="submitting">确认新增</el-button>
      </template>
    </el-dialog>

    <!-- Edit User Dialog -->
    <el-dialog v-model="showEditDialog" title="编辑用户" width="480px" @close="resetEditVerification">
      <el-form :model="editForm" label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="editForm.username" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editForm.role" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="业务员" value="salesman" />
            <el-option label="审核员" value="reviewer" />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="editForm.real_name" />
        </el-form-item>
        <el-form-item label="密码">
          <div v-if="!adminPasswordVerified" class="password-locked">
            <el-input model-value="******" disabled />
            <el-button type="primary" text @click="showVerifyInput = true" style="margin-top: 8px">
              <el-icon><Key /></el-icon> 输入管理员密码查看
            </el-button>
            <div v-if="showVerifyInput" style="margin-top: 8px; display: flex; gap: 8px">
              <el-input v-model="adminPassword" type="password" show-password placeholder="输入当前管理员密码" style="flex: 1" />
              <el-button type="primary" @click="verifyAdminPassword" :loading="verifyingPassword">验证</el-button>
            </div>
          </div>
          <el-input v-else v-model="editForm.password" type="password" show-password placeholder="留空则不修改密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="handleUpdate" :loading="submitting">保存修改</el-button>
      </template>
    </el-dialog>

    <!-- Reset Password Dialog -->
    <el-dialog v-model="showPasswordDialog" :title="`修改密码 - ${pwTargetUser?.username || ''}`" width="400px">
      <el-form :model="pwForm" label-position="top">
        <el-form-item label="管理员密码">
          <el-input v-model="pwForm.admin_password" type="password" show-password placeholder="输入当前管理员密码以确认" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwForm.new_password" type="password" show-password placeholder="至少6位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPasswordDialog = false">取消</el-button>
        <el-button type="primary" @click="handleResetPassword" :loading="submitting">确认修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'
import { ElMessage, ElMessageBox } from 'element-plus'

const authStore = useAuthStore()
const users = ref<any[]>([])
const loading = ref(false)
const submitting = ref(false)
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const showPasswordDialog = ref(false)
const adminPasswordVerified = ref(false)
const adminPassword = ref('')
const showVerifyInput = ref(false)
const verifyingPassword = ref(false)
const currentUserId = computed(() => authStore.user?.id)

const form = ref({ username: '', password: '', role: 'salesman', real_name: '' })
const editForm = ref({ id: 0, username: '', role: '', real_name: '', password: '' })
const pwForm = ref({ admin_password: '', new_password: '' })
const pwTargetUser = ref<any>(null)
const formRef = ref<any>(null)

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { min: 6, message: '至少6位', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function roleTagType(role: string) {
  const map: Record<string, string> = { admin: 'danger', salesman: 'primary', reviewer: 'warning' }
  return map[role] || 'info'
}
function roleLabel(role: string) {
  const map: Record<string, string> = { admin: '管理员', salesman: '业务员', reviewer: '审核员' }
  return map[role] || role
}
function formatDate(d: string) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN')
}

async function loadUsers() {
  loading.value = true
  try {
    const { data } = await api.get('/api/users/')
    users.value = data
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.value = { username: '', password: '', role: 'salesman', real_name: '' }
}

async function handleCreate() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    await api.post('/api/users/', form.value)
    ElMessage.success('用户已创建')
    showCreateDialog.value = false
    loadUsers()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    submitting.value = false
  }
}

function resetEditVerification() {
  adminPasswordVerified.value = false
  adminPassword.value = ''
  showVerifyInput.value = false
}

async function verifyAdminPassword() {
  if (!adminPassword.value) {
    ElMessage.warning('请输入管理员密码')
    return
  }
  verifyingPassword.value = true
  try {
    const { data } = await api.post('/api/users/verify-admin-password', { password: adminPassword.value, user_id: editForm.value.id })
    adminPasswordVerified.value = true
    showVerifyInput.value = false
    editForm.value.password = data.password || ''
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '密码验证失败')
  } finally {
    verifyingPassword.value = false
  }
}

function handleEdit(row: any) {
  editForm.value = { id: row.id, username: row.username, role: row.role, real_name: row.real_name || '', password: '' }
  resetEditVerification()
  showEditDialog.value = true
}

async function handleUpdate() {
  submitting.value = true
  try {
    const body: any = { username: editForm.value.username, role: editForm.value.role, real_name: editForm.value.real_name }
    if (editForm.value.password) body.password = editForm.value.password
    await api.put(`/api/users/${editForm.value.id}`, body)
    ElMessage.success('已保存')
    showEditDialog.value = false
    loadUsers()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除用户「${row.username}」？此操作不可恢复。`, '删除确认', { type: 'warning' })
    await api.delete(`/api/users/${row.id}`)
    ElMessage.success('已删除')
    loadUsers()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

function openPasswordDialog(row: any) {
  pwTargetUser.value = row
  pwForm.value = { admin_password: '', new_password: '' }
  showPasswordDialog.value = true
}

async function handleResetPassword() {
  if (!pwForm.value.admin_password || !pwForm.value.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  if (pwForm.value.new_password.length < 6) {
    ElMessage.warning('新密码至少6位')
    return
  }
  submitting.value = true
  try {
    await api.post(`/api/users/${pwTargetUser.value.id}/reset-password`, {
      admin_password: pwForm.value.admin_password,
      new_password: pwForm.value.new_password,
    })
    ElMessage.success('密码已修改')
    showPasswordDialog.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '修改失败')
  } finally {
    submitting.value = false
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.user-management {
  width: 100%;
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.password-locked {
  width: 100%;
}
.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
</style>
