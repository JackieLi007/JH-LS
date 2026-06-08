import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type AuthRole = 'editor' | 'viewer'

export type AuthUser = {
  username: string
  displayName: string
  role: AuthRole
  homePath: string
}

type AuthResponse = {
  success?: boolean
  message?: string
  result?: AuthUser | null
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const initialized = ref(false)
  const isAuthenticated = computed(() => Boolean(user.value))

  async function restoreSession() {
    if (initialized.value) return user.value
    try {
      const response = await fetch('/api/auth/me', {
        cache: 'no-store',
        credentials: 'include',
      })
      const payload = await response.json() as AuthResponse
      user.value = response.ok && payload.success !== false ? payload.result ?? null : null
    } catch {
      user.value = null
    } finally {
      initialized.value = true
    }
    return user.value
  }

  async function login(username: string, password: string) {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      cache: 'no-store',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    const payload = await response.json() as AuthResponse
    if (!response.ok || payload.success === false || !payload.result) {
      throw new Error(payload.message || '登录失败，请检查用户名和密码。')
    }
    user.value = payload.result
    initialized.value = true
    return payload.result
  }

  async function logout() {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        cache: 'no-store',
        credentials: 'include',
      })
    } finally {
      user.value = null
      initialized.value = true
    }
  }

  return {
    user,
    initialized,
    isAuthenticated,
    restoreSession,
    login,
    logout,
  }
})
