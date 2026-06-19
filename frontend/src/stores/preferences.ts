import { defineStore } from 'pinia'

import { api } from '../api/client'
import { useAuthStore } from './auth'

/** per-user 界面偏好（产品库分面显示/顺序 + 默认币种/排序/每页/视图）。
 *  随 /auth/me 一并下发；本 store 合并出厂默认后供全站读取，改动防抖自动 PUT 保存。 */
export interface ProductFacetPref {
  key: string
  visible: boolean
  expanded?: boolean
}
export interface Preferences {
  product_facets?: ProductFacetPref[]
  default_currency?: string
  default_sort?: string
  page_size?: number
  default_view?: 'card' | 'table'
}

export const PREF_DEFAULTS: Required<Omit<Preferences, 'product_facets'>> & Pick<Preferences, 'product_facets'> = {
  default_currency: 'USD',
  default_sort: 'recent',
  page_size: 20,
  default_view: 'card',
  product_facets: undefined,
}

export const usePreferencesStore = defineStore('preferences', {
  state: () => ({
    prefs: { ...PREF_DEFAULTS } as Preferences,
    _timer: null as ReturnType<typeof setTimeout> | null,
  }),
  getters: {
    view: (s): 'card' | 'table' => s.prefs.default_view ?? 'card',
    pageSize: (s): number => s.prefs.page_size ?? 20,
    currency: (s): string => s.prefs.default_currency ?? 'USD',
    sort: (s): string => s.prefs.default_sort ?? 'recent',
    productFacets: (s): ProductFacetPref[] => s.prefs.product_facets ?? [],
  },
  actions: {
    /** 登录后从 auth.user.preferences 注水（合并出厂默认）。 */
    hydrate() {
      const u = useAuthStore().user as { preferences?: Preferences } | null
      this.prefs = { ...PREF_DEFAULTS, ...(u?.preferences ?? {}) }
    },
    /** 局部更新 + 防抖自动保存。 */
    set(patch: Partial<Preferences>) {
      this.prefs = { ...this.prefs, ...patch }
      if (this._timer) clearTimeout(this._timer)
      this._timer = setTimeout(() => void this.save(), 500)
    },
    async save() {
      try {
        const { data } = await api.put('/auth/me/preferences', this.prefs)
        this.prefs = { ...PREF_DEFAULTS, ...data }
        // 同步回 auth.user.preferences，保持单一真源一致
        const auth = useAuthStore()
        if (auth.user) (auth.user as { preferences?: Preferences }).preferences = data
      } catch { /* 静默：偏好保存失败不阻断主流程 */ }
    },
  },
})
