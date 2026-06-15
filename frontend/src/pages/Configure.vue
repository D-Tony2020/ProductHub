<script setup lang="ts">
/** 配置看板：三栏（产品构成树 / 当前节点编辑区 / 实时摘要与命中）。
 *  核心机制："完整即查重"——每次变更防抖调用 /config/validate，
 *  命中既有 SKU 则隐藏"保存为新 SKU"，只给查看/加入报价单。 */
import { CircleCheck, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import PartPicker from '../components/PartPicker.vue'
import {
  clearTypeCache, fromPayload, fromSkuTree, getTypeMeta, loadType, localProgress, newNodeState,
  toPayload, useValidator,
  type NodeState, type SlotMeta, type TypeMeta,
} from '../composables/useConfigurator'
import { useAuthStore } from '../stores/auth'
import { useQuoteCartStore } from '../stores/quoteCart'

const auth = useAuthStore()
const cart = useQuoteCartStore()
const route = useRoute()
const router = useRouter()

// ---------- 起点选择 ----------
const rootTypes = ref<any[]>([])
const drafts = ref<any[]>([])
const suppliers = ref<any[]>([])  // 采购来源下拉（方案甲）
const rootType = ref<TypeMeta | null>(null)
const rootState = ref<NodeState | null>(null)
const draftId = ref<number | null>(null)

// 整机直采（黑盒整机）：整台外购成品直接作为可售 SKU 的根，不走逐项配置
const direct = reactive({ active: false, type: null as any, partId: null as number | null, partLabel: '' })
const directPicker = reactive({ visible: false })

// 当前编辑节点 = 沿槽 id 的路径
const currentPath = ref<number[]>([])
const { validating, result, trigger } = useValidator()

// 修改既有 SKU 模式(M2-B)：保存走 update（生成新 SKU + 原 SKU 留痕停用/保活），非新建
const editingSkuId = ref<number | null>(null)
const editingSkuCode = ref('')

// 灰盒·部件规格模式：编辑某成品采购件的可选规格(全选填、仅描述、不进指纹)
const partSpecId = ref<number | null>(null)
const partSpecName = ref('')
const specNote = ref('')

onMounted(async () => {
  try {
    clearTypeCache()  // 进入配置看板先清缓存，确保模板最新（必选/部件槽变更立即生效）
    const { data } = await api.get('/template/node-types')
    // 凡可售根均可作配置起点：整机品类 + 单卖配件（如客户单卖筒体/阀门）
    rootTypes.value = data.filter((t: any) => t.is_sellable_root)
    drafts.value = (await api.get('/config-drafts')).data
    suppliers.value = (await api.get('/suppliers')).data
    if (route.query.part_spec_id) await startForPartSpec(Number(route.query.part_spec_id))
    else if (route.query.edit_sku_id) await startFromSku(Number(route.query.edit_sku_id), true)
    else if (route.query.sku_id) await startFromSku(Number(route.query.sku_id))
  } catch { /* 401 由拦截器跳转登录 */ }
})

async function startForPartSpec(partId: number) {
  const { data } = await api.get(`/purchased-parts/by-id/${partId}`)
  rootType.value = await loadType(data.node_type_id)
  rootState.value = data.spec_config
    ? reactive(await fromPayload(data.spec_config))
    : await newNodeState(data.node_type_id)
  specNote.value = data.spec_note ?? ''
  currentPath.value = []
  draftId.value = null
  editingSkuId.value = null
  partSpecId.value = partId
  partSpecName.value = data.name
  ElMessage.info(`正在编辑「${data.name}」的规格：全部选填、仅描述用途，不进 SKU 指纹`)
}

async function startNew(t: any) {
  rootType.value = await loadType(t.id)
  rootState.value = await newNodeState(t.id)
  currentPath.value = []
  draftId.value = null
  editingSkuId.value = null
  partSpecId.value = null
}

// ---------- 整机直采（黑盒整机）----------
function startDirect(t: any) {
  direct.active = true
  direct.type = t
  direct.partId = null
  direct.partLabel = ''
  directPicker.visible = true
}
function onDirectPicked(part: { id: number; label: string }) {
  direct.partId = part.id
  direct.partLabel = part.label
}
function cancelDirect() {
  direct.active = false
  direct.type = null
  direct.partId = null
  direct.partLabel = ''
}
async function createDirect() {
  if (!direct.type || !direct.partId) return
  saving.value = true
  try {
    const { data } = await api.post('/skus', {
      config: { root_type_id: direct.type.id, root_purchased_part_id: direct.partId },
    })
    if (data.created) {
      ElMessage.success(`已创建整机直采 ${data.sku.sku_code}`)
      if (auth.canSetPrice) await promptPrice(data.sku)
      else ElMessage.info('SKU 已进入「待录价」，录价后方可加入报价单')
    } else {
      ElMessage.warning(`该整机已存在 SKU：${data.sku.sku_code}`)
    }
    router.push({ path: '/skus', query: { sku_id: data.sku.id } })
  } catch { /* 拦截器提示 */ } finally {
    saving.value = false
  }
}

async function startFromSku(skuId: number, editing = false) {
  const { data } = await api.get(`/skus/${skuId}`)
  if (data.config_tree?.mode === 'purchased') {
    // 整机直采 SKU：进直采模式、预选其整机件（换件即生成新 SKU；不走逐项配置）
    direct.active = true
    direct.type = await loadType(data.root_type_id)
    direct.partId = data.config_tree.purchased_part_id
    direct.partLabel = `${data.config_tree.supplier_name} | ${data.config_tree.purchased_part_name}`
    ElMessage.info(editing
      ? `整机直采 ${data.sku_code}：换一个整机采购件即生成新 SKU`
      : `已按整机直采 ${data.sku_code} 预填，换件即成新 SKU`)
    return
  }
  rootType.value = await loadType(data.root_type_id)
  await preloadTypes(data.config_tree)
  rootState.value = reactive(await fromSkuTree(data.config_tree))
  currentPath.value = []
  draftId.value = null
  if (editing) {
    editingSkuId.value = skuId
    editingSkuCode.value = data.sku_code
    ElMessage.info(`正在修改 ${data.sku_code}：改动后保存将生成一个新 SKU，原 SKU 可停用或保活`)
  } else {
    editingSkuId.value = null
    ElMessage.success(`已按 ${data.sku_code} 预填配置，修改任一项即成新配置`)
  }
}

async function preloadTypes(tree: any) {
  await loadType(tree.node_type_id)
  for (const c of tree.children ?? []) await preloadTypes(c)
}

async function startFromDraft(d: any) {
  rootType.value = await loadType(d.root_type_id)
  await restoreDraftTypes(d.payload)
  rootState.value = reactive(d.payload as NodeState)
  draftId.value = d.id
  currentPath.value = []
  editingSkuId.value = null
}

async function restoreDraftTypes(node: any) {
  await loadType(node.typeId)
  for (const st of Object.values(node.slots ?? {}) as any[]) {
    if (st.child) await restoreDraftTypes(st.child)
  }
}

// ---------- 当前节点与元数据 ----------
const currentNode = computed<NodeState | null>(() => {
  let node = rootState.value
  for (const slotId of currentPath.value) {
    if (!node) return null
    node = node.slots[slotId]?.child ?? null
  }
  return node
})
const currentMeta = ref<TypeMeta | null>(null)
watch([currentNode, rootState], async () => {
  if (currentNode.value) currentMeta.value = await loadType(currentNode.value.typeId)
}, { immediate: true, deep: false })

const breadcrumb = computed(() => {
  const crumbs: { label: string; path: number[] }[] = [
    { label: rootType.value?.name ?? '', path: [] },
  ]
  let node = rootState.value
  const acc: number[] = []
  for (const slotId of currentPath.value) {
    if (!node) break
    const meta = nodeMeta(node)
    const slot = meta?.slots.find((s) => s.id === slotId)
    acc.push(slotId)
    crumbs.push({ label: slot?.name ?? '?', path: [...acc] })
    node = node.slots[slotId]?.child ?? null
  }
  return crumbs
})

function nodeMeta(node: NodeState): TypeMeta | null {
  return getTypeMeta(node.typeId)
}

// ---------- 变更 → 试算 ----------
const progress = computed(() => {
  if (!rootState.value) return { done: 0, total: 1 }
  return localProgress(rootState.value)
})
const progressPct = computed(() =>
  progress.value.total === 0 ? 100 : Math.round((progress.value.done / progress.value.total) * 100))

watch(rootState, () => {
  // 部件规格模式不查重/不试算指纹（规格仅描述、不进指纹）
  if (rootState.value && rootType.value && !partSpecId.value) {
    trigger(() => toPayload(rootType.value!.id, rootState.value!))
  }
}, { deep: true })

// ---------- 互斥槽组（变体三选一） ----------
const ungroupedSlots = computed(() => currentMeta.value?.slots.filter((s) => !s.variant_group) ?? [])
const slotGroups = computed(() => {
  const map = new Map<string, SlotMeta[]>()
  for (const s of currentMeta.value?.slots ?? []) {
    if (!s.variant_group) continue
    if (!map.has(s.variant_group)) map.set(s.variant_group, [])
    map.get(s.variant_group)!.push(s)
  }
  return [...map.entries()].map(([name, slots]) => ({ name, slots }))
})

// 每组当前选中的变体槽（含尚未选择配置方式的"工作中"状态）
const groupChoice = ref<Record<string, number | null>>({})
watch([currentNode, currentMeta], () => {
  const gc: Record<string, number | null> = {}
  for (const g of slotGroups.value) {
    const active = g.slots.find((s) => {
      const st = currentNode.value?.slots[s.id]
      return st && st.mode !== 'empty'
    })
    gc[g.name] = active?.id ?? groupChoice.value[g.name] ?? null
  }
  groupChoice.value = gc
}, { immediate: true })

async function chooseVariant(group: { name: string; slots: SlotMeta[] }, slotId: number) {
  const node = currentNode.value
  if (!node) return
  const prev = group.slots.find((s) => s.id !== slotId && node.slots[s.id]?.mode !== 'empty')
  if (prev) {
    try {
      await ElMessageBox.confirm(
        `切换会清空「${prev.name}」已配置的内容，确认？`, '提示', { type: 'warning' },
      )
    } catch {
      return
    }
    const st = node.slots[prev.id]
    st.mode = 'empty'
    st.child = null
    st.partId = null
    st.partLabel = ''
  }
  groupChoice.value[group.name] = slotId
}

function chosenSlotOf(group: { name: string; slots: SlotMeta[] }): SlotMeta | null {
  const id = groupChoice.value[group.name]
  return group.slots.find((s) => s.id === id) ?? null
}

// ---------- 槽操作 ----------
const picker = reactive({ visible: false, slotId: 0, nodeTypeId: 0, slotName: '' })

function slotState(slotId: number) {
  return currentNode.value?.slots[slotId]
}

async function setSlotMode(slot: SlotMeta, mode: 'configured' | 'purchased' | 'empty') {
  const node = currentNode.value
  if (!node) return
  const st = node.slots[slot.id]
  if (st.mode === mode) return
  if ((st.mode === 'configured' && st.child) || (st.mode === 'purchased' && st.partId)) {
    try {
      await ElMessageBox.confirm('切换方式会清空该部件当前的配置内容，确认？', '提示', { type: 'warning' })
    } catch {
      return
    }
  }
  st.child = null
  st.partId = null
  st.partLabel = ''
  st.mode = mode
  if (mode === 'configured') {
    st.child = await newNodeState(slot.child_type_id)
    currentPath.value = [...currentPath.value, slot.id]
  } else if (mode === 'purchased') {
    openPartPicker(slot)
  }
}

/** 打开成品件选择器（新选或"更换"）。不走 setSlotMode 的 mode 早退，
 *  故已是 purchased 态时点"更换"也能弹出；取消则保留原件。 */
function openPartPicker(slot: SlotMeta) {
  picker.visible = true
  picker.slotId = slot.id
  picker.nodeTypeId = slot.child_type_id
  picker.slotName = slot.name
}

function onPartSelected(part: { id: number; label: string }) {
  const st = slotState(picker.slotId)
  if (st) {
    st.mode = 'purchased'
    st.partId = part.id
    st.partLabel = part.label
  }
}

function enterSlot(slot: SlotMeta) {
  currentPath.value = [...currentPath.value, slot.id]
}

function slotChildProgress(slot: SlotMeta) {
  const st = slotState(slot.id)
  if (st?.mode === 'configured' && st.child) return localProgress(st.child)
  return null
}

// ---------- 左树 ----------
interface TreeItem {
  label: string
  path: number[]
  status: 'done' | 'progress' | 'todo' | 'blackbox'
  blackboxLabel?: string
  children: TreeItem[]
}
const treeData = computed<TreeItem[]>(() => {
  if (!rootState.value || !rootType.value) return []
  function build(node: NodeState, label: string, path: number[]): TreeItem {
    const meta = nodeMeta(node)
    const p = localProgress(node)
    const children: TreeItem[] = []
    const pendingGroups = new Set<string>()
    const resolvedGroups = new Set<string>()
    for (const slot of meta?.slots ?? []) {
      const st = node.slots[slot.id]
      const active = (st?.mode === 'purchased' && st.partId) || (st?.mode === 'configured' && st.child)
      if (slot.variant_group && !active) {
        pendingGroups.add(slot.variant_group)
        continue // 未选中的变体不进树，整组以"待选"占位
      }
      if (slot.variant_group) resolvedGroups.add(slot.variant_group)
      if (st?.mode === 'purchased' && st.partId) {
        children.push({
          label: slot.name, path: [...path, slot.id], status: 'blackbox',
          blackboxLabel: st.partLabel, children: [],
        })
      } else if (st?.mode === 'configured' && st.child) {
        children.push(build(st.child, slot.name, [...path, slot.id]))
      } else {
        children.push({
          label: slot.name, path: [...path, slot.id],
          status: 'todo', children: [],
        })
      }
    }
    for (const g of pendingGroups) {
      if (!resolvedGroups.has(g)) {
        children.push({ label: `${g}（待选）`, path, status: 'todo', children: [] })
      }
    }
    return {
      label, path,
      status: p.total > 0 && p.done === p.total ? 'done' : p.done > 0 ? 'progress' : 'todo',
      children,
    }
  }
  return [build(rootState.value, rootType.value.name, [])]
})

function onTreeClick(item: TreeItem) {
  if (item.status === 'blackbox') {
    currentPath.value = item.path.slice(0, -1)
    return
  }
  // 点击的若是未展开的槽，跳到其父节点；若是已配置节点，直接进入
  let node = rootState.value
  for (const slotId of item.path) {
    const st = node?.slots[slotId]
    if (st?.mode === 'configured' && st.child) node = st.child
    else {
      currentPath.value = item.path.slice(0, -1)
      return
    }
  }
  currentPath.value = item.path
}

// ---------- 终局动作 ----------
const saving = ref(false)
async function saveSku() {
  if (!rootState.value || !rootType.value) return
  const summary = result.value?.fingerprint?.slice(0, 12)
  try {
    await ElMessageBox.confirm(
      '请核对右侧配置摘要无误。保存后该配置将获得唯一 SKU 编码。',
      '保存为新 SKU', { confirmButtonText: '确认保存', type: 'info' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const { data } = await api.post('/skus', {
      config: toPayload(rootType.value.id, rootState.value),
    })
    if (data.created) {
      ElMessage.success(`已创建 ${data.sku.sku_code}`)
      if (auth.canSetPrice) await promptPrice(data.sku)
      else ElMessage.info('SKU 已进入「待录价」，录价后方可加入报价单')
    } else {
      ElMessage.warning(`该配置已存在：${data.sku.sku_code}`)
    }
    trigger(() => toPayload(rootType.value!.id, rootState.value!))
    if (draftId.value) {
      await api.delete(`/config-drafts/${draftId.value}`).catch(() => {})
      draftId.value = null
    }
  } finally {
    saving.value = false
  }
}

async function updateSku() {
  if (!rootState.value || !rootType.value || !editingSkuId.value) return
  // 询问原 SKU 去留：确认=停用，取消=保活，关闭=放弃整个保存
  let retireOld = false
  try {
    await ElMessageBox.confirm(
      `保存后将生成一个新 SKU（指纹改变，原 SKU 不会被原地修改）。`
      + `原 SKU ${editingSkuCode.value} 如何处理？`,
      '修改 SKU',
      {
        confirmButtonText: '停用原 SKU', cancelButtonText: '保活（仍可报价）',
        distinguishCancelAndClose: true, type: 'warning',
      },
    )
    retireOld = true
  } catch (action) {
    if (action === 'close') return
    retireOld = false
  }
  saving.value = true
  try {
    const { data } = await api.post(`/skus/${editingSkuId.value}/update`, {
      config: toPayload(rootType.value.id, rootState.value),
      retire_old: retireOld,
    })
    const verb = data.created ? '已生成新 SKU' : '该配置已存在，已指向'
    ElMessage.success(
      `${verb} ${data.new_sku.sku_code}；原 ${editingSkuCode.value} 已${retireOld ? '停用' : '保活'}`,
    )
    if (auth.canSetPrice && data.created && !data.new_sku.current_prices?.length) {
      await promptPrice(data.new_sku)
    }
    router.push({ path: '/skus', query: { sku_id: data.new_sku.id } })
  } catch { /* 409 无修改 / 422 不完整 由拦截器提示 */ } finally {
    saving.value = false
  }
}

async function saveSpec() {
  if (!rootState.value || !rootType.value || !partSpecId.value) return
  saving.value = true
  try {
    await api.patch(`/purchased-parts/${partSpecId.value}/spec`, {
      spec_config: toPayload(rootType.value.id, rootState.value),
      spec_note: specNote.value || null,
    })
    ElMessage.success(`「${partSpecName.value}」规格已保存`)
    router.push('/suppliers')
  } catch { /* 拦截器提示 */ } finally {
    saving.value = false
  }
}

async function promptPrice(sku: any) {
  try {
    const { value } = await ElMessageBox.prompt(
      `为 ${sku.sku_code} 录入对外报价单价（USD）`, '录入价格',
      { inputPattern: /^\d+(\.\d{1,4})?$/, inputErrorMessage: '请输入合法金额' },
    )
    await api.post(`/skus/${sku.id}/prices`, { price: value })
    ElMessage.success('价格已生效')
  } catch { /* 用户取消 */ }
}

async function addMatchedToQuote() {
  const matched = result.value?.matched_sku
  if (!matched) return
  const r = await cart.addSku(matched.id, 1)
  if (r.ok) ElMessage.success('已加入当前报价单')
  else if (r.message === 'NO_ACTIVE') {
    ElMessage.warning('尚无激活的报价单草稿，请先到「报价单」页新建')
    router.push('/quotations')
  } else ElMessage.error(r.message!)
}

async function saveDraft() {
  if (!rootState.value || !rootType.value) return
  const payload = JSON.parse(JSON.stringify(rootState.value))
  if (draftId.value) {
    await api.put(`/config-drafts/${draftId.value}`, {
      root_type_id: rootType.value.id, title: rootType.value.name, payload,
    })
  } else {
    const { data } = await api.post('/config-drafts', {
      root_type_id: rootType.value.id, title: rootType.value.name, payload,
    })
    draftId.value = data.id
  }
  ElMessage.success('草稿已保存（草稿不是 SKU，不参与报价）')
}

const matched = computed(() => result.value?.matched_sku ?? null)
const issues = computed(() => result.value?.issues ?? [])
const serverComplete = computed(() => result.value?.complete === true)
</script>

<template>
  <!-- 起点：选品类 / 续草稿 -->
  <div v-if="!rootState && !direct.active">
    <h3>开始一次配置</h3>
    <template v-for="group in [
      { label: '整机', items: rootTypes.filter((t: any) => t.kind === 'product') },
      { label: '配件单卖', items: rootTypes.filter((t: any) => t.kind === 'part') },
    ]" :key="group.label">
      <template v-if="group.items.length">
        <el-divider content-position="left">{{ group.label }}</el-divider>
        <el-row :gutter="16">
          <el-col v-for="t in group.items" :key="t.id" :span="6" style="margin-bottom: 12px">
            <el-card shadow="hover" :body-style="{ padding: '14px' }">
              <b>{{ t.name }}</b>
              <div style="color: var(--el-text-color-secondary); font-size: 12px; margin-bottom: 10px">{{ t.code }}</div>
              <div v-if="group.label === '整机'" style="display: flex; gap: 6px">
                <el-button size="small" type="primary" plain style="flex: 1" @click="startNew(t)">逐项配置</el-button>
                <el-button size="small" style="flex: 1" @click="startDirect(t)">整机直采</el-button>
              </div>
              <el-button v-else size="small" type="primary" plain style="width: 100%" @click="startNew(t)">开始配置</el-button>
            </el-card>
          </el-col>
        </el-row>
      </template>
    </template>
    <template v-if="drafts.length">
      <h4 style="margin-top: 24px">我的草稿</h4>
      <el-table :data="drafts" style="max-width: 720px" @row-click="startFromDraft">
        <el-table-column prop="title" label="品类" />
        <el-table-column prop="updated_at" label="最近编辑" width="200" />
        <el-table-column width="100">
          <template #default="{ row }">
            <el-button size="small" @click.stop="startFromDraft(row)">续配</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>

  <!-- 整机直采：整台外购成品直接成 SKU -->
  <div v-else-if="direct.active">
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px">
      <el-button @click="cancelDirect">← 返回</el-button>
      <h3 style="margin: 0">整机直采 · {{ direct.type?.name }}</h3>
    </div>
    <el-card style="max-width: 660px">
      <el-alert
        type="info" :closable="false" show-icon style="margin-bottom: 16px"
        title="整机直采 = 整台外购成品直接作为可售 SKU，无需逐项配置；整机的描述规格随采购件灰盒带入，不入指纹/报价。"
      />
      <el-form label-width="110px">
        <el-form-item label="整机采购件" required>
          <template v-if="direct.partId">
            <span>{{ direct.partLabel }}</span>
            <el-button text type="primary" size="small" style="margin-left: 8px" @click="directPicker.visible = true">更换</el-button>
          </template>
          <el-button v-else type="primary" @click="directPicker.visible = true">选择整机采购件</el-button>
        </el-form-item>
      </el-form>
      <div style="text-align: right; margin-top: 12px">
        <el-button @click="cancelDirect">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!direct.partId" @click="createDirect">
          创建整机直采 SKU
        </el-button>
      </div>
    </el-card>
    <PartPicker
      v-model:visible="directPicker.visible" :node-type-id="direct.type?.id ?? 0"
      :slot-name="`整机直采 · ${direct.type?.name ?? ''}`" @selected="onDirectPicked"
    />
  </div>

  <!-- 三栏看板 -->
  <el-row v-else :gutter="12" style="height: calc(100vh - 110px)">
    <!-- 左：产品构成树 -->
    <el-col :span="5" style="height: 100%">
      <el-card style="height: 100%; overflow: auto">
        <template #header>产品构成</template>
        <el-tree
          :data="treeData" default-expand-all :expand-on-click-node="false"
          @node-click="onTreeClick"
        >
          <template #default="{ data }">
            <span style="display: flex; align-items: center; gap: 4px">
              <el-icon v-if="data.status === 'done'" color="var(--el-color-success)"><CircleCheck /></el-icon>
              <el-icon v-else-if="data.status === 'progress'" color="var(--el-color-primary)"><Warning /></el-icon>
              <span v-else-if="data.status === 'blackbox'">■</span>
              <span v-else>○</span>
              {{ data.label }}
              <el-tag v-if="data.status === 'blackbox'" size="small" type="info">成品</el-tag>
            </span>
          </template>
        </el-tree>
      </el-card>
    </el-col>

    <!-- 中：当前节点编辑区 -->
    <el-col :span="12" style="height: 100%">
      <el-card style="height: 100%; overflow: auto">
        <template #header>
          <el-breadcrumb separator=">">
            <el-breadcrumb-item
              v-for="(c, i) in breadcrumb" :key="i"
              style="cursor: pointer" @click="currentPath = c.path"
            >{{ c.label }}</el-breadcrumb-item>
          </el-breadcrumb>
        </template>

        <template v-if="currentNode && currentMeta">
          <template v-if="currentMeta.attributes.length">
            <h4>规格参数</h4>
            <el-form label-width="110px">
              <el-form-item
                v-for="a in currentMeta.attributes" :key="a.id"
                :label="a.name" :required="a.is_required"
              >
                <el-radio-group
                  v-if="a.options.filter(o => o.is_active).length <= 5"
                  v-model="currentNode.attrs[a.id]"
                >
                  <el-radio-button
                    v-for="o in a.options.filter(o => o.is_active)" :key="o.id" :value="o.id"
                  >{{ o.label }}</el-radio-button>
                </el-radio-group>
                <el-select
                  v-else v-model="currentNode.attrs[a.id]" filterable clearable
                  placeholder="请选择" style="width: 260px"
                >
                  <el-option
                    v-for="o in a.options.filter(o => o.is_active)" :key="o.id"
                    :value="o.id" :label="o.label"
                  />
                </el-select>
              </el-form-item>
            </el-form>
          </template>

          <h4>采购来源
            <span style="font-size: 12px; color: var(--el-text-color-secondary); font-weight: 400">
              （非必选 · 标注后即区分为不同 SKU，改来源 = 新货）
            </span>
          </h4>
          <el-select
            v-model="currentNode.supplierId" clearable filterable placeholder="未标注来源"
            style="width: 280px; margin-bottom: 8px"
          >
            <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.name" />
          </el-select>

          <template v-if="currentMeta.slots.length">
            <h4>部件</h4>

            <!-- 互斥槽组：变体 N 选 1 -->
            <el-card
              v-for="g in slotGroups" :key="g.name" shadow="never" style="margin-bottom: 12px"
            >
              <template #header>
                <span>
                  {{ g.name }}
                  <el-tag size="small" type="danger" effect="plain">{{ g.slots.length }} 选 1</el-tag>
                </span>
              </template>
              <el-radio-group
                :model-value="groupChoice[g.name]"
                @update:model-value="(v: any) => chooseVariant(g, v)"
              >
                <el-radio-button v-for="s in g.slots" :key="s.id" :value="s.id">
                  {{ s.name }}
                </el-radio-button>
              </el-radio-group>

              <template v-for="slot in (chosenSlotOf(g) ? [chosenSlotOf(g)!] : [])" :key="slot.id">
                <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--el-border-color)">
                  <el-radio-group
                    :model-value="slotState(slot.id)?.mode"
                    size="small"
                    @update:model-value="(m: any) => setSlotMode(slot, m)"
                  >
                    <el-radio-button value="configured">逐项配置</el-radio-button>
                    <el-radio-button v-if="slot.allow_blackbox" value="purchased">选用成品采购件</el-radio-button>
                  </el-radio-group>
                  <div style="margin-top: 10px">
                    <template v-if="slotState(slot.id)?.mode === 'configured' && slotState(slot.id)?.child">
                      <el-progress
                        :percentage="(() => { const p = slotChildProgress(slot); return p && p.total ? Math.round(p.done / p.total * 100) : 0 })()"
                        :stroke-width="6" style="margin-bottom: 6px"
                      />
                      <el-button size="small" type="primary" plain @click="enterSlot(slot)">进入配置 →</el-button>
                    </template>
                    <template v-else-if="slotState(slot.id)?.mode === 'purchased' && slotState(slot.id)?.partId">
                      <el-tag type="info">成品采购件</el-tag>
                      <div style="margin: 6px 0">{{ slotState(slot.id)?.partLabel }}</div>
                      <el-button size="small" @click="openPartPicker(slot)">更换</el-button>
                    </template>
                    <div v-else style="color: var(--el-text-color-secondary); font-size: 12px">
                      请选择该型号的配置方式
                    </div>
                  </div>
                </div>
              </template>
            </el-card>

            <el-row :gutter="12">
              <el-col v-for="slot in ungroupedSlots" :key="slot.id" :span="12" style="margin-bottom: 12px">
                <el-card shadow="never">
                  <template #header>
                    <span>
                      {{ slot.name }}
                      <el-tag v-if="slot.is_required" size="small" type="danger" effect="plain">必配</el-tag>
                    </span>
                  </template>
                  <el-radio-group
                    :model-value="slotState(slot.id)?.mode"
                    size="small"
                    @update:model-value="(m: any) => setSlotMode(slot, m)"
                  >
                    <el-radio-button value="configured">逐项配置</el-radio-button>
                    <el-radio-button v-if="slot.allow_blackbox" value="purchased">选用成品采购件</el-radio-button>
                  </el-radio-group>

                  <div style="margin-top: 10px">
                    <template v-if="slotState(slot.id)?.mode === 'configured' && slotState(slot.id)?.child">
                      <el-progress
                        :percentage="(() => { const p = slotChildProgress(slot); return p && p.total ? Math.round(p.done / p.total * 100) : 0 })()"
                        :stroke-width="6" style="margin-bottom: 6px"
                      />
                      <el-button size="small" type="primary" plain @click="enterSlot(slot)">进入配置 →</el-button>
                    </template>
                    <template v-else-if="slotState(slot.id)?.mode === 'purchased' && slotState(slot.id)?.partId">
                      <el-tag type="info">成品采购件</el-tag>
                      <div style="margin: 6px 0">{{ slotState(slot.id)?.partLabel }}</div>
                      <el-button size="small" @click="openPartPicker(slot)">更换</el-button>
                    </template>
                    <div v-else style="color: var(--el-text-color-secondary); font-size: 12px">
                      {{ slot.is_required ? '尚未配置' : '可选，未配置' }}
                    </div>
                  </div>
                </el-card>
              </el-col>
            </el-row>
          </template>
        </template>
      </el-card>
    </el-col>

    <!-- 右：进度 / 命中 / 动作 -->
    <el-col :span="7" style="height: 100%">
      <el-card style="height: 100%; overflow: auto">
        <template #header>{{ partSpecId ? '部件规格' : '配置摘要' }}</template>

        <!-- 灰盒·部件规格模式：全选填、仅描述、不进指纹 -->
        <template v-if="partSpecId">
          <el-alert
            type="warning" :closable="false" show-icon style="margin-bottom: 12px"
            :title="`编辑「${partSpecName}」的规格`"
            description="全部选填，只为记录这件成品采购件的内部规格；不进 SKU 指纹、不参与报价。"
          />
          <h4 style="margin-top: 0">自由规格（纯文本）</h4>
          <el-input
            v-model="specNote" type="textarea" :rows="3"
            placeholder="结构化属性之外的补充，如：出口认证 CE、材质说明、厂家备注…（可空）"
          />
          <el-divider />
          <el-button type="primary" style="width: 100%" :loading="saving" @click="saveSpec">
            保存规格
          </el-button>
          <el-button style="width: 100%; margin-top: 8px" @click="router.push('/suppliers')">
            放弃 · 返回供应商与采购件
          </el-button>
          <p style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 10px">
            左侧/中间像配置看板一样填这件的属性与子部件——但这里全是选填，填多少看你想记多少。
          </p>
        </template>

        <template v-else>
        <el-alert
          v-if="editingSkuId" type="warning" :closable="false" show-icon style="margin-bottom: 10px"
          :title="`修改模式：原 ${editingSkuCode}`"
          description="保存将生成一个新 SKU，原 SKU 由你选择停用或保活；指纹绝不原地修改。"
        />
        <el-progress :percentage="progressPct" :status="progressPct === 100 ? 'success' : undefined" />

        <template v-if="issues.length">
          <h4>待完成（{{ issues.length }}）</h4>
          <div v-for="(i, idx) in issues" :key="idx" style="font-size: 13px; margin-bottom: 4px">
            <el-tag :type="i.kind === 'error' ? 'danger' : 'warning'" size="small">
              {{ i.kind === 'error' ? '错误' : '缺' }}
            </el-tag>
            {{ i.message }}
          </div>
        </template>

        <template v-if="serverComplete">
          <el-divider />
          <!-- 修改既有 SKU：统一走"保存修改"(update)；命中既有指纹由后端处理 -->
          <template v-if="editingSkuId">
            <el-alert
              v-if="matched && matched.id === editingSkuId" type="info" :closable="false"
              title="尚未做出改动" description="修改任一项后再保存"
            />
            <el-alert
              v-else-if="matched" type="warning" :closable="false"
              :title="`改后的配置与既有 ${matched.sku_code} 相同，保存将指向它`"
            />
            <el-button
              type="primary" style="width: 100%; margin-top: 10px" :loading="saving"
              :disabled="!!(matched && matched.id === editingSkuId)" @click="updateSku"
            >保存修改</el-button>
          </template>
          <template v-else-if="matched">
            <el-alert type="success" :closable="false" title="该配置已存在">
              <p style="font-size: 15px"><b>{{ matched.sku_code }}</b>（{{ matched.status === 'active' ? '在售' : '已作废' }}）</p>
              <p>{{ matched.name }}</p>
              <p v-if="matched.current_prices.length" style="font-size: 18px; color: var(--el-color-success)">
                {{ matched.current_prices[0].currency }} {{ matched.current_prices[0].price }}
                <small>（{{ matched.current_prices[0].valid_from }} 起生效）</small>
              </p>
              <p v-else style="color: var(--el-color-warning)">待录价</p>
            </el-alert>
            <el-button
              type="primary" style="width: 100%; margin-top: 10px"
              :disabled="!matched.current_prices.length || matched.status !== 'active'"
              @click="addMatchedToQuote"
            >加入报价单</el-button>
          </template>
          <template v-else>
            <el-alert type="info" :closable="false" title="新配置，尚无对应 SKU" />
            <el-button
              type="primary" style="width: 100%; margin-top: 10px" :loading="saving"
              @click="saveSku"
            >保存为新 SKU</el-button>
          </template>
        </template>

        <el-divider />
        <div style="display: flex; gap: 8px">
          <el-button style="flex: 1" @click="saveDraft">存草稿</el-button>
          <el-button style="flex: 1" @click="rootState = null">放弃</el-button>
        </div>
        <div v-if="validating" style="margin-top: 8px; color: var(--el-text-color-secondary); font-size: 12px">
          校验中…
        </div>
        </template>
      </el-card>
    </el-col>
  </el-row>

  <PartPicker
    v-model:visible="picker.visible"
    :node-type-id="picker.nodeTypeId"
    :slot-name="picker.slotName"
    @selected="onPartSelected"
  />
</template>
