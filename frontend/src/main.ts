import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import { reportError } from './utils/errorReporter'
import './styles/global.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// ---------------------------------------------------------------------------
// 全局错误上报：Vue 组件内异常、全局 JS 错误、未处理的 Promise 拒绝
// reportError 内部使用原生 fetch 且静默失败，不会反向影响页面渲染
// ---------------------------------------------------------------------------

/** 把任意抛出物转换成可读的 message */
function toErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message || err.name || 'Error'
  if (typeof err === 'string') return err
  if (err === null || err === undefined) return '未知错误'
  try {
    return String(err)
  } catch {
    return '未知错误'
  }
}

/** 提取堆栈信息 */
function toErrorStack(err: unknown): string {
  if (err instanceof Error && typeof err.stack === 'string') return err.stack
  return ''
}

app.config.errorHandler = (err, _instance, info) => {
  const message = toErrorMessage(err)
  const stack = [toErrorStack(err), info ? `Vue errorHandler info: ${info}` : '']
    .filter(Boolean)
    .join('\n\n')
  reportError(message, stack)
}

window.addEventListener('error', (event: ErrorEvent) => {
  // 资源加载失败（img/script/link 等）也会冒泡到 window 的 error 事件，
  // 但 event.error 为 null 且 message 为空，没有排查价值，直接忽略。
  if (!event.message && !event.error) return
  const message = event.message || toErrorMessage(event.error)
  const stack = [toErrorStack(event.error), event.filename ? `at ${event.filename}:${event.lineno}:${event.colno}` : '']
    .filter(Boolean)
    .join('\n\n')
  reportError(message, stack)
})

/** 判断是否为「正常流程」的请求异常（用户取消 / 4xx 业务错误），这类不上报 */
function isExpectedRequestRejection(reason: unknown): boolean {
  if (!reason || typeof reason !== 'object') return false
  const err = reason as { code?: unknown; isAxiosError?: unknown; response?: { status?: unknown } }
  // 用户主动取消的请求（AbortController / axios cancel）
  if (err.code === 'ERR_CANCELED' || err.code === 'ERR_ABORTED') return true
  // axios 异常统一交给 src/api 的响应拦截器处理：
  // 5xx 已在拦截器里上报，4xx/取消不上报。这里再报一次会产生重复记录。
  if (err.isAxiosError === true) return true
  const status = err.response?.status
  // 其他形态的 4xx 业务错误同样不上报
  if (typeof status === 'number' && status >= 400 && status < 500) return true
  return false
}

window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
  const reason = event.reason
  if (isExpectedRequestRejection(reason)) return
  const message = `Unhandled Promise Rejection: ${toErrorMessage(reason)}`
  reportError(message, toErrorStack(reason))
})

app.mount('#app')
