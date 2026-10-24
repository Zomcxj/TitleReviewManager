/**
 * Frontend error reporting utility.
 *
 * Design notes (must be kept, otherwise new production issues will creep in):
 * 1. Use native fetch, never the shared axios instance from src/api. That instance has a
 *    response interceptor attached: a failed report re-triggers it -> re-report -> dead loop.
 * 2. Wrap the whole body in try/catch and do nothing inside catch (no console.error).
 *    The fetch Promise must be .catch-ed as well, otherwise it fires unhandledrejection,
 *    and unhandledrejection calls this function again -> endless self-triggering.
 * 3. The same message is reported at most once per 60 seconds, preventing backend floods
 *    from looping component renders / timer errors.
 */

/** Dedupe window: the same message is reported only once within this time window */
const DEDUPE_WINDOW_MS = 60_000
/** Max entries in the dedupe Map; beyond it, expired entries are cleaned up to avoid unbounded memory growth over long runs */
const DEDUPE_MAX_ENTRIES = 200
/** Max length of a dedupe key (prevents overly long messages from being used as keys) */
const DEDUPE_KEY_MAX_LEN = 200

/** message -> timestamp of the most recent report */
const reportedAt = new Map<string, number>()

/** Returns true when this report should be skipped (already reported within the window) */
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
    // Still too full after cleanup: reset entirely, guaranteeing it never grows without bound
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
 * Report one frontend error. Works anonymously (errors on the login page reach here too).
 * Never throws and never returns a rejected Promise.
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

    // Native fetch: bypasses the axios interceptors so the reporting logic cannot re-trigger itself
    void fetch('/api/client-errors/report', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {
      // Fail silently: a failed report must not affect the page, nor trigger unhandledrejection
    })
  } catch {
    // Fail silently: never propagate any exception outward
  }
}
