import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const request = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

// 请求拦截：携带 access token
request.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  return config
})

// 401 自动刷新重试一次（refresh rotation）
let refreshing = null

request.interceptors.response.use(
  (resp) => resp.data,
  async (error) => {
    const { response, config } = error
    const auth = useAuthStore()

    if (response?.status === 401 && !config._retried && auth.refreshToken && !config.url.includes('/auth/')) {
      config._retried = true
      try {
        refreshing = refreshing || auth.refreshAccess()
        await refreshing
        refreshing = null
        config.headers.Authorization = `Bearer ${auth.accessToken}`
        return request(config)
      } catch {
        refreshing = null
        auth.clear()
        window.location.href = '/login'
        return Promise.reject(error)
      }
    }

    const message = response?.data?.message || error.message || '请求失败'
    if (!config._silent) {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default request
