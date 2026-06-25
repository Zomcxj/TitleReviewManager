import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from './auth'

vi.mock('../api', () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value.toString()
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key]
    }),
    clear: vi.fn(() => {
      store = {}
    }),
  }
})()

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
})

describe('Auth Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorageMock.clear()
    vi.clearAllMocks()
  })

  it('initializes with correct defaults', () => {
    const store = useAuthStore()
    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBeFalsy()
    expect(store.isAdmin).toBeFalsy()
  })

  it('updates state on successful login', async () => {
    const api = (await import('../api')).default
    const mockUser = { id: 1, username: 'testuser', role: 'admin' }
    vi.mocked(api.post).mockResolvedValue({ data: { user: mockUser } })

    const store = useAuthStore()
    await store.login('testuser', 'testpassword')

    expect(store.user).toEqual(mockUser)
    expect(store.isLoggedIn).toBeTruthy()
    expect(store.isAdmin).toBeTruthy()
  })

  it('clears state on logout', async () => {
    const api = (await import('../api')).default
    const mockUser = { id: 1, username: 'testuser', role: 'admin' }
    vi.mocked(api.post).mockResolvedValue({ data: { user: mockUser } })

    const store = useAuthStore()
    await store.login('testuser', 'testpassword')
    
    vi.mocked(api.post).mockResolvedValue({})
    await store.logout()

    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBeFalsy()
  })
})
