import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<any>(null)
  const token = ref<string | null>(localStorage.getItem('access_token'))

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isSalesman = computed(() => user.value?.role === 'salesman')
  const isReviewer = computed(() => user.value?.role === 'reviewer')

  async function login(username: string, password: string) {
    const { data } = await api.post('/api/auth/login', { username, password })
    token.value = 'logged-in'
    localStorage.setItem('access_token', 'logged-in')
    user.value = data.user
    // 存储用户角色到 localStorage，供路由守卫使用
    if (data.user?.role) {
      localStorage.setItem('user_role', data.user.role)
    }
    return data
  }

  async function fetchUser() {
    try {
      const { data } = await api.get('/api/auth/me')
      user.value = data
      if (data?.role) {
        localStorage.setItem('user_role', data.role)
      }
    } catch {
      user.value = null
      token.value = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_role')
    }
  }

  async function logout() {
    try {
      await api.post('/api/auth/logout')
    } catch {
      // 即使 API 失败也要清除本地状态
    }
    user.value = null
    token.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('user_role')
  }

  return { user, token, isLoggedIn, isAdmin, isSalesman, isReviewer, login, fetchUser, logout }
})
