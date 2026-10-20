import { defineStore } from 'pinia'
import client, { TOKEN_KEY } from '../api/client'

const USER_KEY = 'interviewai_user'

interface User {
  id: string
  username: string
  email: string
  full_name?: string
  target_position?: string
  industry?: string
  experience_level?: string
  role?: string
  is_active?: boolean
  created_at?: string
}

function loadToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

function loadUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

function saveAuth(token: string, user: User) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    /* 忽略：无痕/禁用 localStorage 时登录态仅存内存 */
  }
}

function clearAuth() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  } catch {
    /* 忽略 */
  }
}

export const useUserStore = defineStore('user', {
  state: () => ({
    token: loadToken(),
    user: loadUser(),
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    isAdmin: (state) => state.user?.role === 'admin',
    displayName: (state) => state.user?.full_name || state.user?.username || state.user?.email || '',
  },
  actions: {
    setAuth(token: string, user: User) {
      this.token = token
      this.user = user
      saveAuth(token, user)
    },
    async login(email: string, password: string) {
      const res = await client.post('/auth/login', { email, password })
      this.setAuth(res.data.token, res.data.user)
    },
    async register(payload: { username: string; email: string; password: string }) {
      const res = await client.post('/auth/register', payload)
      this.setAuth(res.data.token, res.data.user)
    },
    logout() {
      this.token = ''
      this.user = null
      clearAuth()
    },
    async checkAuth() {
      // 启动时向后端确认本地 token 是否仍有效；只有明确 401 才登出
      if (!this.token) return
      try {
        const res = await client.get('/auth/me')
        this.user = res.data
        saveAuth(this.token, res.data)
      } catch (e: any) {
        if (e?.response?.status === 401) {
          this.logout()
        }
        // 网络异常/服务未就绪等其他错误不处理，保持现状
      }
    },
  },
})
