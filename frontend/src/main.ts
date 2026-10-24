import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import App from './App.vue'
import router from './router'
import { reportError } from './utils/errorReporter'
import './styles/global.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// Icons are imported on demand: each component does its own `import { Xxx } from '@element-plus/icons-vue'`.
// Previously all 294 icons were registered globally here, so unused icons could not be removed by
// tree-shaking and the main bundle grew for nothing. Global registration also hid real dependencies:
// any icon worked without being imported, and no error appeared until it surfaced at runtime.

// ---------------------------------------------------------------------------
// Global error reporting: exceptions inside Vue components, global JS errors, and unhandled
// Promise rejections. reportError uses native fetch and fails silently, never affecting rendering
// ---------------------------------------------------------------------------

/** Convert any thrown value into a readable message */
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

/** Extract the stack trace */
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
  // Resource load failures (img/script/link, etc.) also bubble up to the window error event,
  // but event.error is null and message is empty, so they are useless for debugging; ignore them.
  if (!event.message && !event.error) return
  const message = event.message || toErrorMessage(event.error)
  const stack = [toErrorStack(event.error), event.filename ? `at ${event.filename}:${event.lineno}:${event.colno}` : '']
    .filter(Boolean)
    .join('\n\n')
  reportError(message, stack)
})

/** Decide whether a rejection is an "expected flow" request failure (user cancel / 4xx business error); these are not reported */
function isExpectedRequestRejection(reason: unknown): boolean {
  if (!reason || typeof reason !== 'object') return false
  const err = reason as { code?: unknown; isAxiosError?: unknown; response?: { status?: unknown } }
  // Requests actively canceled by the user (AbortController / axios cancel)
  if (err.code === 'ERR_CANCELED' || err.code === 'ERR_ABORTED') return true
  // Axios errors are handled uniformly by the response interceptor in src/api:
  // 5xx are already reported there, 4xx/cancel are not. Reporting again here would create duplicates.
  if (err.isAxiosError === true) return true
  const status = err.response?.status
  // Other forms of 4xx business errors are likewise not reported
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
