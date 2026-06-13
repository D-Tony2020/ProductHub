/**
 * 配置看板状态引擎：本地配置树 ←→ 后端 ConfigPayload。
 * 本地只负责交互与进度显示；指纹、完整性、命中以服务端 /config/validate 为准。
 */
import { reactive, ref } from 'vue'

import { api } from '../api/client'

export interface OptionMeta {
  id: number
  code: string
  label: string
  is_active: boolean
}
export interface AttrMeta {
  id: number
  code: string
  name: string
  is_required: boolean
  is_active: boolean
  options: OptionMeta[]
}
export interface SlotMeta {
  id: number
  code: string
  name: string
  child_type_id: number
  is_required: boolean
  allow_blackbox: boolean
  variant_group: string | null
  is_active: boolean
}
export interface TypeMeta {
  id: number
  code: string
  name: string
  attributes: AttrMeta[]
  slots: SlotMeta[]
}

export interface SlotState {
  mode: 'empty' | 'configured' | 'purchased'
  child: NodeState | null
  partId: number | null
  partLabel: string
}
export interface NodeState {
  typeId: number
  attrs: Record<number, number | null>
  slots: Record<number, SlotState>
}

const typeCache = new Map<number, TypeMeta>()

/** 同步读取已加载的类型元数据（树渲染等热路径用） */
export function getTypeMeta(typeId: number): TypeMeta | null {
  return typeCache.get(typeId) ?? null
}

/** 清空类型元数据缓存：进入配置看板时调用，确保拿到管理员最新改过的模板
 *  （必选/部件槽变更立即生效）。单次配置会话内仍缓存，避免重复拉同类型。 */
export function clearTypeCache(): void {
  typeCache.clear()
}

export async function loadType(typeId: number): Promise<TypeMeta> {
  if (typeCache.has(typeId)) return typeCache.get(typeId)!
  const { data } = await api.get(`/template/node-types/${typeId}`)
  const meta: TypeMeta = {
    id: data.id, code: data.code, name: data.name,
    attributes: data.attributes.filter((a: any) => a.is_active),
    slots: data.slots.filter((s: any) => s.is_active),
  }
  typeCache.set(typeId, meta)
  return meta
}

export async function newNodeState(typeId: number): Promise<NodeState> {
  const meta = await loadType(typeId)
  const node: NodeState = { typeId, attrs: {}, slots: {} }
  for (const a of meta.attributes) node.attrs[a.id] = null
  for (const s of meta.slots) {
    node.slots[s.id] = { mode: 'empty', child: null, partId: null, partLabel: '' }
  }
  return reactive(node)
}

/** 本地完整度（驱动进度条/树图标；权威判定仍在服务端）。
 * 规则：必选属性各计 1；黑盒槽（已选件）计 1/1；白盒槽并入子树计数；
 * 未配置的必配槽计 0/1；未配置的可选槽不计；
 * 互斥组（变体）：组内无选择计 0/1，已选成员按普通槽规则计数。 */
export function localProgress(node: NodeState): { done: number; total: number } {
  const meta = typeCache.get(node.typeId)
  if (!meta) return { done: 0, total: 1 }
  let done = 0
  let total = 0
  for (const a of meta.attributes) {
    if (!a.is_required) continue
    total += 1
    if (node.attrs[a.id] != null) done += 1
  }

  const countSlot = (s: SlotMeta): boolean => {
    const st = node.slots[s.id]
    if (st && st.mode === 'purchased' && st.partId) {
      total += 1
      done += 1
      return true
    }
    if (st && st.mode === 'configured' && st.child) {
      const sub = localProgress(st.child)
      done += sub.done
      total += sub.total
      return true
    }
    return false
  }

  const emptyGroups = new Set<string>()
  const touchedGroups = new Set<string>()
  for (const s of meta.slots) {
    if (s.variant_group) {
      if (countSlot(s)) touchedGroups.add(s.variant_group)
      else emptyGroups.add(s.variant_group)
      continue
    }
    if (!countSlot(s) && s.is_required) total += 1
  }
  for (const g of emptyGroups) {
    if (!touchedGroups.has(g)) total += 1 // 整组未选：计一个缺口
  }
  return { done, total }
}

/** 本地状态 → 后端 payload */
export function toPayload(rootTypeId: number, root: NodeState): any {
  function nodeOut(n: NodeState): any {
    return {
      attributes: Object.entries(n.attrs)
        .filter(([, v]) => v != null)
        .map(([attrId, optId]) => ({ attribute_id: Number(attrId), option_id: optId })),
      slots: Object.entries(n.slots).map(([slotId, st]) => ({
        slot_id: Number(slotId),
        mode: st.mode,
        child: st.mode === 'configured' && st.child ? nodeOut(st.child) : null,
        purchased_part_id: st.mode === 'purchased' ? st.partId : null,
      })),
    }
  }
  return { root_type_id: rootTypeId, root: nodeOut(root) }
}

/** SKU 详情 config_tree → 本地状态（"以此为模板再配置"） */
export async function fromSkuTree(tree: any): Promise<NodeState> {
  const node = await newNodeState(tree.node_type_id)
  for (const av of tree.attributes ?? []) node.attrs[av.attribute_id] = av.option_id
  for (const child of tree.children ?? []) {
    if (child.slot_id == null) continue
    if (child.mode === 'purchased') {
      node.slots[child.slot_id] = {
        mode: 'purchased', child: null, partId: child.purchased_part_id,
        partLabel: `${child.supplier_name ?? ''} | ${child.purchased_part_name ?? ''}`,
      }
    } else {
      node.slots[child.slot_id] = {
        mode: 'configured', child: await fromSkuTree(child), partId: null, partLabel: '',
      }
    }
  }
  return node
}

export function useValidator() {
  const validating = ref(false)
  const result = ref<any | null>(null)
  let timer: ReturnType<typeof setTimeout> | null = null

  function trigger(payloadFn: () => any) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(async () => {
      validating.value = true
      try {
        const { data } = await api.post('/config/validate', payloadFn())
        result.value = data
      } catch {
        result.value = null
      } finally {
        validating.value = false
      }
    }, 350)
  }
  return { validating, result, trigger }
}
