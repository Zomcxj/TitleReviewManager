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
  // Whether a forced password change is required (true for seed accounts / after an admin resets the password)
  const mustChangePassword = computed(
    () => user.value?.must_change_password === true || localStorage.getItem('must_change_password') === '1'
  )

  /** Sync the user's role and forced-password-change flag into localStorage for the router guard to read */
  function syncLocalUser(u: any) {
    if (u?.role) {
      localStorage.setItem('user_role', u.role)
    }
    if (u && 'must_change_password' in u) {
      localStorage.setItem('must_change_password', u.must_change_password ? '1' : '0')
    }
  }

  /** Locally clear the forced-password-change flag (called after a successful change, no need to request /me again) */
  function clearMustChangePassword() {
    localStorage.setItem('must_change_password', '0')
    if (user.value) {
      user.value = { ...user.value, must_change_password: false }
    }
  }

  async function login(username: string, password: string) {
    const { data } = await api.post('/api/auth/login', { username, password })
    token.value = 'logged-in'
    localStorage.setItem('access_token', 'logged-in')
    user.value = data.user
    // Store the user role and forced-password-change flag in localStorage for the router guard
    syncLocalUser(data.user)
    return data
  }

  async function fetchUser() {
    try {
      const { data } = await api.get('/api/auth/me')
      user.value = data
      syncLocalUser(data)
    } catch {
      user.value = null
      token.value = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_role')
      localStorage.removeItem('must_change_password')
    }
  }

  async function logout() {
    try {
      await api.post('/api/auth/logout')
    } catch {
      // Clear local state even if the API call fails
    }
    user.value = null
    token.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('user_role')
    localStorage.removeItem('must_change_password')
  }

  return {
    user,
    token,
    isLoggedIn,
    isAdmin,
    isSalesman,
    isReviewer,
    mustChangePassword,
    login,
    fetchUser,
    logout,
    clearMustChangePassword,
  }
})
