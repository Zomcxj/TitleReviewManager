import axios from 'axios'
import router from '../router'
import { reportError } from '../utils/errorReporter'

const api = axios.create({
  baseURL: '',
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status

    if (status === 401) {
      // 401 is part of the normal flow (session expired): clear the token and redirect to login; not reported
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_role')
      router.push('/login')
      return Promise.reject(error)
    }

    // Only 5xx server errors are reported; 4xx are business errors (validation failure, no permission, not found), not reported
    // reportError uses native fetch and bypasses this interceptor, so there is no reporting loop
    if (typeof status === 'number' && status >= 500) {
      const url = error.config?.url || ''
      let detail = ''
      const data = error.response?.data
      if (typeof data === 'string') {
        detail = data
      } else if (data && typeof data === 'object') {
        try {
          detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data)
        } catch {
          detail = ''
        }
      }
      const stack = [detail, error.message].filter(Boolean).join('\n\n')
      reportError(`HTTP ${status} ${url}`, stack)
    }

    return Promise.reject(error)
  }
)

export default api
