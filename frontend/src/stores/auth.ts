import { defineStore } from 'pinia'

import { api } from '../api/client'

export interface UserInfo {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'sales'
  can_set_price: boolean
  preferences?: Record<string, any>
}

export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null as UserInfo | null }),
  getters: {
    isAdmin: (s) => s.user?.role === 'admin',
    canSetPrice: (s) => s.user?.role === 'admin' || !!s.user?.can_set_price,
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await api.post('/auth/login', { username, password })
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      await this.fetchMe()
    },
    async fetchMe() {
      const { data } = await api.get('/auth/me')
      this.user = data
      // 用户偏好随 /auth/me 下发 → 注水偏好 store（懒引用避免循环依赖）
      const { usePreferencesStore } = await import('./preferences')
      usePreferencesStore().hydrate()
    },
    logout() {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      this.user = null
    },
  },
})
