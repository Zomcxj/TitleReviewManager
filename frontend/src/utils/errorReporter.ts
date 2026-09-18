/**
 * 前端错误上报工具。
 *
 * 设计要点（务必保持，否则会引入新的线上问题）：
 * 1. 使用原生 fetch，绝不使用 src/api 里的共享 axios 实例。
 *    共享实例挂了响应拦截器，上报失败会再次触发拦截器 -> 再次上报 -> 死循环。
 * 2. 整段包 try/catch 且 catch 内不做任何事（不 console.error）。
 *    fetch 的 Promise 也必须 .catch 掉，否则会触发 unhandledrejection，
 *    而 unhandledrejection 又会调用本函数 -> 无限自激。
 * 3. 同一个 message 在 60 秒内只上报一次，避免组件循环渲染 / 定时器报错时刷爆后端。
 */

/** 去重窗口：同一 message 在该时间窗内只上报一次 */
const DEDUPE_WINDOW_MS = 60_000
/** 去重 Map 的最大条目数，超过后清理过期项，避免长时间运行内存膨胀 */
const DEDUPE_MAX_ENTRIES = 200
/** 去重 key 的最大长度（避免超长 message 作为 key） */
const DEDUPE_KEY_MAX_LEN = 200

/** message -> 最近一次上报时间戳 */
const reportedAt = new Map<string, number>()

/** 返回 true 表示应当跳过本次上报（窗口内已上报过） */
function isDuplicate(message: string): boolean {
  const now = Date.now()
  const key = message.slice(0, DEDUPE_KEY_MAX_LEN)
  const last = reportedAt.get(key)
  if (last !== undefined && now - last < DEDUPE_WINDOW_MS) {
    return true
  }
  if (reportedAt.size >= DEDUPE_MAX_ENTRIES) {
    for (const [k, t] of reportedAt) {
      if (now - t >= DEDUPE_WINDOW_MS) {
        reportedAt.delete(k)
      }
    }
    // 清理后仍然过满：整体重置，保证不会无限增长
    if (reportedAt.size >= DEDUPE_MAX_ENTRIES) {
      reportedAt.clear()
    }
  }
  reportedAt.set(key, now)
  return false
}

function currentUrl(): string {
  try {
    return location.pathname + location.search
  } catch {
    return ''
  }
}

/**
 * 上报一条前端错误。匿名可用（登录页出错时也会走到这里）。
 * 永远不会抛出异常，永远不会返回失败的 Promise。
 */
export function reportError(message: string, stack?: string): void {
  try {
    const text = (message ?? '').toString().trim()
    if (!text) return

    if (isDuplicate(text)) return

    const payload: { message: string; url: string; stack?: string } = {
      message: text.slice(0, 2000),
      url: currentUrl().slice(0, 500),
    }
    if (stack) {
      payload.stack = stack.slice(0, 5000)
    }

    // 原生 fetch：不经过 axios 拦截器，避免与上报逻辑互相触发
    void fetch('/api/client-errors/report', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {
      // 静默失败：上报失败不能影响页面，也不能触发 unhandledrejection
    })
  } catch {
    // 静默失败：任何异常都不向外抛
  }
}
