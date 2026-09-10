import { defineStore } from 'pinia'
import { login as apiLogin, logout as apiLogout, getMe } from '../api/auth'

const TOKEN_KEY = 'rag_access_token'
const REFRESH_KEY = 'rag_refresh_token'
const USER_KEY = 'rag_user'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem(TOKEN_KEY) || '',
    refreshToken: localStorage.getItem(REFRESH_KEY) || '',
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
  }),
  getters: {
    isLoggedIn: (s) => !!s.accessToken,
    isAdmin: (s) => s.user?.role === 'admin',
  },
  actions: {
    setTokens(accessToken, refreshToken) {
      this.accessToken = accessToken
      this.refreshToken = refreshToken
      localStorage.setItem(TOKEN_KEY, accessToken)
      localStorage.setItem(REFRESH_KEY, refreshToken)
    },
    setUser(user) {
      this.user = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    },
    async login(username, password) {
      const data = await apiLogin(username, password)
      this.setTokens(data.access_token, data.refresh_token)
      this.setUser(data.user)
    },
    async logout() {
      try {
        await apiLogout(this.refreshToken)
      } catch {
        /* 网络异常时也继续清理本地状态 */
      }
      this.clear()
    },
    clear() {
      this.accessToken = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_KEY)
      localStorage.removeItem(USER_KEY)
    },
    async refreshAccess() {
      // refresh rotation：由 request.js 在 401 时调用
      const { refreshTokenRequest } = await import('../api/auth')
      const data = await refreshTokenRequest(this.refreshToken)
      this.setTokens(data.access_token, data.refresh_token)
      this.setUser(data.user)
    },
  },
})
