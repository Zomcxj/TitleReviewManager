<template>
  <div class="dashboard-page">
    <div class="stats-grid">
      <el-statistic title="客户总数" :value="stats.total_customers">
        <template #prefix>👥</template>
      </el-statistic>
      <el-statistic title="申报总数" :value="stats.total_applications">
        <template #prefix>📋</template>
      </el-statistic>
      <el-statistic title="今日新增" :value="stats.today_new" value-style="color: #67c23a">
        <template #prefix>📈</template>
      </el-statistic>
      <el-statistic title="本周新增" :value="stats.week_new" value-style="color: #409eff">
        <template #prefix>📊</template>
      </el-statistic>
    </div>

    <el-card style="margin-top: 24px">
      <template #header>
        <h4>状态分布</h4>
      </template>
      <el-table :data="statusData" style="width: 100%">
        <el-table-column prop="status" label="状态" />
        <el-table-column prop="count" label="数量" width="100" />
      </el-table>
    </el-card>

    <el-card style="margin-top: 16px">
      <template #header>
        <h4>快速入口</h4>
      </template>
      <div class="quick-actions">
        <router-link to="/admin/customers">
          <el-button type="primary">客户管理</el-button>
        </router-link>
        <router-link to="/admin/reviews">
          <el-button type="success">审核工作台</el-button>
        </router-link>
        <router-link to="/admin/public-pool" v-if="authStore.isSalesman || authStore.isAdmin">
          <el-button type="warning">公海池</el-button>
        </router-link>
        <router-link to="/admin/audit-logs" v-if="authStore.isAdmin">
          <el-button type="info">审计日志</el-button>
        </router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import axios from 'axios'

const authStore = useAuthStore()
const stats = ref({
  total_customers: 0,
  total_applications: 0,
  today_new: 0,
  week_new: 0,
  status_distribution: {},
})

const statusData = computed(() => {
  return Object.entries(stats.value.status_distribution || {}).map(([name, count]) => ({
    status: name,
    count: count as number,
  }))
})

async function loadStats() {
  try {
    const { data } = await axios.get('/api/dashboard/stats')
    stats.value = data
  } catch (e) {
    console.error('Failed to load stats:', e)
  }
}

onMounted(loadStats)
</script>

<style scoped>
.dashboard-page {
  padding: 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.el-statistic {
  background: #fff;
  padding: 20px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.el-card h4 {
  margin: 0;
  font-size: 15px;
  color: #303133;
}

.quick-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
