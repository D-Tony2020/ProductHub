import { defineStore } from 'pinia'

import { api } from '../api/client'

/** 报价单"购物车"：当前激活草稿单（业务员同时服务多客户，可多单并存切换）。 */
export const useQuoteCartStore = defineStore('quoteCart', {
  state: () => ({
    activeQuoteId: Number(localStorage.getItem('active_quote_id')) || null as number | null,
    itemCount: 0,
  }),
  actions: {
    setActive(id: number | null) {
      this.activeQuoteId = id
      if (id) localStorage.setItem('active_quote_id', String(id))
      else localStorage.removeItem('active_quote_id')
      void this.refreshCount()
    },
    async refreshCount() {
      if (!this.activeQuoteId) {
        this.itemCount = 0
        return
      }
      try {
        const { data } = await api.get(`/quotes/${this.activeQuoteId}`)
        if (data.status !== 'draft') {
          this.setActive(null)
          return
        }
        this.itemCount = data.items.length
      } catch {
        this.setActive(null)
      }
    },
    /** 加入当前激活单；无激活单时引导创建。
     *  成功：warnings=该 SKU 加入时的 supply 软提醒（含停用/停产件，仅当次回填）。
     *  失败：code='INCOMPLETE_SKU' 表示后端完整性硬闸拦截（detail 为结构化对象）。 */
    async addSku(skuId: number, qty: number):
      Promise<{ ok: boolean; message?: string; code?: string; warnings?: string[] }> {
      if (!this.activeQuoteId) return { ok: false, message: 'NO_ACTIVE' }
      try {
        const { data } = await api.post(`/quotes/${this.activeQuoteId}/items`, { sku_id: skuId, qty })
        await this.refreshCount()
        const line = data.items?.find((it: any) => it.sku_id === skuId)
        return { ok: true, warnings: line?.supply_warnings ?? [] }
      } catch (e: any) {
        const detail = e?.response?.data?.detail
        if (detail && typeof detail === 'object' && detail.code === 'INCOMPLETE_SKU') {
          return { ok: false, code: 'INCOMPLETE_SKU', message: detail.message }
        }
        return { ok: false, message: typeof detail === 'string' ? detail : '加入失败' }
      }
    },
  },
})
