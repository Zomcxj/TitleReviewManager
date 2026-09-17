<template>
  <div class="system-config-page" v-loading="loading">
    <div class="page-header">
      <div class="header-left">
        <h2>系统配置</h2>
        <p class="header-sub">调整公海限额、SLA 时长、登录锁定等运行参数，保存后立即生效</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadConfig">刷新</el-button>
        <el-button type="warning" :icon="RefreshLeft" @click="handleReset">恢复默认值</el-button>
      </div>
    </div>

    <el-alert
      v-if="changedKeys.length"
      type="info"
      :closable="false"
      show-icon
      class="changed-alert"
    >
      <template #title>有 {{ changedKeys.length }} 项配置已修改，尚未保存</template>
      {{ changedKeys.map(k => configs[k].label).join('、') }}
    </el-alert>

    <el-card class="config-card" shadow="never">
      <el-table :data="configRows" style="width: 100%">
        <el-table-column prop="label" label="配置项名称" min-width="200">
          <template #default="{ row }">
            <span class="config-label">{{ row.label }}</span>
            <span class="config-key">{{ row.key }}</span>
          </template>
        </el-table-column>
        <el-table-column label="当前值" width="140" align="center">
          <template #default="{ row }">
            <el-tag :type="isChanged(row.key) ? 'warning' : 'info'" effect="plain" round>
              {{ row.original }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认值" width="120" align="center">
          <template #default="{ row }">
            <span class="default-value">{{ row.default }}</span>
          </template>
        </el-table-column>
        <el-table-column label="修改为" width="200">
          <template #default="{ row }">
            <el-input-number
              v-model="configs[row.key].value"
              :min="0"
              :step="1"
              :precision="0"
              controls-position="right"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="isChanged(row.key)" type="warning" size="small" round>待保存</el-tag>
            <span v-else class="no-change">-</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无配置项" :image-size="80" />
        </template>
      </el-table>

      <div class="save-bar">
        <span class="save-hint">仅提交已修改的配置项</span>
        <el-button
          type="primary"
          :disabled="!changedKeys.length"
          :loading="saving"
          @click="handleSave"
        >
          保存{{ changedKeys.length ? `（${changedKeys.length} 项）` : '' }}
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, RefreshLeft } from '@element-plus/icons-vue'

interface ConfigEntry {
  value: number
  label: string
  default: number
}

const loading = ref(false)
const saving = ref(false)
const configs = reactive<Record<string, ConfigEntry>>({})
const originals = reactive<Record<string, number>>({})

const configRows = computed(() =>
  Object.entries(configs).map(([key, entry]) => ({
    key,
    label: entry.label,
    default: entry.default,
    original: originals[key],
  }))
)

const changedKeys = computed(() =>
  Object.keys(configs).filter((key) => Number(configs[key].value) !== Number(originals[key]))
)

function isChanged(key: string) {
  return Number(configs[key]?.value) !== Number(originals[key])
}

function applyConfigs(data: Record<string, ConfigEntry>) {
  Object.keys(configs).forEach((key) => delete configs[key])
  Object.keys(originals).forEach((key) => delete originals[key])
  Object.entries(data || {}).forEach(([key, entry]) => {
    configs[key] = { value: Number(entry.value), label: entry.label, default: entry.default }
    originals[key] = Number(entry.value)
  })
}

async function loadConfig() {
  loading.value = true
  try {
    const { data } = await api.get('/api/system-config/')
    applyConfigs(data)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载系统配置失败')
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  if (!changedKeys.value.length) return
  const payload: Record<string, number> = {}
  changedKeys.value.forEach((key) => {
    payload[key] = Number(configs[key].value)
  })
  saving.value = true
  try {
    const { data } = await api.put('/api/system-config/', payload)
    applyConfigs(data.configs || {})
    ElMessage.success(`已保存 ${changedKeys.value.length || Object.keys(payload).length} 项配置`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleReset() {
  try {
    await ElMessageBox.confirm(
      '确认将所有系统配置恢复为默认值？当前自定义的参数将被覆盖。',
      '恢复默认值',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  loading.value = true
  try {
    const { data } = await api.post('/api/system-config/reset')
    applyConfigs(data.configs || {})
    ElMessage.success(data.message || '已恢复默认配置')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '恢复默认值失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.system-config-page {
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

.header-actions {
  display: flex;
  gap: 8px;
}

.changed-alert {
  margin-bottom: 16px;
}

.config-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.config-label {
  font-size: 14px;
  font-weight: 500;
  color: #1e293b;
  margin-right: 8px;
}

.config-key {
  font-size: 12px;
  color: #94a3b8;
  font-family: 'SF Mono', 'Monaco', monospace;
}

.default-value {
  color: #94a3b8;
}

.no-change {
  color: #cbd5e1;
}

.save-bar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 16px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}

.save-hint {
  font-size: 12px;
  color: #94a3b8;
}
</style>
