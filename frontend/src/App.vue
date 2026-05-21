<template>
  <div v-loading="loading" element-loading-text="加载中..." v-if="loading" style="height: 100vh" />
  <router-view v-else />
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from './stores/auth'

const authStore = useAuthStore()
const loading = ref(true)

onMounted(async () => {
  if (authStore.token && !authStore.user) {
    await authStore.fetchUser()
  }
  loading.value = false
})
</script>
