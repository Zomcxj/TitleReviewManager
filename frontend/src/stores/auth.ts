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
  // 是否被要求强制修改密码（种子账号 / 管理员重置密码后为 true）
  const mustChangePassword = computed(
    () => user.value?.must_change_password === true || localStorage.getItem('must_change_password') === '1'
  )

  /** 把用户信息里的角色与强制改密标记同步到 localStorage，供路由守卫读取 */
  function syncLocalUser(u: any) {
    if (u?.role) {
      localStorage.setItem('user_role', u.role)
    }
    if (u && 'must_change_password' in u) {
      localStorage.setItem('must_change_password', u.must_change_password ? '1' : '0')
    }
  }

  /** 本地解除强制改密标记（改密成功后调用，无需再请求 /me） */
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
    // 存储用户角色与强制改密标记到 localStorage，供路由守卫使用
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
      // 即使 API 失败也要清除本地状态
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
