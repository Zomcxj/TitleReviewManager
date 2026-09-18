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
      // 401 是正常业务流程（会话过期），清 token 跳登录，不上报
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_role')
      router.push('/login')
      return Promise.reject(error)
    }

    // 仅上报 5xx 服务端异常；4xx 属于业务错误（校验失败、无权限、不存在），不上报
    // reportError 使用原生 fetch，不经过本拦截器，不存在循环上报
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
