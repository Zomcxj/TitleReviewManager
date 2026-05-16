<template>
  <div class="follow-up-timeline">
    <div class="timeline-header">
      <h4>跟进记录</h4>
      <el-button type="primary" size="small" @click="showAddDialog = true">
        <el-icon><Plus /></el-icon>
        新增跟进
      </el-button>
    </div>
    
    <div class="timeline-list" v-loading="loading">
      <div v-if="followUps.length === 0" class="empty-state">
        <p>暂无跟进记录</p>
      </div>
      
      <div v-for="fu in followUps" :key="fu.id" class="timeline-item">
        <div class="timeline-dot"></div>
        <div class="timeline-content">
          <div class="timeline-header-row">
            <span class="user-name">{{ fu.username || '未知' }}</span>
            <el-tag :type="getTypeTag(fu.follow_up_type)" size="small">{{ getTypeLabel(fu.follow_up_type) }}</el-tag>
            <span class="time">{{ formatTime(fu.created_at) }}</span>
          </div>
          <div class="timeline-text">{{ fu.content }}</div>
          <div v-if="fu.next_follow_up_at" class="next-reminder">
            <el-icon><AlarmClock /></el-icon>
            下次跟进：{{ formatDate(fu.next_follow_up_at) }}
          </div>
        </div>
      </div>
    </div>
    
    <el-dialog v-model="showAddDialog" title="新增跟进记录" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="跟进方式">
          <el-select v-model="form.follow_up_type" style="width: 100%">
            <el-option label="电话" value="phone" />
            <el-option label="微信" value="wechat" />
            <el-option label="邮件" value="email" />
            <el-option label="面谈" value="meeting" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="跟进内容" required>
          <el-input v-model="form.content" type="textarea" :rows="4" placeholder="记录本次沟通情况" />
        </el-form-item>
        <el-form-item label="下次跟进">
          <el-date-picker
            v-model="form.next_follow_up_at"
            type="datetime"
            placeholder="选择下次跟进时间"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, defineProps } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

interface FollowUp {
  id: number
  customer_id: number
  user_id: number
  username: string
  content: string
  follow_up_type: string
  next_follow_up_at: string | null
  created_at: string
}

const props = defineProps<{ customerId: number }>()

const loading = ref(false)
const followUps = ref<FollowUp[]>([])
const showAddDialog = ref(false)
const submitting = ref(false)
const form = ref({
  follow_up_type: 'phone',
  content: '',
  next_follow_up_at: null as Date | null,
})

async function loadFollowUps() {
  loading.value = true
  try {
    const { data } = await axios.get(`/api/follow-ups/customer/${props.customerId}`)
    followUps.value = data
  } catch (e) {
    ElMessage.error('加载跟进记录失败')
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  if (!form.value.content.trim()) {
    ElMessage.warning('请输入跟进内容')
    return
  }
  
  submitting.value = true
  try {
    await axios.post('/api/follow-ups/', {
      customer_id: props.customerId,
      ...form.value,
    })
    ElMessage.success('添加成功')
    showAddDialog.value = false
    form.value = { follow_up_type: 'phone', content: '', next_follow_up_at: null }
    loadFollowUps()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '添加失败')
  } finally {
    submitting.value = false
  }
}

function getTypeLabel(type: string): string {
  const map: Record<string, string> = {
    phone: '电话',
    wechat: '微信',
    email: '邮件',
    meeting: '面谈',
    other: '其他',
  }
  return map[type] || type
}

function getTypeTag(type: string): string {
  const map: Record<string, string> = {
    phone: '',
    wechat: 'success',
    email: 'primary',
    meeting: 'warning',
    other: 'info',
  }
  return map[type] || 'info'
}

function formatTime(time: string): string {
  return new Date(time).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDate(time: string): string {
  return new Date(time).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(loadFollowUps)
</script>

<style scoped>
.follow-up-timeline {
  margin-top: 24px;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.timeline-header h4 {
  margin: 0;
  font-size: 14px;
  color: #303133;
}

.timeline-list {
  position: relative;
}

.timeline-item {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}

.timeline-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #409EFF;
  flex-shrink: 0;
  margin-top: 4px;
}

.timeline-content {
  flex: 1;
  background: #f5f7fa;
  padding: 12px 16px;
  border-radius: 8px;
}

.timeline-header-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.user-name {
  font-weight: 600;
  color: #303133;
  font-size: 13px;
}

.time {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}

.timeline-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}

.next-reminder {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 12px;
  color: #e6a23c;
  background: #fdf6ec;
  padding: 4px 8px;
  border-radius: 4px;
  width: fit-content;
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: #909399;
}
</style>
