<script setup lang="ts">
/** 产品模板管理（admin）：节点类型 / 属性与选项 / 部件槽。
 *  纪律由后端强制（code 不可变、软停用、引用计数、DAG、可选属性"无"选项禁令），
 *  此页只做呈现与触发。 */
import { Bottom, Right, Search, Top } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'

const types = ref<any[]>([])
const selected = ref<any | null>(null)
const optionRows = reactive<Record<number, any[]>>({})
// 档位二：双维上级归属（部件级 direct + 品类级 root_categories）与面包屑导航轨迹
const parentsDim = ref<{ direct: any[]; root_categories: any[] }>({ direct: [], root_categories: [] })
const navTrail = ref<{ id: number; name: string }[]>([])

// code 全部由后端按名称自动生成（拼音转写+查重），UI 不再要求填写
const typeDialog = reactive({ visible: false, form: { name: '', kind: 'part', is_sellable_root: false } })
const attrDialog = reactive({ visible: false, form: { name: '', is_required: true, is_filterable: false } })
const optDialog = reactive({ visible: false, attrId: 0, form: { label: '' } })
type VariantMode = 'none' | 'existing' | 'new'
const slotDialog = reactive({
  visible: false,
  source: 'existing' as 'existing' | 'new',   // 起点二分叉：用现存部件 / 新建部件
  variantMode: 'none' as VariantMode,         // N选1 三态：普通 / 加入已有组 / 新建组
  suffix: '',                                 // 选已有时·同父重复挂同类型才解锁的区分后缀
  form: {
    name: '', child_type_id: null as number | null,
    is_required: true, allow_blackbox: true, variant_group: '',
  },
})

function openSlotDialog() {
  slotDialog.source = 'existing'
  slotDialog.variantMode = 'none'
  slotDialog.suffix = ''
  slotDialog.form = { name: '', child_type_id: null, is_required: true, allow_blackbox: true, variant_group: '' }
  slotDialog.visible = true
}
function onSlotSourceChange() {
  // 切换来源清空名称/类型/后缀，避免跨路残留
  slotDialog.form.child_type_id = null
  slotDialog.form.name = ''
  slotDialog.suffix = ''
}
function onSlotVariantMode() {
  slotDialog.form.variant_group = ''  // 切换三态清空组名，避免误带
}

// 当前父下已存在的「选择组」(variant_group 去重) + 成员名，供"加入已有组"下拉与查重
const existingGroups = computed<{ group: string; members: string[] }[]>(() => {
  const map = new Map<string, string[]>()
  for (const s of selected.value?.slots ?? []) {
    if (!s.variant_group) continue
    if (!map.has(s.variant_group)) map.set(s.variant_group, [])
    map.get(s.variant_group)!.push(typeName(s.child_type_id) as string)
  }
  return [...map.entries()].map(([group, members]) => ({ group, members }))
})
// 选已有类型路：槽名继承类型名(+可选区分后缀)
const slotInheritedName = computed(() => {
  if (slotDialog.source !== 'existing' || !slotDialog.form.child_type_id) return ''
  const base = typeName(slotDialog.form.child_type_id) as string
  const sfx = slotDialog.suffix.trim()
  return sfx ? `${base}-${sfx}` : base
})
// 同父已存在引用同一 child_type 的活跃槽 → 解锁区分后缀(否则两槽同名易混)
const slotDupChildType = computed(() =>
  slotDialog.source === 'existing' && slotDialog.form.child_type_id != null
  && (selected.value?.slots ?? []).some(
    (s: any) => s.child_type_id === slotDialog.form.child_type_id && s.is_active))

// ---- 在位编辑（仅可变字段；code/所属结构不可改，物理删除不存在）----
const editDialog = reactive({
  visible: false,
  kind: 'attr' as 'type' | 'attr' | 'option' | 'slot',
  id: 0,
  refCount: 0,
  variantMode: 'none' as VariantMode,  // 编辑槽时的 N选1 三态
  form: {} as Record<string, any>,
})
function onEditVariantMode() {
  editDialog.form.variant_group = ''  // 切到普通/重选时清空，select/input 重新赋值
}

const EDIT_TITLES = { type: '编辑节点类型', attr: '编辑属性', option: '编辑选项', slot: '编辑部件槽' }

function openEdit(kind: typeof editDialog.kind, row: any, refCount = 0) {
  editDialog.kind = kind
  editDialog.id = row.id
  editDialog.refCount = refCount
  if (kind === 'type') {
    editDialog.form = { name: row.name, is_sellable_root: row.is_sellable_root }
  } else if (kind === 'attr') {
    editDialog.form = {
      name: row.name, unit: row.unit ?? '',
      is_required: row.is_required, is_filterable: row.is_filterable,
    }
  } else if (kind === 'option') {
    editDialog.form = { label: row.label }
  } else {
    editDialog.form = {
      name: row.name, is_required: row.is_required, allow_blackbox: row.allow_blackbox,
      variant_group: row.variant_group ?? '',
    }
    editDialog.variantMode = row.variant_group ? 'existing' : 'none'
  }
  editDialog.visible = true
}

async function saveEdit() {
  const { kind, id } = editDialog
  // 已被 SKU 引用的选项改名：技术安全（编码与指纹不变），但会同步改变历史 SKU 的展示，
  // 必须让管理员区分"纠错"与"换义"
  if (kind === 'option' && editDialog.refCount > 0) {
    try {
      await ElMessageBox.confirm(
        `该选项已被 ${editDialog.refCount} 个 SKU 引用，改名后这些 SKU 的展示会同步变化。`
        + '改名仅用于纠错（错别字、表述规范）；若是换成不同含义（如 4kg 改成 5kg），'
        + '请取消本次操作，新建一个选项并停用旧选项。',
        '改名会影响历史 SKU 的展示',
        { type: 'warning', confirmButtonText: '我确认是纠错改名', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  const urls: Record<string, string> = {
    type: `/template/node-types/${id}`,
    attr: `/template/attributes/${id}`,
    option: `/template/options/${id}`,
    slot: `/template/slots/${id}`,
  }
  const payload = { ...editDialog.form }
  if (payload.unit === '') delete payload.unit
  // C dry-run：把"非必选→必选"这种收紧改动落库前预演影响面
  if (payload.is_required === true) {
    const et = { type: 'node_type', attr: 'attribute', option: 'option', slot: 'slot' }[kind]
    if (!(await confirmImpact(et, id, { is_required: true }))) return
  }
  await api.patch(urls[kind], payload)
  editDialog.visible = false
  await loadTypes()
  if (selected.value) await select(selected.value)
  ElMessage.success('已保存（操作已记录审计）')
}

// ---- 左栏分组 + 搜索 ----
const search = ref('')
const GROUP_DEFS = [
  { key: 'products', label: '整机品类', match: (t: any) => t.kind === 'product' },
  { key: 'sellableParts', label: '可单卖配件', match: (t: any) => t.kind === 'part' && t.is_sellable_root },
  { key: 'commonParts', label: '通用部件', match: (t: any) => t.kind === 'part' && !t.is_sellable_root },
]
const grouped = computed<Record<string, any[]>>(() => {
  const kw = search.value.trim().toLowerCase()
  const hit = (t: any) => !kw || t.name.toLowerCase().includes(kw) || (t.code ?? '').toLowerCase().includes(kw)
  const r: Record<string, any[]> = {}
  for (const g of GROUP_DEFS) r[g.key] = types.value.filter((t) => g.match(t) && hit(t))
  return r
})

async function selectById(id: number) {
  const t = types.value.find((x) => x.id === id)
  if (t) await select(t, true)  // 经脉络带/面包屑跳转 → 计入导航轨迹
}

// 当前节点的下级↓：其部件槽的子类型（去重），结构脉络带用
const childTypes = computed<{ id: number; name: string }[]>(() => {
  const seen = new Map<number, string>()
  for (const s of selected.value?.slots ?? []) {
    if (!seen.has(s.child_type_id)) seen.set(s.child_type_id, typeName(s.child_type_id))
  }
  return [...seen.entries()].map(([id, name]) => ({ id, name }))
})

async function gotoTrail(idx: number) {
  const node = navTrail.value[idx]
  navTrail.value = navTrail.value.slice(0, idx)  // select(viaNav) 会把自己补回末尾
  const t = types.value.find((x) => x.id === node.id)
  if (t) await select(t, true)
}

/** C dry-run：收紧/停用类改动落库前预演影响面，>0 时二次确认。返回是否继续。 */
async function confirmImpact(
  entityType: string, entityId: number, changes: Record<string, boolean>,
): Promise<boolean> {
  let res: any
  try {
    res = (await api.post('/template/preview-impact', {
      entity_type: entityType, entity_id: entityId, changes,
    })).data
  } catch {
    return true  // 预演本身失败不阻断正常操作
  }
  if (!res.newly_broken) return true
  const f = res.by_family
  const parts: string[] = []
  if (f.completeness) parts.push(`缺必配 ${f.completeness}`)
  if (f.structural) parts.push(`违反互斥 ${f.structural}`)
  if (f.supply) parts.push(`含停用件 ${f.supply}`)
  const samples = res.samples.slice(0, 5).map((s: any) => s.sku_code).join('、')
  try {
    await ElMessageBox.confirm(
      `此改动将让 ${res.newly_broken} 个在售 SKU 变成残货（${parts.join('；')}）。`
      + (samples ? `例如 ${samples}。` : '')
      + '它们将无法加入报价单，需到 SKU 库「待治理」逐一处理。确认继续？',
      '影响面预警',
      { type: 'warning', confirmButtonText: '仍然继续', cancelButtonText: '取消' },
    )
    return true
  } catch {
    return false
  }
}

// ---- 组内拖拽排序（搜索态禁用，避免丢失未显示项）；reorder 始终传全量顺序（组优先+组内序）----
const drag = reactive({ group: '', idx: -1 })
function onDragStart(group: string, idx: number) {
  drag.group = group
  drag.idx = idx
}
async function onDrop(group: string, targetIdx: number) {
  const from = drag.idx
  const fromGroup = drag.group
  drag.idx = -1
  if (search.value || fromGroup !== group || from < 0 || from === targetIdx) return
  const arr = grouped.value[group].slice()
  const moved = arr.splice(from, 1)[0]
  arr.splice(targetIdx, 0, moved)
  const ids: number[] = []
  for (const g of GROUP_DEFS) {
    const list = g.key === group ? arr : grouped.value[g.key]
    ids.push(...list.map((t) => t.id))
  }
  await api.put('/template/node-types/reorder', { ids })
  await loadTypes()
  ElMessage.success('排序已保存')
}

async function loadTypes() {
  types.value = (await api.get('/template/node-types', {
    params: { include_inactive: true, with_counts: true },
  })).data
}

async function select(t: any, viaNav = false) {
  const { data } = await api.get(`/template/node-types/${t.id}`)
  selected.value = data
  parentsDim.value = (await api.get(`/template/node-types/${t.id}/parents`)).data
  for (const a of data.attributes) {
    optionRows[a.id] = (await api.get(`/template/attributes/${a.id}/options`)).data
  }
  if (viaNav) {
    // 已在轨迹中（含来回穿行回到祖先）→ 截断回到该节点，绝不重复追加，避免面包屑无限嵌套累积
    const at = navTrail.value.findIndex((n) => n.id === t.id)
    if (at >= 0) navTrail.value = navTrail.value.slice(0, at + 1)
    else navTrail.value.push({ id: t.id, name: data.name })
  } else {
    navTrail.value = [{ id: t.id, name: data.name }]  // 从左栏直选 = 新起点
  }
}

onMounted(() => loadTypes().catch(() => { /* 401 由拦截器跳转登录 */ }))

async function createType() {
  await api.post('/template/node-types', typeDialog.form)
  typeDialog.visible = false
  typeDialog.form = { name: '', kind: 'part', is_sellable_root: false }
  await loadTypes()
  ElMessage.success('已创建')
}

async function toggleTypeActive(t: any) {
  // 反向归属预警：停用一个被上级共用的部件，会让上级在新配置里选不到它
  if (t.is_active && t.parents?.length) {
    try {
      await ElMessageBox.confirm(
        `「${t.name}」被 ${t.parents.length} 个上级总成（${t.parents.map((p: any) => p.name).join('、')}）`
        + '当部件引用，停用后这些上级在新配置里将选不到它（既有 SKU 不受影响）。确认停用？',
        '该部件被上级共用', { type: 'warning' },
      )
    } catch {
      return
    }
  }
  // C dry-run：停用类型对既有在售 SKU 的影响面预演（与上面"新配置"预警互补）
  if (t.is_active && !(await confirmImpact('node_type', t.id, { is_active: false }))) return
  await api.patch(`/template/node-types/${t.id}`, { is_active: !t.is_active })
  await loadTypes()
  if (selected.value?.id === t.id) await select(t, true)
}

async function createAttr() {
  await api.post(`/template/node-types/${selected.value.id}/attributes`, attrDialog.form)
  attrDialog.visible = false
  attrDialog.form = { name: '', is_required: true, is_filterable: false }
  await select(selected.value)
}

async function createOption() {
  try {
    await api.post(`/template/attributes/${optDialog.attrId}/options`, optDialog.form)
    optDialog.visible = false
    optDialog.form = { label: '' }
    await select(selected.value)
  } catch (e: any) {
    // 409（如可选属性"无"选项禁令）由拦截器提示
  }
}

async function toggleOption(o: any) {
  // 停用方向：落库前预演影响面（启用方向不会让既有 SKU 变残，免预演）
  if (o.is_active && !(await confirmImpact('option', o.id, { is_active: false }))) return
  await api.patch(`/template/options/${o.id}`, { is_active: !o.is_active })
  await select(selected.value, true)
  ElMessage.success(o.is_active ? '已停用：新配置不可选，既有 SKU 不受影响' : '已启用')
}

// 三态归组 → 最终 variant_group 字符串(null=普通)
function resolveVariantGroup(): string | null {
  if (slotDialog.variantMode === 'existing') return slotDialog.form.variant_group || null
  if (slotDialog.variantMode === 'new') return slotDialog.form.variant_group.trim() || null
  return null
}

async function createSlot() {
  // 起点二分叉：用现存部件=名称继承类型名(+后缀)；新建部件=输入名兼作新类型名与槽名
  let childTypeId: number | null
  let slotName: string
  if (slotDialog.source === 'existing') {
    if (!slotDialog.form.child_type_id) {
      ElMessage.warning('请选择已有的部件类型')
      return
    }
    childTypeId = slotDialog.form.child_type_id
    slotName = slotInheritedName.value
  } else {
    if (!slotDialog.form.name.trim()) {
      ElMessage.warning('请填写新部件名称')
      return
    }
    childTypeId = null  // 待新建
    slotName = slotDialog.form.name.trim()
  }
  const variantGroup = resolveVariantGroup()
  // 新建组·同父查重(纯前端防呆，重名后端无害但易误合并)
  if (slotDialog.variantMode === 'new' && variantGroup
      && existingGroups.value.some((g) => g.group === variantGroup)) {
    ElMessage.warning(`选择组「${variantGroup}」已存在，请改用「加入已有组」`)
    return
  }

  let newTypeId: number | null = null
  try {
    if (slotDialog.source === 'new') {
      // 第一步：建新部件类型（code 后端自动生成）
      const { data } = await api.post('/template/node-types', { name: slotName, kind: 'part' })
      newTypeId = data.id
      childTypeId = newTypeId
      await loadTypes()
    }
    try {
      // 第二步：挂槽（code 留空由后端生成、父下唯一；指纹只认 code 不认 name）
      await api.post(`/template/node-types/${selected.value.id}/slots`, {
        name: slotName,
        child_type_id: childTypeId,
        is_required: slotDialog.form.is_required,
        allow_blackbox: slotDialog.form.allow_blackbox,
        variant_group: variantGroup,
      })
    } catch (slotErr) {
      // 失败兜底：停用刚建的临时类型，杜绝"未挂载孤儿类型"(409 原因由拦截器已提示)
      if (newTypeId != null) {
        await api.patch(`/template/node-types/${newTypeId}`, { is_active: false }).catch(() => {})
        await loadTypes()
        ElMessage.warning('挂载失败，已自动清理刚建的未挂载临时类型')
      }
      throw slotErr
    }
    slotDialog.visible = false
    await select(selected.value)
    ElMessage.success('部件槽已创建')
  } catch {
    // 409（DAG 防环 / code 冲突等）由拦截器提示
  }
}

async function toggleSlot(s: any) {
  if (s.is_active && !(await confirmImpact('slot', s.id, { is_active: false }))) return
  await api.patch(`/template/slots/${s.id}`, { is_active: !s.is_active })
  await select(selected.value, true)
}

function typeName(id: number) {
  return types.value.find((t) => t.id === id)?.name ?? id
}
</script>

<template>
  <el-row :gutter="12">
    <el-col :span="6">
      <el-card>
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            节点类型
            <el-button size="small" type="primary" @click="typeDialog.visible = true">新建</el-button>
          </div>
        </template>
        <el-input v-model="search" placeholder="搜索名称 / 编码" clearable size="small" style="margin-bottom: 8px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="type-list">
        <template v-for="g in GROUP_DEFS" :key="g.key">
          <div v-if="grouped[g.key].length" class="side-group">
            {{ g.label }} <span class="gcnt">{{ grouped[g.key].length }}</span>
          </div>
          <div
            v-for="(t, idx) in grouped[g.key]" :key="t.id" class="type-item"
            :class="{ active: selected?.id === t.id, inactive: !t.is_active, dragging: drag.group === g.key && drag.idx === idx }"
            :draggable="!search"
            @click="select(t)"
            @dragstart="onDragStart(g.key, idx)"
            @dragover.prevent
            @drop.prevent="onDrop(g.key, idx)"
            @dragend="drag.idx = -1"
          >
            <span v-if="!search" class="drag-handle" title="拖动排序（组内）">⠿</span>
            <span class="ti-name">{{ t.name }}</span>
            <span class="badges">
              <el-tag v-if="t.sku_count" size="small" type="success" effect="plain" title="在售 SKU 数">{{ t.sku_count }}</el-tag>
              <el-tag v-if="t.parent_count" size="small" type="warning" effect="plain" title="被几个上级引用">↑{{ t.parent_count }}</el-tag>
              <span v-if="t.kind === 'part' && !t.parent_count" class="orphan" title="未被任何上级引用">未挂载</span>
            </span>
          </div>
        </template>
        <el-empty v-if="!grouped.products.length && !grouped.sellableParts.length && !grouped.commonParts.length"
                  :image-size="50" description="无匹配" />
        </div>
        <p style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 8px">
          搜索定位 · 组内拖拽排序（搜索时暂停）· 徽标：绿=在售SKU，橙↑=被几个上级引用
        </p>
      </el-card>
    </el-col>

    <el-col :span="18">
      <el-card v-if="selected">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>{{ selected.name }}</span>
            <span>
              <el-button size="small" @click="openEdit('type', selected)">编辑</el-button>
              <el-button size="small" :type="selected.is_active ? 'danger' : 'success'" plain
                         @click="toggleTypeActive(selected)">
                {{ selected.is_active ? '停用' : '启用' }}
              </el-button>
            </span>
          </div>
        </template>

        <!-- 档位二·结构脉络带：上级↑（品类级+部件级双维）/ 本体 / 下级↓，可点击穿行 -->
        <el-card shadow="never" class="spine-card" body-style="padding: 10px 12px">
          <el-breadcrumb v-if="navTrail.length > 1" separator="›" class="spine-crumb">
            <el-breadcrumb-item v-for="(n, i) in navTrail" :key="i">
              <a class="crumb-link" @click="gotoTrail(i)">{{ n.name }}</a>
            </el-breadcrumb-item>
          </el-breadcrumb>

          <div class="spine-row">
            <span class="spine-label"><el-icon><Top /></el-icon> 上级</span>
            <template v-if="parentsDim.root_categories.length || parentsDim.direct.length">
              <el-tag
                v-for="p in parentsDim.root_categories" :key="'c' + p.id" class="chip"
                type="primary" effect="dark" @click="selectById(p.id)"
              >{{ p.name }}<small class="chip-kind">品类</small></el-tag>
              <el-tag
                v-for="p in parentsDim.direct" :key="'d' + p.id" class="chip"
                :type="p.is_active ? 'warning' : 'info'" effect="plain" @click="selectById(p.id)"
              >{{ p.name }}</el-tag>
            </template>
            <span v-else class="spine-none">顶层 / 暂未被任何上级引用</span>
          </div>

          <div class="spine-row spine-self">
            <span class="spine-label">本体</span>
            <b>{{ selected.name }}</b>
            <el-tag size="small" effect="plain">{{ selected.kind === 'product' ? '整机' : '部件' }}</el-tag>
            <el-tag v-if="!selected.is_active" size="small" type="info">已停用</el-tag>
          </div>

          <div class="spine-row">
            <span class="spine-label"><el-icon><Bottom /></el-icon> 下级</span>
            <template v-if="childTypes.length">
              <el-tag
                v-for="c in childTypes" :key="c.id" class="chip"
                type="success" effect="plain" @click="selectById(c.id)"
              >{{ c.name }}<el-icon class="chip-arrow"><Right /></el-icon></el-tag>
            </template>
            <span v-else class="spine-none">无下级部件（叶子类型）</span>
          </div>

          <div
            v-if="selected.kind === 'part' && parentsDim.direct.length"
            class="spine-foot"
          >只读 · 双维归属：品类级为沿槽图上溯的可售根，部件级为直接上级 · 停用/改名将波及上级；解除引用请到对应上级停用该部件槽</div>
        </el-card>

        <h4>规格属性
          <el-button size="small" style="margin-left: 8px" @click="attrDialog.visible = true">+ 属性</el-button>
        </h4>
        <el-collapse>
          <el-collapse-item v-for="a in selected.attributes" :key="a.id">
            <template #title>
              {{ a.name }}
              <el-tag v-if="a.is_required" size="small" style="margin-left: 6px">必选</el-tag>
              <el-tag v-if="a.is_filterable" size="small" type="success" style="margin-left: 4px">筛选项</el-tag>
              <el-tag v-if="!a.is_active" size="small" type="info" style="margin-left: 4px">已停用</el-tag>
              <el-button
                text type="primary" size="small" style="margin-left: 8px"
                @click.stop="openEdit('attr', a)"
              >编辑</el-button>
            </template>
            <el-table :data="optionRows[a.id] ?? []" size="small">
              <el-table-column prop="code" label="选项 code（不可变）" width="170" />
              <el-table-column prop="label" label="显示名" />
              <el-table-column prop="reference_count" label="被引用" width="80" />
              <el-table-column label="状态 / 操作" width="220">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
                    {{ row.is_active ? '可用' : '已停用' }}
                  </el-tag>
                  <el-button text type="primary" size="small"
                             @click="openEdit('option', row, row.reference_count)">编辑</el-button>
                  <el-button text size="small" @click="toggleOption(row)">
                    {{ row.is_active ? '停用' : '启用' }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-button size="small" style="margin-top: 6px"
                       @click="optDialog.visible = true; optDialog.attrId = a.id">+ 选项</el-button>
          </el-collapse-item>
        </el-collapse>

        <h4 style="margin-top: 18px">部件槽
          <el-button size="small" style="margin-left: 8px" @click="openSlotDialog">+ 部件槽</el-button>
        </h4>
        <el-table :data="selected.slots" size="small">
          <el-table-column prop="code" label="槽 code（不可变）" width="160" />
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column label="部件类型" width="130">
            <template #default="{ row }">{{ typeName(row.child_type_id) }}</template>
          </el-table-column>
          <el-table-column label="必配" width="70">
            <template #default="{ row }">{{ row.is_required ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="允许成品件" width="100">
            <template #default="{ row }">{{ row.allow_blackbox ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="互斥组" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.variant_group" size="small" type="warning">{{ row.variant_group }}</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="状态 / 操作" width="210">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
                {{ row.is_active ? '可用' : '已停用' }}
              </el-tag>
              <el-button text type="primary" size="small" @click="openEdit('slot', row)">编辑</el-button>
              <el-button text size="small" @click="toggleSlot(row)">
                {{ row.is_active ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-alert
          type="info" :closable="false" style="margin-top: 16px"
          title="模板纪律（系统强制）"
          description="编码由系统按名称自动生成、一经创建不可修改（进入 SKU 唯一性校验）；删除一律软停用，被 SKU 引用的对象数据库层禁止物理删除；停用只影响新配置，既有 SKU 的展示与指纹永不改变；可选属性禁止创建“无/不带”语义的选项。"
        />
      </el-card>
      <el-empty v-else description="左侧选择一个节点类型" />
    </el-col>
  </el-row>

  <!-- 对话框们 -->
  <el-dialog v-model="typeDialog.visible" title="新建节点类型" width="460">
    <el-form label-width="110px">
      <el-form-item label="名称" required>
        <el-input v-model="typeDialog.form.name" placeholder="如：顶杆（编码由系统自动生成）" />
      </el-form-item>
      <el-form-item label="类别">
        <el-radio-group v-model="typeDialog.form.kind">
          <el-radio value="product">整机品类</el-radio>
          <el-radio value="part">部件类型</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="可作可售根">
        <el-switch v-model="typeDialog.form.is_sellable_root" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="typeDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createType">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="attrDialog.visible" title="新建属性" width="460">
    <el-form label-width="110px">
      <el-form-item label="名称" required>
        <el-input v-model="attrDialog.form.name" placeholder="如：充装量" />
      </el-form-item>
      <el-form-item label="必选"><el-switch v-model="attrDialog.form.is_required" /></el-form-item>
      <el-form-item label="作为筛选项"><el-switch v-model="attrDialog.form.is_filterable" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="attrDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createAttr">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="optDialog.visible" title="新建选项" width="460">
    <el-form label-width="110px">
      <el-form-item label="显示名" required>
        <el-input v-model="optDialog.form.label" placeholder="如 4kg（编码由系统自动生成）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="optDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createOption">创建</el-button>
    </template>
  </el-dialog>

  <!-- 在位编辑对话框：只暴露安全可变字段；code 与所属结构不可改 -->
  <el-dialog v-model="editDialog.visible" :title="EDIT_TITLES[editDialog.kind]" width="460">
    <el-form label-width="110px">
      <template v-if="editDialog.kind === 'type'">
        <el-form-item label="名称" required><el-input v-model="editDialog.form.name" /></el-form-item>
        <el-form-item label="可作可售根"><el-switch v-model="editDialog.form.is_sellable_root" /></el-form-item>
      </template>
      <template v-else-if="editDialog.kind === 'attr'">
        <el-form-item label="名称" required><el-input v-model="editDialog.form.name" /></el-form-item>
        <el-form-item label="单位"><el-input v-model="editDialog.form.unit" placeholder="如 kg、MPa（可空）" /></el-form-item>
        <el-form-item label="必选"><el-switch v-model="editDialog.form.is_required" /></el-form-item>
        <el-form-item label="作为筛选项"><el-switch v-model="editDialog.form.is_filterable" /></el-form-item>
      </template>
      <template v-else-if="editDialog.kind === 'option'">
        <el-form-item label="显示名" required><el-input v-model="editDialog.form.label" /></el-form-item>
        <el-alert
          v-if="editDialog.refCount > 0" type="warning" :closable="false"
          :title="`该选项被 ${editDialog.refCount} 个 SKU 引用，改名将同步改变它们的展示`"
          description="仅限纠错（错别字/表述）。若是换成不同含义（如 4kg→5kg），请新建选项并停用本选项。"
        />
      </template>
      <template v-else>
        <el-form-item label="名称" required><el-input v-model="editDialog.form.name" /></el-form-item>
        <el-form-item label="必配">
          <el-switch v-model="editDialog.form.is_required" :disabled="editDialog.variantMode !== 'none'" />
          <span v-if="editDialog.variantMode !== 'none'" style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">归组后由选择组接管</span>
        </el-form-item>
        <el-form-item label="允许成品件"><el-switch v-model="editDialog.form.allow_blackbox" /></el-form-item>
        <el-form-item label="这个位置是">
          <el-radio-group v-model="editDialog.variantMode" @change="onEditVariantMode">
            <el-radio-button value="none">普通位置</el-radio-button>
            <el-radio-button value="existing" :disabled="!existingGroups.length">加入选择组</el-radio-button>
            <el-radio-button value="new">新建选择组</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="editDialog.variantMode === 'existing'" label="选择组">
          <el-select v-model="editDialog.form.variant_group" style="width: 100%" placeholder="加入哪个 N选1 组">
            <el-option
              v-for="g in existingGroups" :key="g.group" :value="g.group"
              :label="`${g.group}（${g.members.join('、')}）`"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-else-if="editDialog.variantMode === 'new'" label="新组名">
          <el-input v-model="editDialog.form.variant_group" placeholder="业务名，如 阀门型号" />
        </el-form-item>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="editDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="saveEdit">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="slotDialog.visible" title="新建部件槽" width="520">
    <el-form label-width="96px">
      <!-- 第一步·起点二分叉 -->
      <el-form-item label="部件来源">
        <el-segmented
          v-model="slotDialog.source" @change="onSlotSourceChange"
          :options="[{ label: '用现存部件', value: 'existing' }, { label: '新建部件', value: 'new' }]"
        />
      </el-form-item>

      <!-- 路A：用现存部件——名称继承类型名 -->
      <template v-if="slotDialog.source === 'existing'">
        <el-form-item label="部件类型" required>
          <el-select
            v-model="slotDialog.form.child_type_id" filterable style="width: 100%"
            placeholder="选择已有的部件类型" @change="slotDialog.suffix = ''"
          >
            <el-option
              v-for="t in types.filter(t => t.is_active)" :key="t.id" :value="t.id"
              :label="t.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="slotDialog.form.child_type_id" label="该位置名称">
          <span style="font-size: 14px">{{ slotInheritedName }}</span>
          <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">随类型名 · 不可改</span>
        </el-form-item>
        <el-form-item v-if="slotDupChildType" label="区分后缀">
          <el-input v-model="slotDialog.suffix" placeholder="如 进气 / 排气" style="width: 200px" />
          <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">同父已有同类型槽，加后缀区分</span>
        </el-form-item>
      </template>

      <!-- 路B：新建部件——输入名兼作新类型名与槽名 -->
      <template v-else>
        <el-form-item label="新部件名称" required>
          <el-input v-model="slotDialog.form.name" placeholder="新零件名，如 顶杆（编码自动生成）" />
        </el-form-item>
        <el-alert
          type="info" :closable="false" style="margin-bottom: 14px"
          title="将新建一个部件类型并挂到当前部件下；建好后可在左栏选中它，继续给它加属性、拆下一级部件（递归）。"
        />
      </template>

      <el-form-item label="必配">
        <el-switch v-model="slotDialog.form.is_required" :disabled="slotDialog.variantMode !== 'none'" />
        <span v-if="slotDialog.variantMode !== 'none'" style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">归组后由选择组接管（恰好选一种）</span>
      </el-form-item>
      <el-form-item label="允许成品件">
        <el-switch v-model="slotDialog.form.allow_blackbox" />
        <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">可整件外购、不再往下拆</span>
      </el-form-item>

      <!-- N选1 三态控件 -->
      <el-form-item label="这个位置是">
        <el-radio-group v-model="slotDialog.variantMode" @change="onSlotVariantMode">
          <el-radio-button value="none">普通位置</el-radio-button>
          <el-radio-button value="existing" :disabled="!existingGroups.length">加入已有组</el-radio-button>
          <el-radio-button value="new">新建选择组</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="slotDialog.variantMode === 'existing'" label="选择组">
        <el-select v-model="slotDialog.form.variant_group" style="width: 100%" placeholder="加入哪个 N选1 组">
          <el-option
            v-for="g in existingGroups" :key="g.group" :value="g.group"
            :label="`${g.group}（${g.members.join('、')}）`"
          />
        </el-select>
      </el-form-item>
      <el-form-item v-else-if="slotDialog.variantMode === 'new'" label="新组名">
        <el-input v-model="slotDialog.form.variant_group" placeholder="业务名，如 阀门型号" />
      </el-form-item>
      <el-alert
        v-if="slotDialog.variantMode === 'new'" type="info" :closable="false" style="margin-bottom: 4px"
        title="N选1 至少需 2 款：本槽是第 1 款，记得再给本位置添加其他款式槽。"
      />
      <el-alert
        v-else-if="slotDialog.variantMode === 'existing'" type="info" :closable="false" style="margin-bottom: 4px"
        title="同组「恰好选一种」，单槽必配由选择组统一判定。"
      />
    </el-form>
    <template #footer>
      <el-button @click="slotDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createSlot">创建</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
/* 节点列表过长 → 框内滚动（搜索/计数/说明常驻，列表区独立滚动） */
.type-list {
  max-height: calc(100vh - 300px);
  overflow-y: auto;
  overscroll-behavior: contain;
  margin: 0 -4px;
  padding: 0 4px;
}
.type-item {
  padding: 7px 8px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 2px;
}
.type-item:hover { background: var(--el-fill-color-light); }
.type-item.active { background: var(--el-color-primary-light-9); }
.type-item.inactive { opacity: 0.5; }
.type-item.dragging { opacity: 0.4; border: 1px dashed var(--el-color-primary); }
.type-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.drag-handle {
  cursor: grab;
  color: var(--el-text-color-placeholder);
  user-select: none;
  flex-shrink: 0;
}
.ti-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badges { display: flex; gap: 3px; align-items: center; flex-shrink: 0; }
.orphan { font-size: 11px; color: var(--el-text-color-placeholder); }
.side-group {
  font-weight: 500;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 10px 0 2px;
}
.side-group .gcnt { color: var(--el-text-color-placeholder); }
.spine-card { background: var(--el-fill-color-lighter); margin-bottom: 14px; }
.spine-crumb { margin-bottom: 8px; font-size: 12px; }
.crumb-link { cursor: pointer; color: var(--el-color-primary); }
.spine-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; padding: 3px 0; }
.spine-self { padding: 5px 0; }
.spine-label {
  display: inline-flex; align-items: center; gap: 2px; width: 52px; flex-shrink: 0;
  font-size: 12px; color: var(--el-text-color-secondary);
}
.spine-none { font-size: 12px; color: var(--el-text-color-placeholder); }
.chip { cursor: pointer; }
.chip-kind { margin-left: 4px; opacity: 0.8; }
.chip-arrow { vertical-align: -2px; margin-left: 2px; }
.spine-foot { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 8px; line-height: 1.5; }
</style>
