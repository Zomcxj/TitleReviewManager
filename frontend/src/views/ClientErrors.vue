<template>
  <div class="client-errors-page">
    <div class="page-header">
      <div class="header-left">
        <h2>前端错误</h2>
        <p class="subtitle">前端运行时异常与接口 5xx 的自动上报记录，用于排查线上问题</p>
      </div>
      <el-button type="danger" :loading="clearing" :disabled="!pagination.total" @click="handleClearAll">
        <el-icon><Delete /></el-icon> 清空全部
      </el-button>
    </div>

    <el-table v-loading="loading" :data="items" style="width: 100%">
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="用户" width="120">
        <template #default="{ row }">
          <span v-if="row.username">{{ row.username }}</span>
          <span v-else class="muted">未登录</span>
        </template>
      </el-table-column>
      <el-table-column label="页面" min-width="180">
        <template #default="{ row }">
          <span class="url-cell">{{ row.url || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="错误信息" min-width="300" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="message-cell">{{ row.message }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="ip_address" label="IP" width="140">
        <template #default="{ row }">{{ row.ip_address || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无错误记录" />
      </template>
    </el-table>

    <div class="pagination">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="fetchErrors"
        @current-change="fetchErrors"
      />
    </div>

    <el-dialog v-model="detailVisible" title="错误详情" width="760px" top="6vh">
      <template v-if="current">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="时间">{{ formatTime(current.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="用户">
            <span v-if="current.username">{{ current.username }}</span>
            <span v-else class="muted">未登录</span>
          </el-descriptions-item>
          <el-descriptions-item label="页面">{{ current.url || '-' }}</el-descriptions-item>
          <el-descriptions-item label="IP">{{ current.ip_address || '-' }}</el-descriptions-item>
          <el-descriptions-item label="User-Agent">
            <span class="ua-cell">{{ current.user_agent || '-' }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <div class="detail-block">
          <div class="detail-label">错误信息</div>
          <pre class="detail-pre">{{ current.message }}</pre>
        </div>

        <div class="detail-block">
          <div class="detail-label">堆栈</div>
          <pre class="detail-pre stack">{{ current.stack || '（无堆栈信息）' }}</pre>
        </div>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import api from '../api'

interface ClientError {
  id: number
  username: string | null
  message: string
  stack: string | null
  url: string | null
  user_agent: string | null
  ip_address: string | null
  created_at: string | null
}

const loading = ref(false)
const clearing = ref(false)
const items = ref<ClientError[]>([])
const detailVisible = ref(false)
const current = ref<ClientError | null>(null)

const pagination = reactive({
  page: 1,
  page_size: 20,
  total: 0,
})

/** 后端返回 ISO 时间，格式化为 YYYY-MM-DD HH:mm:ss（本地时区），不引入 dayjs */
function formatTime(time: string | null | undefined): string {
  if (!time) return '-'
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return String(time)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function fetchErrors() {
  loading.value = true
  try {
    const { data } = await api.get('/api/client-errors/', {
      params: { page: pagination.page, page_size: pagination.page_size },
    })
    items.value = data.items || []
    pagination.total = data.total || 0
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载前端错误失败')
  } finally {
    loading.value = false
  }
}

function openDetail(row: ClientError) {
  current.value = row
  detailVisible.value = true
}

async function handleDelete(row: ClientError) {
  try {
    await ElMessageBox.confirm('确定删除这条错误记录吗？', '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api.delete(`/api/client-errors/${row.id}`)
    ElMessage.success('已删除')
    // 删除后当前页可能为空，回退一页
    if (items.value.length === 1 && pagination.page > 1) {
      pagination.page -= 1
    }
    await fetchErrors()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

async function handleClearAll() {
  try {
    await ElMessageBox.confirm('确定清空全部前端错误记录吗？此操作不可恢复。', '警告', {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  clearing.value = true
  try {
    const { data } = await api.delete('/api/client-errors/')
    ElMessage.success(data?.message || '已清空')
    pagination.page = 1
    await fetchErrors()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '清空失败')
  } finally {
    clearing.value = false
  }
}

onMounted(fetchErrors)
</script>

<style scoped>
.client-errors-page {
  padding: 20px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 600;
  color: #0f172a;
}

.subtitle {
  margin: 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.6;
}

.muted {
  color: #909399;
}

.url-cell,
.message-cell {
  word-break: break-all;
}

.ua-cell {
  word-break: break-all;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.detail-block {
  margin-top: 16px;
}

.detail-label {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 6px;
}

.detail-pre {
  margin: 0;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-family: Consolas, Monaco, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow: auto;
}

.detail-pre.stack {
  max-height: 320px;
}
</style>
