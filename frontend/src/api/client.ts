import axios from 'axios'
import { ElMessage } from 'element-plus'

import { router } from '../router'

export const api = axios.create({ baseURL: '/api/v1' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshing: Promise<string | null> | null = null

async function refreshToken(): Promise<string | null> {
  const refresh = localStorage.getItem('refresh_token')
  if (!refresh) return null
  try {
    const { data } = await axios.post('/api/v1/auth/refresh', { refresh_token: refresh })
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    return data.access_token
  } catch {
    return null
  }
}

api.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const { response, config } = error
    if (response?.status === 401 && !config.__retried) {
      refreshing = refreshing ?? refreshToken()
      const token = await refreshing
      refreshing = null
      if (token) {
        config.__retried = true
        return api(config)
      }
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      router.push('/login')
    } else if (response?.status !== 422 && response?.data?.detail) {
      const detail = response.data.detail
      // 结构化错误（detail 为对象，如 {code:'INCOMPLETE_SKU', message}）交由调用方处理，
      // 避免 String(对象) 显示成 [object Object]；普通字符串错误仍全局兜底提示。
      if (typeof detail === 'string') ElMessage.error(detail)
      else if (detail?.message && !detail?.code) ElMessage.error(String(detail.message))
    }
    return Promise.reject(error)
  },
)
