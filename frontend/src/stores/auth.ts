import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<any>(null)
  const token = ref<string | null>(localStorage.getItem('access_token'))

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isSalesman = computed(() => user.value?.role === 'salesman')
  const isReviewer = computed(() => user.value?.role === 'reviewer')

  async function login(username: string, password: string) {
    const { data } = await axios.post('/api/auth/login', { username, password }, {
      withCredentials: true,
    })
    token.value = 'logged-in'
    localStorage.setItem('access_token', 'logged-in')
    user.value = data.user
    return data
  }

  async function fetchUser() {
    try {
      const { data } = await axios.get('/api/auth/me', { withCredentials: true })
      user.value = data
    } catch {
      user.value = null
      token.value = null
      localStorage.removeItem('access_token')
    }
  }

  async function logout() {
    await axios.post('/api/auth/logout', {}, { withCredentials: true })
    user.value = null
    token.value = null
    localStorage.removeItem('access_token')
  }

  return { user, token, isLoggedIn, isAdmin, isSalesman, isReviewer, login, fetchUser, logout }
})
