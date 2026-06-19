/** 产品库筛选分面注册表 —— 检索面板（SkuFilterPanel）与通用设置（分面自定义）共用同一真源。
 *  用户可在「系统设置 · 通用设置」里调整分面的显示与顺序，偏好存于 per-user preferences。 */
import type { ProductFacetPref } from '../stores/preferences'

export interface FacetDef {
  key: string
  label: string
  hint?: string
}

/** 全部可配置分面，数组顺序即出厂默认顺序。新增分面追加于此即可对所有用户生效。
 *  （「快捷视图」「品类树」是固定常驻区，不在可自定义分面内。） */
// 注：「供应商」已升级为左栏与「品类」平级的一级分类视角（视角切换），不再作为可自定义分面。
export const FACET_REGISTRY: FacetDef[] = [
  { key: 'sourcing', label: '采购来源', hint: '含外购件 / 纯自配 / 整机直采' },
  { key: 'price', label: '价格区间', hint: '按所选币种现价' },
  { key: 'quotable', label: '可报价状态' },
  { key: 'attrs', label: '规格属性', hint: '随所选品类动态展开' },
]

export interface ResolvedFacet extends FacetDef {
  visible: boolean
  expanded: boolean
}

/** 合并出厂默认与用户偏好：先按偏好顺序取已知分面，再把偏好里没有的新分面追加在后
 *  （保证新上线分面对老用户自动可见）；偏好里的未知键忽略。 */
export function resolveFacets(prefList?: ProductFacetPref[]): ResolvedFacet[] {
  const def = new Map(FACET_REGISTRY.map((f) => [f.key, f]))
  const seen = new Set<string>()
  const out: ResolvedFacet[] = []
  for (const p of prefList ?? []) {
    const d = def.get(p.key)
    if (d && !seen.has(p.key)) {
      seen.add(p.key)
      out.push({ ...d, visible: p.visible !== false, expanded: p.expanded !== false })
    }
  }
  for (const d of FACET_REGISTRY) {
    if (!seen.has(d.key)) out.push({ ...d, visible: true, expanded: true })
  }
  return out
}

export const SOURCING_OPTIONS = [
  { value: 'blackbox', label: '含外购件', hint: '配置含外购成品子件（最常见）' },
  { value: 'whitebox', label: '纯自配', hint: '完全自行配置、无任何外购件' },
  { value: 'direct', label: '整机直采', hint: '按成品整机直接采购转售' },
]

export const SORT_OPTIONS = [
  { value: 'recent', label: '综合（最新）' },
  { value: 'price_asc', label: '价格 从低到高' },
  { value: 'price_desc', label: '价格 从高到低' },
  { value: 'created_asc', label: '最早创建' },
  { value: 'code', label: 'SKU 编码' },
  { value: 'name', label: '名称' },
]

export const CURRENCY_OPTIONS = ['USD', 'CNY']
