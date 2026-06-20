<script setup lang="ts">
/** SKU 库（货架，默认首页）：统计带 + 品类树 + 卡片/表格双视图 + 详情抽屉。
 *  P1：统计与计数走聚合端点，检索复用 /skus，零数据层改动。 */
import { CopyDocument, EditPen, Goods, Grid, List, Operation, Right, Search, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import BomTreeNode from '../components/BomTreeNode.vue'
import PriceTrendChart from '../components/PriceTrendChart.vue'
import SkuFilterPanel from '../components/SkuFilterPanel.vue'
import SkuSortBar from '../components/SkuSortBar.vue'
import StructuredSearchDrawer from '../components/StructuredSearchDrawer.vue'
import StatCard from '../components/StatCard.vue'
import { resolveFacets, SOURCING_OPTIONS } from '../constants/facets'
import { useAuthStore } from '../stores/auth'
import { usePreferencesStore } from '../stores/preferences'
import { useQuoteCartStore } from '../stores/quoteCart'

const auth = useAuthStore()
const pref = usePreferencesStore()
const cart = useQuoteCartStore()
const router = useRouter()
const route = useRoute()

// 移动端适配：≤768px 强制卡片视图（隐藏 1100px+ 宽表格）、品类树面板可折叠，消除横向溢出
const isMobile = ref(false)
const mobileFilterOpen = ref(false)
let mq: MediaQueryList | null = null
const onMqChange = (e: MediaQueryListEvent) => { isMobile.value = e.matches }
onMounted(() => {
  mq = window.matchMedia('(max-width: 768px)')
  isMobile.value = mq.matches
  mq.addEventListener('change', onMqChange)
})
onUnmounted(() => { mq?.removeEventListener('change', onMqChange) })

const filters = reactive({
  q: '', root_type_id: null as number | null, status: null as string | null,
  option_id: [] as number[], purchased_part_id: null as number | null,
  supplier_id: null as number | null, mine: false,
  supplier_part_type_id: null as number | null,  // 供应商×件类型下钻（仅配合 supplier_id）
  // 结构化检索·多对来源："该件类型由该供应商供应"，可任意多对并立，各自 AND（→ /skus sp_pair[]）
  supplier_pairs: [] as Array<{ supplier_id: number; node_type_id: number }>,
  sourcing: [] as string[], price_min: null as number | null,
  price_max: null as number | null, quotable: false,
})
const supplierPartTypeName = ref('')  // 件类型 chip 展示名（点击下钻时带入）
const stats = ref({ active: 0, pending_price: 0, new_this_week: 0, stale_30d: 0, incomplete: 0 })
const suppliers = ref<any[]>([])
const tree = ref<{ products: any[]; parts: any[] }>({ products: [], parts: [] })
const allTypes = ref<any[]>([])  // 全量 node-types（含非根子部件），供 sp_pair chip 件类型名解析
const filterAttrs = ref<any[]>([])
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
let ready = false  // 首屏注水期间抑制各筛选 watcher 重复 load / 回写 URL
let applyingBatch = false  // 结构化检索批量套用期间抑制各 watcher（避免清 option_id / 重复 load）
const structuredSearchVisible = ref(false)  // 「按配置找货」抽屉
// 视图与每页条数取自 per-user 偏好（通用设置可改）；computed 自动跟随偏好注水，切换即存偏好
const viewMode = computed<'card' | 'table'>({
  get: () => pref.view,
  set: (v) => pref.set({ default_view: v }),
})
// 排序 / 币种：会话态本地真源，初值取 URL ?? 偏好；用户改动既驱动当前结果又持久化为默认。
// 偏好异步注水时若用户未在 URL 指定且未手改，则跟随注水回填（touched 闸防覆盖用户选择）。
const sort = ref<string>((route.query.sort as string) || pref.sort)
const currency = ref<string>((route.query.ccy as string) || pref.currency)
let sortTouched = !!route.query.sort
let ccyTouched = !!route.query.ccy
watch(() => pref.sort, (v) => { if (!sortTouched) sort.value = v })
watch(() => pref.currency, (v) => { if (!ccyTouched) currency.value = v })
function onSort(v: string) { sortTouched = true; sort.value = v; pref.set({ default_sort: v }) }
function onCurrency(v: string) { ccyTouched = true; currency.value = v; pref.set({ default_currency: v }) }
// 分面顺序/显隐：合并出厂默认与 per-user 偏好（通用设置可拖拽配置）
const facets = computed(() => resolveFacets(pref.productFacets))

// 结构化检索带入的选项标签（含嵌套部件属性，filterAttrs 里没有，故单独缓存供 chip 显示）
const structuredOptLabels = ref<Record<number, string>>({})
// ---- 生效筛选 chips（可逐个移除 / 清空），与左栏分面、SortBar 三处同一真源 ----
function optionLabel(oid: number): string {
  if (structuredOptLabels.value[oid]) return structuredOptLabels.value[oid]
  for (const a of filterAttrs.value) {
    const o = a.options?.find((x: any) => x.id === oid)
    if (o) return `${a.name}: ${o.label}`
  }
  return `规格 #${oid}`
}
/** sp_pair chip 文案："件类型 ← 供应商"；名称从全量 node-types/suppliers 反查（URL 回灌也能解析）。 */
function pairLabel(p: { supplier_id: number; node_type_id: number }): string {
  const pt = allTypes.value.find((t) => t.id === p.node_type_id)?.name ?? `件类型#${p.node_type_id}`
  const sp = suppliers.value.find((s) => s.id === p.supplier_id)?.name ?? `#${p.supplier_id}`
  return `${pt} ← ${sp}`
}
const activeChips = computed(() => {
  const c: { key: string; text: string }[] = []
  if (filters.q) c.push({ key: 'q', text: `搜索：${filters.q}` })
  if (filters.root_type_id) {
    const name = [...tree.value.products, ...tree.value.parts]
      .find((t) => t.id === filters.root_type_id)?.name
    c.push({ key: 'cat', text: `品类：${name ?? filters.root_type_id}` })
  }
  const statusText: Record<string, string> = {
    pending_price: '待录价', incomplete: '待治理', active: '在售', retired: '已作废',
  }
  if (filters.status) c.push({ key: 'status', text: statusText[filters.status] ?? filters.status })
  if (filters.mine) c.push({ key: 'mine', text: '我创建的' })
  if (filters.supplier_id) {
    const name = suppliers.value.find((s) => s.id === filters.supplier_id)?.name
    c.push({ key: 'supplier', text: `供应商：${name ?? filters.supplier_id}` })
  }
  if (filters.supplier_part_type_id) {
    c.push({ key: 'supplier_part', text: `件类型：${supplierPartTypeName.value || filters.supplier_part_type_id}` })
  }
  for (const p of filters.supplier_pairs) {
    c.push({ key: `sp:${p.supplier_id}:${p.node_type_id}`, text: pairLabel(p) })
  }
  for (const s of filters.sourcing) {
    c.push({ key: `sourcing:${s}`, text: SOURCING_OPTIONS.find((o) => o.value === s)?.label ?? s })
  }
  if (filters.quotable) c.push({ key: 'quotable', text: '仅可报价' })
  if (filters.price_min != null || filters.price_max != null) {
    const lo = filters.price_min ?? ''
    const hi = filters.price_max ?? ''
    c.push({ key: 'price', text: `价格 ${lo}~${hi} ${currency.value}` })
  }
  for (const oid of filters.option_id) c.push({ key: `opt:${oid}`, text: optionLabel(oid) })
  return c
})
function removeChip(key: string) {
  if (key === 'q') filters.q = ''
  else if (key === 'cat') filters.root_type_id = null
  else if (key === 'status') filters.status = null
  else if (key === 'mine') filters.mine = false
  else if (key === 'supplier') { filters.supplier_id = null; filters.supplier_part_type_id = null }
  else if (key === 'supplier_part') filters.supplier_part_type_id = null
  else if (key === 'quotable') filters.quotable = false
  else if (key === 'price') { filters.price_min = null; filters.price_max = null }
  else if (key.startsWith('sourcing:')) {
    filters.sourcing = filters.sourcing.filter((s) => s !== key.slice(9))
  } else if (key.startsWith('sp:')) {
    const [, sid, ntid] = key.split(':')
    filters.supplier_pairs = filters.supplier_pairs.filter(
      (p) => !(p.supplier_id === Number(sid) && p.node_type_id === Number(ntid)))
  } else if (key.startsWith('opt:')) {
    filters.option_id = filters.option_id.filter((o) => o !== Number(key.slice(4)))
  }
}
function clearAllFilters() {
  filters.q = ''
  filters.root_type_id = null
  filters.status = null
  filters.supplier_id = null
  filters.supplier_part_type_id = null
  filters.mine = false
  filters.quotable = false
  filters.price_min = null
  filters.price_max = null
  filters.sourcing = []
  filters.option_id = []
  filters.supplier_pairs = []
}

const activeQuick = computed(() => {
  if (filters.mine) return 'mine'
  if (filters.status === 'pending_price') return 'pending'
  if (filters.status === 'incomplete') return 'incomplete'
  if (!filters.root_type_id && !filters.supplier_id && !filters.status && !filters.q
      && !filters.option_id.length) return 'all'
  return ''
})

/** 健康徽标：incomplete=红(待治理)，supply_warn=黄(含停用件)，ok/未知=无。 */
function healthTag(s: any): { type: 'danger' | 'warning'; text: string } | null {
  if (s.health_status === 'incomplete') return { type: 'danger', text: '待治理' }
  if (s.health_status === 'supply_warn') return { type: 'warning', text: '含停用件' }
  return null
}

/** 加入报价单禁用原因（null=可加入）。完整性优先于待录价，黄色 supply 不拦。 */
function addDisabledReason(s: any): string | null {
  if (!s) return null
  if (s.status !== 'active') return '已作废 SKU 不可报价'
  if (s.health_status === 'incomplete') return '配置不完整（缺必选项/必配部件或违反互斥组），需先治理后才能报价'
  if (!s.current_prices?.length) return '待录价，录入现价后才能加入报价单'
  return null
}

/** 货架展示序：在售优先，已作废(非 active)灰显并沉到末尾。
 *  纯前端视觉排序——sort 稳定，同组内保留服务端原序，绝不改动任何数据。 */
const displayRows = computed(() =>
  [...rows.value].sort((a, b) =>
    (a.status === 'active' ? 0 : 1) - (b.status === 'active' ? 0 : 1)))

const drawer = reactive({ visible: false, sku: null as any, prices: [] as any[] })
const bomCollapsed = reactive(new Set<string>())  // 产品构成树折叠态（节点路径）

async function loadStats() {
  try {
    stats.value = (await api.get('/skus/stats')).data
  } catch { /* 401 由拦截器处理 */ }
}

async function loadTree() {
  const { data } = await api.get('/template/node-types', { params: { with_counts: true } })
  allTypes.value = data
  tree.value = {
    products: data.filter((t: any) => t.kind === 'product' && t.is_sellable_root),
    parts: data.filter((t: any) => t.kind === 'part' && t.is_sellable_root),
  }
}

async function loadSuppliers() {
  // overview 带 linked_skus 计数：供「按供应商」视角的一级树显示关联在售 SKU 数
  try { suppliers.value = (await api.get('/suppliers/overview')).data } catch { /* 忽略 */ }
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/skus', {
      params: {
        q: filters.q || undefined,
        root_type_id: filters.root_type_id ?? undefined,
        status: filters.status ?? undefined,
        option_id: filters.option_id.length ? filters.option_id : undefined,
        purchased_part_id: filters.purchased_part_id ?? undefined,
        supplier_id: filters.supplier_id ?? undefined,
        supplier_part_type_id: filters.supplier_part_type_id ?? undefined,
        sp_pair: filters.supplier_pairs.length
          ? filters.supplier_pairs.map((p) => `${p.supplier_id}:${p.node_type_id}`) : undefined,
        mine: filters.mine || undefined,
        sourcing: filters.sourcing.length ? filters.sourcing : undefined,
        price_min: filters.price_min ?? undefined,
        price_max: filters.price_max ?? undefined,
        quotable: filters.quotable || undefined,
        sort: sort.value, currency: currency.value,
        page: page.value, page_size: pref.pageSize,
      },
      paramsSerializer: { indexes: null },
    })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

/** 把当前检索态序列化进 URL（仅写非默认值，保持链接简洁、可分享、可回退）。 */
function buildQuery(): Record<string, string> {
  const q: Record<string, string> = {}
  if (filters.q) q.q = filters.q
  if (filters.root_type_id) q.cat = String(filters.root_type_id)
  if (filters.status) q.status = filters.status
  if (filters.supplier_id) q.supplier = String(filters.supplier_id)
  if (filters.supplier_part_type_id) q.sptype = String(filters.supplier_part_type_id)
  if (filters.supplier_pairs.length) {
    q.sp = filters.supplier_pairs.map((p) => `${p.supplier_id}:${p.node_type_id}`).join(',')
  }
  if (filters.mine) q.mine = '1'
  if (filters.quotable) q.quotable = '1'
  if (filters.price_min != null) q.pmin = String(filters.price_min)
  if (filters.price_max != null) q.pmax = String(filters.price_max)
  if (filters.sourcing.length) q.sourcing = filters.sourcing.join(',')
  if (filters.option_id.length) q.opt = filters.option_id.join(',')
  if (sort.value !== 'recent') q.sort = sort.value
  if (currency.value !== 'USD') q.ccy = currency.value
  if (page.value > 1) q.page = String(page.value)
  return q
}

/** 首屏从 URL 注水筛选态（在 watcher 启用前调用，故不会触发重复 load）。 */
function readUrlIntoFilters() {
  const qd = route.query
  filters.q = (qd.q as string) || ''
  filters.root_type_id = qd.cat ? Number(qd.cat) : null
  filters.status = (qd.status as string) || null
  filters.supplier_id = qd.supplier ? Number(qd.supplier) : null
  filters.supplier_part_type_id = qd.sptype ? Number(qd.sptype) : null
  filters.supplier_pairs = qd.sp
    ? String(qd.sp).split(',').map((s) => {
      const [a, b] = s.split(':')
      return { supplier_id: Number(a), node_type_id: Number(b) }
    }).filter((p) => !Number.isNaN(p.supplier_id) && !Number.isNaN(p.node_type_id) && p.supplier_id && p.node_type_id)
    : []
  filters.mine = qd.mine === '1'
  filters.quotable = qd.quotable === '1'
  filters.price_min = qd.pmin != null ? Number(qd.pmin) : null
  filters.price_max = qd.pmax != null ? Number(qd.pmax) : null
  filters.sourcing = qd.sourcing ? String(qd.sourcing).split(',').filter(Boolean) : []
  filters.option_id = qd.opt
    ? String(qd.opt).split(',').map(Number).filter((n) => !Number.isNaN(n)) : []
  if (qd.page) page.value = Number(qd.page) || 1
}

async function loadFilterAttrs(id: number | null) {
  filterAttrs.value = []
  if (id) {
    const { data } = await api.get(`/template/node-types/${id}`)
    filterAttrs.value = data.attributes.filter((a: any) => a.is_filterable && a.is_active)
  }
}

onMounted(async () => {
  readUrlIntoFilters()  // 先从 URL 注水（此时 ready=false，下方 watcher 不会重复触发 load）
  try {
    await Promise.all([loadStats(), loadTree(), loadSuppliers(), loadOverview()])
    if (filters.root_type_id) await loadFilterAttrs(filters.root_type_id)
    await load()
    if (route.query.sku_id) await openDetailById(Number(route.query.sku_id))
  } catch { /* 401 由拦截器跳转登录 */ }
  ready = true
})

watch(() => filters.root_type_id, async (id) => {
  if (!ready || applyingBatch) return
  filters.option_id = []
  await loadFilterAttrs(id)
  page.value = 1
  await load()
})
watch([() => filters.q, () => filters.status, () => filters.option_id, () => filters.mine,
       () => filters.supplier_id, () => filters.supplier_part_type_id, () => filters.supplier_pairs,
       () => filters.sourcing,
       () => filters.quotable, () => filters.price_min, () => filters.price_max], () => {
  if (!ready || applyingBatch) return
  page.value = 1
  void load()
}, { deep: true })
watch([sort, currency], () => { if (!ready || applyingBatch) return; page.value = 1; void load() })
watch(page, () => { if (ready && !applyingBatch) void load() })
watch(() => pref.pageSize, () => { if (!ready) return; page.value = 1; void load() })
// 检索态回写 URL（可分享/可回退）；首屏注水期不写
watch([filters, sort, currency, page], () => {
  if (!ready || applyingBatch) return
  void router.replace({ query: buildQuery() }).catch(() => {})
}, { deep: true })

// 结构化检索：批量套用查询(复用现有 filter 字段，chips/load/URL 自动生效)。
// applyingBatch 抑制各 watcher 期间手动 loadFilterAttrs + 单次 load + 回写 URL，避免清 option_id/多次 load。
async function applyStructuredQuery(q: any) {
  applyingBatch = true
  filters.mine = false
  filters.status = null
  filters.sourcing = []
  filters.price_min = null
  filters.price_max = null
  filters.quotable = false
  filters.q = ''
  filters.root_type_id = q.root_type_id ?? null
  filters.option_id = (q.option_id ?? []).slice()
  // 结构化检索走多对来源 sp_pair，清空"按供应商视角下钻"的单来源字段，避免双重约束
  filters.supplier_id = null
  filters.supplier_part_type_id = null
  supplierPartTypeName.value = ''
  filters.supplier_pairs = (q.supplier_pairs ?? []).map(
    (p: any) => ({ supplier_id: p.supplier_id, node_type_id: p.node_type_id }))
  structuredOptLabels.value = q.opt_labels ?? {}
  await loadFilterAttrs(filters.root_type_id)
  page.value = 1
  applyingBatch = false
  await load()
  void router.replace({ query: buildQuery() }).catch(() => {})
}

// ---- 快捷视图 / 品类树 ----
function selectQuick(kind: 'all' | 'pending' | 'mine' | 'incomplete') {
  filters.q = ''
  filters.option_id = []
  filters.root_type_id = null
  filters.supplier_id = null
  filters.supplier_part_type_id = null
  supplierPartTypeName.value = ''
  filters.supplier_pairs = []
  filters.sourcing = []
  filters.price_min = null
  filters.price_max = null
  filters.quotable = false
  filterAttrs.value = []
  filters.status = kind === 'pending' ? 'pending_price' : kind === 'incomplete' ? 'incomplete' : null
  filters.mine = kind === 'mine'
}
function selectCategory(id: number) {
  // 按品类视角：纯品类筛选（清供应商维度），再点同品类取消
  filters.mine = false
  filters.status = null
  filters.supplier_id = null
  filters.supplier_part_type_id = null
  supplierPartTypeName.value = ''
  filters.supplier_pairs = []
  filters.root_type_id = filters.root_type_id === id ? null : id
}
// 按供应商视角=在售供应关系：点供应商=纯供应商筛选（清品类/件类型维度）；再点同供应商取消。
// 强制在售口径(status=active)，使列表 total 与供应商节点的 linked_skus(在售) 计数对齐。
function selectSupplier(id: number) {
  filters.mine = false
  filters.root_type_id = null
  const same = filters.supplier_id === id && filters.supplier_part_type_id == null
  filters.supplier_part_type_id = null
  supplierPartTypeName.value = ''
  filters.supplier_pairs = []
  filters.supplier_id = same ? null : id
  filters.status = same ? null : 'active'
}
// 供应商下钻件类型：供应商×件类型双维（仅命中"该件类型本身由该供应商供应"的在售 SKU），
// 在售口径使 total 与「件目录」计数对齐（你要的"对上"）。
function selectSupplierCategory(p: { supplierId: number; partTypeId: number; partTypeName: string }) {
  filters.mine = false
  filters.root_type_id = null
  filters.supplier_pairs = []
  filters.supplier_id = p.supplierId
  filters.supplier_part_type_id = p.partTypeId
  supplierPartTypeName.value = p.partTypeName
  filters.status = 'active'
}

async function openDetailById(id: number) {
  const { data } = await api.get(`/skus/${id}`)
  drawer.sku = data
  drawer.prices = (await api.get(`/skus/${id}/prices`)).data
  bomCollapsed.clear()  // 每次打开默认全展开
  drawer.visible = true
}

// ---- SKU 详情页（重设计）派生与工具 ----
const isDirectAssembly = computed(() => drawer.sku?.config_tree?.mode === 'purchased')

function priceVal(s: any) { return s?.current_prices?.[0]?.price ?? null }
function priceCur(s: any) { return s?.current_prices?.[0]?.currency ?? '' }

/** 「可否报价」结论：复用 addDisabledReason 同一判定，杜绝与按钮禁用态打架。 */
const quotableVerdict = computed<{ label: string; tone: any; alert: boolean }>(() => {
  const s = drawer.sku
  if (!s) return { label: '', tone: 'default', alert: false }
  const reason = addDisabledReason(s)
  if (reason) {
    if (s.status !== 'active') return { label: '已作废', tone: 'info', alert: false }
    if (s.health_status === 'incomplete') return { label: '不可报价', tone: 'danger', alert: true }
    return { label: '待录价', tone: 'warning', alert: true }
  }
  if (s.health_status === 'supply_warn') return { label: '可报价 · 有风险', tone: 'warning', alert: true }
  return { label: '可报价', tone: 'success', alert: false }
})

function countBom(node: any, acc: { total: number; white: number; black: number }) {
  acc.total++
  if (node.mode === 'purchased') acc.black++; else acc.white++
  for (const c of node.children ?? []) countBom(c, acc)
  return acc
}
const bomStats = computed(() =>
  drawer.sku?.config_tree
    ? countBom(drawer.sku.config_tree, { total: 0, white: 0, black: 0 })
    : { total: 0, white: 0, black: 0 })

function collectBomParents(node: any, path: string, acc: string[]) {
  if (node.children && node.children.length) {
    acc.push(path)
    node.children.forEach((c: any, i: number) => collectBomParents(c, `${path}-${i}`, acc))
  }
  return acc
}
function expandAllBom() { bomCollapsed.clear() }
function collapseAllBom() {
  bomCollapsed.clear()
  if (drawer.sku?.config_tree) collectBomParents(drawer.sku.config_tree, '0', []).forEach((p) => bomCollapsed.add(p))
}
async function copyBomText() {
  if (!drawer.sku?.config_tree) return
  try {
    await navigator.clipboard.writeText(renderTreeText(drawer.sku.config_tree).join('\n'))
    ElMessage.success('已复制构成文本')
  } catch { ElMessage.warning('复制失败，请手动选择') }
}
async function copyCode() {
  if (!drawer.sku?.sku_code) return
  try { await navigator.clipboard.writeText(drawer.sku.sku_code); ElMessage.success('已复制 SKU 编码') } catch { /* 忽略 */ }
}
function goSku(id?: number) { if (id) openDetailById(id) }
const bomSection = ref<HTMLElement | null>(null)
function scrollToBom() { bomSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }

async function addToQuote(sku: any) {
  const r = await cart.addSku(sku.id, 1)
  if (r.ok) {
    if (r.warnings?.length) {
      ElMessage({ type: 'warning', duration: 6000,
        message: `已加入，但请注意：${r.warnings.join('；')}` })
    } else ElMessage.success('已加入当前报价单')
  } else if (r.code === 'INCOMPLETE_SKU') {
    // 后端硬闸兜底（正常情况下按钮已禁用，理论不可达）
    ElMessage({ type: 'error', duration: 6000, message: r.message || '该 SKU 配置不完整，已被拦截' })
  } else if (r.message === 'NO_ACTIVE') {
    ElMessage.warning('请先到「报价单」页新建/选择草稿单')
    router.push('/quotations')
  } else ElMessage.error(r.message!)
}

// 录价对话框（方案 A）：产品全貌卡片 + 图片位 + 完整表单（价/币种/生效日/备注）
const priceDialog = reactive({
  visible: false, sku: null as any, submitting: false,
  form: { price: '', currency: 'USD', valid_from: '', note: '' },
})
async function openPriceDialog(sku: any) {
  // 从卡片/表格直接改价时列表项无 config_tree，补一次详情用于全貌展示
  if (!sku.config_tree) {
    try { sku = (await api.get(`/skus/${sku.id}`)).data } catch { /* 用列表项兜底 */ }
  }
  priceDialog.sku = sku
  priceDialog.form = {
    price: '', currency: sku.current_prices?.[0]?.currency || 'USD', valid_from: '', note: '',
  }
  priceDialog.visible = true
}
async function submitPrice() {
  if (!/^\d+(\.\d{1,4})?$/.test(priceDialog.form.price)) {
    ElMessage.warning('请输入合法金额（最多 4 位小数）')
    return
  }
  priceDialog.submitting = true
  try {
    await api.post(`/skus/${priceDialog.sku.id}/prices`, {
      price: priceDialog.form.price,
      currency: priceDialog.form.currency,
      valid_from: priceDialog.form.valid_from || undefined,
      note: priceDialog.form.note || undefined,
    })
    ElMessage.success('价格已生效')
    priceDialog.visible = false
    await Promise.all([load(), loadStats()])
    if (drawer.visible && drawer.sku?.id === priceDialog.sku.id) await openDetailById(priceDialog.sku.id)
  } catch { /* 拦截器已提示 */ } finally {
    priceDialog.submitting = false
  }
}

function exportList() {
  const token = localStorage.getItem('access_token')
  fetch(`/api/v1/skus/export${filters.root_type_id ? `?root_type_id=${filters.root_type_id}` : ''}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(async (r) => {
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'SKU清单.xlsx'
    a.click()
    URL.revokeObjectURL(url)
  })
}

function priceText(s: any) {
  if (!s.current_prices?.length) return null
  // 优先展示所选币种现价，与排序/筛选币种一致（否则同列会混入他币现价、视觉错序）；
  // 该 SKU 无此币种价时回落到首条，仍优于显示"待录价"
  const p = s.current_prices.find((x: any) => x.currency === currency.value) ?? s.current_prices[0]
  return `${p.currency} ${p.price}`
}

function renderTreeText(node: any, depth = 0): string[] {
  const pad = '　'.repeat(depth)
  const lines: string[] = []
  const head = node.slot_name ? `${node.slot_name}：` : ''
  if (node.mode === 'purchased') {
    let line = `${pad}${head}【成品】${node.supplier_name} | ${node.purchased_part_name}`
    const spec = [node.part_spec_summary, node.part_spec_note].filter(Boolean).join('；')
    if (spec) line += `（规格：${spec}）`  // 灰盒渐进披露：黑盒件已补录的规格
    lines.push(line)
  } else {
    const attrs = (node.attributes ?? [])
      .map((a: any) => `${a.attribute_name}=${a.option_label}${a.option_active ? '' : '（选项已停用）'}`)
      .join('，')
    lines.push(`${pad}${head}${node.node_type_name}${attrs ? `（${attrs}）` : ''}`)
    for (const c of node.children ?? []) lines.push(...renderTreeText(c, depth + 1))
  }
  return lines
}

// 来源地图：把配置树按构成顺序(DFS)摊成 部件→供应商 两列行；未标注=白盒自配/未指定来源。
// 不分黑白盒组，顺序与产品构成一致（同一棵树的同序遍历）。
function sourcingRows(tree: any): { label: string; supplier: string | null }[] {
  const rows: { label: string; supplier: string | null }[] = []
  function walk(node: any, isRoot: boolean) {
    if (!isRoot) {
      rows.push({ label: node.slot_name || node.node_type_name, supplier: node.supplier_name ?? null })
    } else if (node.supplier_name) {
      rows.push({ label: `${node.node_type_name}（整机）`, supplier: node.supplier_name })
    }
    for (const c of node.children ?? []) walk(c, false)
  }
  walk(tree, true)
  return rows
}
const sourcingFlat = computed(() =>
  drawer.sku?.config_tree ? sourcingRows(drawer.sku.config_tree) : [])

// ---- 产品库首页视图：货架(默认·业务员日常主场) / 产品全貌(可切视角·偏好持久化) ----
const homeView = ref<'shelf' | 'overview'>(
  (localStorage.getItem('home_view') as 'shelf' | 'overview') || 'shelf',
)
watch(homeView, (v) => localStorage.setItem('home_view', v))
const overview = ref<any[]>([])
async function loadOverview() {
  try { overview.value = (await api.get('/skus/overview')).data } catch { /* 401 由拦截器处理 */ }
}
const ovProducts = computed(() => overview.value.filter((t) => t.kind === 'product'))
const ovParts = computed(() => overview.value.filter((t) => t.kind === 'part'))
const ovStats = computed(() => ({
  types: overview.value.filter((t) => t.sku_count > 0).length,
  skus: overview.value.reduce((a, t) => a + t.sku_count, 0),
  pending: overview.value.reduce((a, t) => a + t.pending_price, 0),
  incomplete: overview.value.reduce((a, t) => a + t.incomplete, 0),
}))
function openCategory(rt: any) {
  filters.mine = false
  filters.status = null
  filters.root_type_id = rt.root_type_id
  homeView.value = 'shelf'
}
function priceRange(t: any): string | null {
  if (t.price_min == null) return null
  const c = t.currency || ''
  return t.price_min === t.price_max ? `${c} ${t.price_min}` : `${c} ${t.price_min}~${t.price_max}`
}
</script>

<template>
  <!-- 产品库视图切换：货架(默认·日常主场) / 产品全貌(可切视角) -->
  <div class="home-toggle">
    <el-radio-group v-model="homeView">
      <el-radio-button value="shelf"><el-icon><List /></el-icon> SKU 货架</el-radio-button>
      <el-radio-button value="overview"><el-icon><Grid /></el-icon> 产品全貌</el-radio-button>
    </el-radio-group>
    <span style="flex: 1"></span>
    <el-button type="primary" @click="router.push('/configure')">+ 新配置</el-button>
  </div>

  <template v-if="homeView === 'shelf'">
  <!-- 统计带 -->
  <div class="stat-band">
    <StatCard label="在售 SKU" :value="stats.active" />
    <StatCard
      label="待录价" :value="stats.pending_price" clickable @click="selectQuick('pending')"
      :tone="stats.pending_price > 0 ? 'warning' : 'default'" :alert="stats.pending_price > 0"
    />
    <StatCard label="近 7 天新增" :value="stats.new_this_week" />
    <StatCard label="30 天未调价" :value="stats.stale_30d" />
    <StatCard
      label="待治理" :value="stats.incomplete" clickable @click="selectQuick('incomplete')"
      :tone="stats.incomplete > 0 ? 'danger' : 'default'" :alert="stats.incomplete > 0"
    />
  </div>

  <el-row :gutter="12">
    <!-- 左栏：分面检索面板（快捷视图 + 品类树 + 可自定义分面） -->
    <el-col :span="6" :xs="24">
      <el-button
        v-if="isMobile" text class="mobile-filter-toggle"
        @click="mobileFilterOpen = !mobileFilterOpen"
      >{{ mobileFilterOpen ? '收起筛选 ▲' : '筛选 / 品类树 ▼' }}</el-button>
      <SkuFilterPanel
        v-show="!isMobile || mobileFilterOpen"
        :filters="filters" :stats="stats" :tree="tree" :suppliers="suppliers"
        :filter-attrs="filterAttrs" :facets="facets" :active-quick="activeQuick" :currency="currency"
        @quick="selectQuick" @category="selectCategory"
        @supplier="selectSupplier" @supplier-category="selectSupplierCategory"
        @open-settings="router.push('/settings/general')"
      />
    </el-col>

    <!-- 主区 -->
    <el-col :span="18" :xs="24">
      <el-card>
        <div class="main-tools">
          <el-input v-model="filters.q" placeholder="SKU 编码 / 名称" clearable class="tools-search">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <span class="tools-spacer"></span>
          <el-tooltip content="显示设置（分面 / 默认视图 / 每页）" placement="top">
            <el-button :icon="Setting" @click="router.push('/settings/general')" />
          </el-tooltip>
          <el-button :icon="Operation" @click="structuredSearchVisible = true">按配置找货</el-button>
          <el-button @click="exportList">导出 Excel</el-button>
          <el-button type="primary" @click="router.push('/configure')">+ 新配置</el-button>
        </div>

        <StructuredSearchDrawer
          v-model="structuredSearchVisible" :products="tree.products" :suppliers="suppliers"
          @apply="applyStructuredQuery"
        />

        <SkuSortBar
          :total="total" :sort="sort" :currency="currency" :view="viewMode" :chips="activeChips"
          @update:sort="onSort" @update:currency="onCurrency" @update:view="(v) => viewMode = v"
          @remove="removeChip" @clear-all="clearAllFilters"
        />

        <!-- 卡片视图（手机强制卡片，隐藏 1100px+ 宽表格） -->
        <div v-if="isMobile || viewMode === 'card'" v-loading="loading">
          <div v-if="rows.length" class="card-grid">
            <el-card v-for="row in displayRows" :key="row.id" shadow="hover" body-style="padding: 10px"
                     class="sku-card" :class="{ retired: row.status !== 'active' }" @click="openDetailById(row.id)">
              <div class="sku-thumb"><el-icon :size="26"><Goods /></el-icon></div>
              <div class="sku-code">{{ row.sku_code }}</div>
              <div class="sku-name">{{ row.name }}</div>
              <div class="sku-foot">
                <b v-if="priceText(row)" class="price">{{ priceText(row) }}</b>
                <el-tag v-else type="warning" size="small">待录价</el-tag>
                <el-tag v-if="row.status === 'retired'" type="info" size="small">已作废</el-tag>
                <el-tag v-if="healthTag(row)" :type="healthTag(row)!.type" size="small" effect="dark">
                  {{ healthTag(row)!.text }}
                </el-tag>
              </div>
              <div class="sku-actions" @click.stop>
                <el-tooltip :disabled="!addDisabledReason(row)" :content="addDisabledReason(row) || ''" placement="top">
                  <span>
                    <el-button size="small" type="primary" :disabled="!!addDisabledReason(row)"
                               @click="addToQuote(row)">加入报价单</el-button>
                  </span>
                </el-tooltip>
                <el-button v-if="auth.canSetPrice" size="small" @click="openPriceDialog(row)">改价</el-button>
                <span style="flex: 1"></span>
                <el-tooltip
                  v-if="row.status === 'active' && !row.superseded_by_sku_id"
                  content="修改此 SKU 配置（生成新 SKU，原 SKU 停用或保活）" placement="top"
                >
                  <el-button size="small" text :icon="EditPen" aria-label="修改配置"
                             @click="router.push({ path: '/configure', query: { edit_sku_id: row.id } })" />
                </el-tooltip>
                <el-tooltip content="以此为模板复制配置一个新 SKU" placement="top">
                  <el-button size="small" text :icon="CopyDocument" aria-label="以此再配置"
                             @click="router.push({ path: '/configure', query: { sku_id: row.id } })" />
                </el-tooltip>
              </div>
            </el-card>
          </div>
          <el-empty v-else description="暂无 SKU" />
        </div>

        <!-- 表格视图 -->
        <el-table v-else :data="displayRows" v-loading="loading"
                  :row-class-name="({ row }: any) => row.status !== 'active' ? 'row-retired' : ''"
                  @row-click="(r: any) => openDetailById(r.id)">
          <el-table-column prop="sku_code" label="SKU 编码" width="150" />
          <el-table-column prop="name" label="名称 / 规格摘要" min-width="260" />
          <el-table-column label="现价" width="120">
            <template #default="{ row }">
              <b v-if="priceText(row)" class="ph-num" style="color: var(--el-color-success)">{{ priceText(row) }}</b>
              <el-tag v-else type="warning" size="small">待录价</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                {{ row.status === 'active' ? '在售' : '已作废' }}
              </el-tag>
              <el-tag v-if="healthTag(row)" :type="healthTag(row)!.type" size="small" effect="dark"
                      style="margin-left: 4px">{{ healthTag(row)!.text }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="270">
            <template #default="{ row }">
              <div class="row-actions">
                <el-tooltip :disabled="!addDisabledReason(row)" :content="addDisabledReason(row) || ''" placement="top">
                  <span>
                    <el-button size="small" type="primary" :disabled="!!addDisabledReason(row)"
                               @click.stop="addToQuote(row)">加入报价单</el-button>
                  </span>
                </el-tooltip>
                <el-button v-if="auth.canSetPrice" size="small" @click.stop="openPriceDialog(row)">改价</el-button>
                <el-tooltip
                  v-if="row.status === 'active' && !row.superseded_by_sku_id"
                  content="修改此 SKU 配置（生成新 SKU，原 SKU 停用或保活）" placement="top"
                >
                  <el-button size="small" text :icon="EditPen" aria-label="修改配置"
                             @click.stop="router.push({ path: '/configure', query: { edit_sku_id: row.id } })" />
                </el-tooltip>
                <el-tooltip content="以此为模板复制配置一个新 SKU" placement="top">
                  <el-button size="small" text :icon="CopyDocument" aria-label="以此再配置"
                             @click.stop="router.push({ path: '/configure', query: { sku_id: row.id } })" />
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-model:current-page="page" :total="total" :page-size="pref.pageSize"
          layout="total, prev, pager, next" style="margin-top: 12px; justify-content: end"
        />
      </el-card>
    </el-col>
  </el-row>
  </template>

  <!-- 产品全貌：按品类聚合的卡片墙（比 SKU 粗一档）-->
  <template v-else>
    <div class="stat-band ov-band">
      <StatCard label="产品类型(有货)" :value="ovStats.types" />
      <StatCard label="SKU 总数" :value="ovStats.skus" />
      <StatCard label="待录价" :value="ovStats.pending" :tone="ovStats.pending > 0 ? 'warning' : 'default'" :alert="ovStats.pending > 0" />
      <StatCard label="待治理" :value="ovStats.incomplete" :tone="ovStats.incomplete > 0 ? 'danger' : 'default'" :alert="ovStats.incomplete > 0" />
    </div>

    <template v-for="grp in [
      { label: '整机', items: ovProducts },
      { label: '配件单卖', items: ovParts },
    ]" :key="grp.label">
      <div v-if="grp.items.length" class="ov-group">{{ grp.label }}</div>
      <div v-if="grp.items.length" class="ov-grid">
        <el-card v-for="t in grp.items" :key="t.root_type_id" shadow="hover"
                 class="ov-card" :class="{ empty: t.sku_count === 0 }"
                 body-style="padding: 14px 16px" @click="openCategory(t)">
          <div class="ov-name">{{ t.root_type_name }}</div>
          <div class="ov-count"><b>{{ t.sku_count }}</b><span>个 SKU</span></div>
          <div class="ov-badges">
            <el-tag v-if="!t.slot_count && !t.attr_count" type="info" size="small">待建模</el-tag>
            <el-tag v-if="t.incomplete" type="danger" size="small" effect="dark">待治理 {{ t.incomplete }}</el-tag>
            <el-tag v-if="t.pending_price" type="warning" size="small">待录价 {{ t.pending_price }}</el-tag>
            <span v-if="!t.incomplete && !t.pending_price && t.sku_count" class="ov-ok">健康</span>
          </div>
          <div class="ov-meta">
            <span v-if="priceRange(t)" class="ov-price ph-num">{{ priceRange(t) }}</span>
            <span v-else class="ov-noprice">{{ t.sku_count ? '待录价' : '暂无 SKU' }}</span>
          </div>
          <div class="ov-dims">
            <template v-if="t.slot_count || t.attr_count">选配维度 · {{ t.slot_count }} 部件槽 · {{ t.attr_count }} 属性轴</template>
            <span v-else class="ov-unmodeled">待建模 · 去「系统设置 · 产品模板」建属性与部件槽</span>
          </div>
        </el-card>
      </div>
    </template>
  </template>

  <el-drawer v-model="drawer.visible" size="560px" direction="rtl" class="sku-drawer">
    <template #header>
      <div class="sku-dh">
        <span class="dh-code">{{ drawer.sku?.sku_code }}
          <el-icon class="copy-code" @click="copyCode"><CopyDocument /></el-icon>
        </span>
        <el-tag v-if="drawer.sku" size="small" :type="drawer.sku.status === 'active' ? 'success' : 'info'">
          {{ drawer.sku.status === 'active' ? '在售' : '已作废' }}
        </el-tag>
      </div>
    </template>

    <template v-if="drawer.sku">
      <!-- 决策层（sticky 钉顶）：3 秒看懂 是什么货 / 多少钱 / 能不能卖 -->
      <div class="decide ph-fade">
        <div class="decide-name">
          {{ drawer.sku.name }}
          <el-tag size="small" effect="plain" :type="isDirectAssembly ? 'warning' : 'info'">
            {{ isDirectAssembly ? '整机直采' : '白盒配置' }}
          </el-tag>
          <el-tag
            v-if="drawer.sku.superseded_by_sku_code" size="small" type="info" effect="plain"
            class="link-tag" @click="goSku(drawer.sku.superseded_by_sku_id)"
          >已被 {{ drawer.sku.superseded_by_sku_code }} 取代</el-tag>
        </div>
        <div class="decide-kpis">
          <StatCard
            label="现价" :tone="priceVal(drawer.sku) ? 'success' : 'warning'" :alert="!priceVal(drawer.sku)"
            :value="priceVal(drawer.sku) ?? '待录价'" :unit="priceVal(drawer.sku) ? priceCur(drawer.sku) : ''"
          />
          <StatCard label="可否报价" :tone="quotableVerdict.tone" :alert="quotableVerdict.alert" :value="quotableVerdict.label" />
          <StatCard
            label="构成" clickable @click="scrollToBom"
            :value="isDirectAssembly ? '整机' : bomStats.total" :unit="isDirectAssembly ? '' : '项'"
            :hint="isDirectAssembly ? '' : `白盒${bomStats.white}·黑盒${bomStats.black}`"
          />
        </div>
        <el-alert
          v-if="drawer.sku.health && drawer.sku.health.status !== 'ok'"
          :type="drawer.sku.health.blocking ? 'error' : 'warning'"
          :closable="false" show-icon style="margin-top: 12px"
        >
          <template #title>
            {{ drawer.sku.health.blocking
              ? '配置不完整：不可加入报价单，需先治理'
              : '含停用 / 停产件：可报价，但请留意供货风险' }}
          </template>
          <ul class="health-issues">
            <li v-for="(it, i) in [
              ...drawer.sku.health.families.completeness,
              ...drawer.sku.health.families.structural,
              ...drawer.sku.health.families.supply,
            ]" :key="i">{{ it.message }}</li>
          </ul>
        </el-alert>
      </div>

      <!-- 区① 产品构成 · BOM 事实视图 -->
      <div ref="bomSection" class="pd-section">
        <div class="pd-section-head">
          <span>产品构成</span>
          <span class="sec-tools">
            <el-button text size="small" @click="expandAllBom">展开全部</el-button>
            <el-button text size="small" @click="collapseAllBom">收起全部</el-button>
            <el-button text size="small" :icon="CopyDocument" @click="copyBomText">复制构成</el-button>
          </span>
        </div>
        <div class="bom-box">
          <BomTreeNode v-if="drawer.sku.config_tree" :node="drawer.sku.config_tree" path="0" :collapsed="bomCollapsed" />
          <span v-else style="color: var(--el-text-color-secondary); font-size: 13px">—</span>
        </div>
      </div>

      <!-- 区② 来源地图：清晰两列式（部件 | 供应商），按产品构成顺序平铺、不分黑白盒组 -->
      <div class="pd-section">
        <div class="pd-section-head"><span>来源地图</span></div>
        <div class="src-box">
          <div v-for="(r, i) in sourcingFlat" :key="i" class="src-line">
            <span class="src-label">{{ r.label }}</span>
            <span v-if="r.supplier" class="src-sup">
              <el-icon class="src-arrow"><Right /></el-icon>{{ r.supplier }}
            </span>
            <span v-else class="src-nosrc">未标注</span>
          </div>
          <el-empty v-if="!sourcingFlat.length" :image-size="40" description="无外购来源" />
        </div>
        <p class="sec-note">按产品构成顺序逐部件列出采购来源；「未标注」表示自产 / 未指定来源。</p>
      </div>

      <!-- 区③ 价格历史 + 趋势 -->
      <div class="pd-section">
        <div class="pd-section-head"><span>价格历史</span></div>
        <PriceTrendChart :prices="drawer.prices" />
        <el-table
          :data="drawer.prices" size="small"
          :row-class-name="({ row }: { row: any }) => (row.superseded ? 'price-superseded' : '')"
        >
          <el-table-column label="状态" width="72">
            <template #default="{ row }">
              <el-tag v-if="row.superseded" size="small" type="info">已作废</el-tag>
              <el-tag v-else-if="!row.valid_to" size="small" type="success">生效</el-tag>
              <el-tag v-else size="small">历史</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="price" label="单价" width="88" align="right" />
          <el-table-column prop="currency" label="币种" width="56" />
          <el-table-column prop="valid_from" label="生效日" width="100" />
          <el-table-column prop="valid_to" label="失效日" width="100">
            <template #default="{ row }">{{ row.valid_to ?? '长期' }}</template>
          </el-table-column>
          <el-table-column prop="created_by_name" label="录入人" width="80" />
          <el-table-column prop="note" label="备注" min-width="80" />
        </el-table>
        <p class="sec-note">价格只追加不覆盖；同日纠错的旧价标"已作废"灰显、物理保留可追溯。</p>
      </div>
    </template>

    <template #footer>
      <div v-if="drawer.sku" class="sku-actions">
        <el-tooltip :disabled="!addDisabledReason(drawer.sku)" :content="addDisabledReason(drawer.sku) || ''" placement="top">
          <span>
            <el-button type="primary" :disabled="!!addDisabledReason(drawer.sku)"
                       @click="addToQuote(drawer.sku)">加入报价单</el-button>
          </span>
        </el-tooltip>
        <el-button
          v-if="drawer.sku?.status === 'active' && !drawer.sku?.superseded_by_sku_id"
          type="primary" plain :icon="EditPen"
          @click="router.push({ path: '/configure', query: { edit_sku_id: drawer.sku.id } })"
        >修改配置</el-button>
        <el-button @click="router.push({ path: '/configure', query: { sku_id: drawer.sku.id } })">
          以此为模板再配置
        </el-button>
        <el-button v-if="auth.canSetPrice" @click="openPriceDialog(drawer.sku)">录入新价</el-button>
      </div>
    </template>
  </el-drawer>

  <!-- 录价对话框：产品全貌卡片 + 图片位 + 完整表单 -->
  <el-dialog v-model="priceDialog.visible" title="录入价格" width="640">
    <template v-if="priceDialog.sku">
      <div style="display: flex; gap: 12px; margin-bottom: 14px">
        <div class="price-thumb">
          <el-icon :size="30"><Goods /></el-icon>
          <div style="font-size: 11px; margin-top: 4px">图片待上传</div>
        </div>
        <div style="flex: 1; min-width: 0">
          <div style="font-weight: 500">{{ priceDialog.sku.sku_code }}</div>
          <div style="font-size: 12px; color: var(--el-text-color-secondary)">{{ priceDialog.sku.name }}</div>
          <pre class="tree-mini">{{
            priceDialog.sku.config_tree ? renderTreeText(priceDialog.sku.config_tree).join('\n') : '（构成略）'
          }}</pre>
        </div>
      </div>
      <el-alert
        v-if="priceText(priceDialog.sku)" type="info" :closable="false"
        :title="`当前现行价：${priceText(priceDialog.sku)}`" style="margin-bottom: 12px"
      />
      <el-form label-width="90px">
        <el-form-item label="价格" required>
          <el-input v-model="priceDialog.form.price" placeholder="数字，最多 4 位小数" style="width: 200px" />
        </el-form-item>
        <el-form-item label="币种">
          <el-select v-model="priceDialog.form.currency" style="width: 120px">
            <el-option value="USD" /><el-option value="CNY" /><el-option value="EUR" />
          </el-select>
        </el-form-item>
        <el-form-item label="生效日期">
          <el-date-picker
            v-model="priceDialog.form.valid_from" type="date" value-format="YYYY-MM-DD"
            placeholder="缺省=今天" style="width: 200px"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="priceDialog.form.note" type="textarea" :rows="2" placeholder="可空" />
        </el-form-item>
      </el-form>
      <p style="font-size: 12px; color: var(--el-text-color-secondary)">
        同日改价视为纠错：旧价作废保留可追溯、不覆盖历史；跨日改价为正常追加。
      </p>
    </template>
    <template #footer>
      <el-button @click="priceDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="priceDialog.submitting" @click="submitPrice">确认录入</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.stat-band {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}
.main-tools { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.tools-search { width: 240px; }
.tools-spacer { flex: 1; }
.mobile-filter-toggle { width: 100%; justify-content: center; margin-bottom: 8px; border: 1px dashed var(--el-border-color); }

/* ── 移动端（≤768px）：统计带降列、工具条换行、消除横向溢出（左右栏由 :xs=24 堆叠） ── */
@media (max-width: 768px) {
  .stat-band { grid-template-columns: repeat(2, 1fr); }
  .main-tools { flex-wrap: wrap; }
  .tools-search { width: 100%; }
  .tools-spacer { display: none; }
  .home-toggle { flex-wrap: wrap; gap: 8px; }
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}
.sku-card {
  cursor: pointer;
  transition: transform var(--ph-duration-fast) var(--ph-ease),
    box-shadow var(--ph-duration-fast) var(--ph-ease),
    border-color var(--ph-duration-fast) var(--ph-ease);
}
.sku-card:hover { transform: translateY(-2px); border-color: var(--el-color-primary); }
.sku-thumb {
  height: 60px; display: flex; align-items: center; justify-content: center;
  background: var(--el-fill-color-light); border-radius: 6px; color: var(--el-text-color-secondary);
}
.sku-code { font-weight: 500; font-size: 13px; margin-top: 8px; font-family: var(--ph-font-mono); font-variant-numeric: tabular-nums; }
.sku-name {
  font-size: 12px; color: var(--el-text-color-secondary); margin: 2px 0 6px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  min-height: 32px;
}
.sku-foot { display: flex; align-items: center; gap: 6px; min-height: 24px; }
.sku-foot .price { color: var(--el-color-success); font-size: 16px; font-variant-numeric: tabular-nums; }
/* align-items:center 让裸按钮与被 tooltip<span>包裹的「加入报价单」同基线对齐；
   span 设 inline-flex 否则其内按钮按文字基线下沉，与「改价」上下错位 */
.sku-actions { display: flex; align-items: center; gap: 4px; margin-top: 8px; }
.sku-actions > span { display: inline-flex; }
/* 已作废 SKU：去饱和灰显（沉底由 displayRows 排序保证），仍可点开查看 */
.sku-card.retired { opacity: 0.6; filter: grayscale(0.5); }
/* 作废卡不参与悬停抬升/变色，避免"诱导交互"——特异性 0,2,1 稳压 .sku-card:hover(0,2,0) */
.sku-card.retired:hover { transform: none; border-color: var(--el-border-color); box-shadow: none; }

.price-thumb {
  width: 80px; height: 80px; flex-shrink: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: var(--el-fill-color-light); border-radius: 8px; color: var(--el-text-color-secondary);
}
.tree-mini {
  font-family: inherit; font-size: 12px; line-height: 1.7; white-space: pre-wrap;
  margin: 6px 0 0; max-height: 140px; overflow: auto;
  background: var(--el-fill-color-lighter); border-radius: 6px; padding: 6px 8px;
}
:deep(.price-superseded) { opacity: 0.55; }
.health-issues { margin: 4px 0 0; padding-left: 18px; font-size: 13px; line-height: 1.7; }
/* ===== SKU 详情抽屉（重设计）===== */
.sku-dh { display: flex; align-items: center; gap: 10px; }
.dh-code { font-family: var(--ph-font-mono); font-size: 13px; color: var(--el-text-color-secondary); font-variant-numeric: tabular-nums; }
.copy-code { cursor: pointer; color: var(--ph-gray-400); vertical-align: -2px; }
.copy-code:hover { color: var(--ph-brand-600); }

/* 抽屉 body 默认 padding-top 会在 sticky 决策层之上留缝隙，下滚时 BOM 内容从此漏出（漏视野）。
   修复：body 顶距清零（见文末非 scoped 块，需穿透 teleport），顶距移交决策层自身的 padding-top，
   使其 sticky 贴合滚动区真正顶部、不透明背景完全盖住下方内容。 */
.decide {
  position: sticky; top: 0; z-index: 2; background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  padding: 16px 0 14px; margin-bottom: 14px;
}
.decide-name { font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.link-tag { cursor: pointer; }
.decide-kpis { display: flex; gap: 10px; }
.decide-kpis > * { flex: 1; }

.pd-section { margin-bottom: 18px; }
.pd-section-head {
  display: flex; align-items: center; justify-content: space-between;
  font-weight: 600; font-size: 14px; margin-bottom: 10px;
  padding-bottom: 6px; border-bottom: 1px solid var(--el-border-color-lighter);
}
.sec-tools { font-weight: 400; }
.sec-note { color: var(--el-text-color-secondary); font-size: 12px; margin: 8px 0 0; }

.bom-box { background: var(--el-fill-color-light); border-radius: var(--ph-radius-md); padding: 10px 12px; }

/* 来源地图：清晰两列式（部件左 · 供应商右），平铺无分组 */
.src-box { background: var(--el-fill-color-light); border-radius: var(--ph-radius-md); padding: 4px 12px; }
.src-line {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  font-size: 13px; padding: 6px 0;
}
.src-line + .src-line { border-top: 1px solid var(--el-border-color-lighter); }
.src-label { color: var(--el-text-color-primary); flex-shrink: 0; }
.src-sup { color: var(--ph-brand-600); display: inline-flex; align-items: center; text-align: right; }
.src-arrow { margin-right: 2px; flex-shrink: 0; }
.src-nosrc { color: var(--el-text-color-placeholder); }

/* 产品库视图切换 + 产品全貌 */
.home-toggle { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.ov-band { grid-template-columns: repeat(4, 1fr); }
.ov-group { font-weight: 500; font-size: 14px; margin: 14px 0 8px; color: var(--el-text-color-primary); }
.ov-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.ov-card {
  cursor: pointer;
  transition: transform var(--ph-duration-fast) var(--ph-ease),
    box-shadow var(--ph-duration-fast) var(--ph-ease),
    border-color var(--ph-duration-fast) var(--ph-ease);
}
.ov-card:hover { transform: translateY(-2px); border-color: var(--el-color-primary); box-shadow: var(--ph-shadow-md); }
.ov-card.empty { opacity: 0.6; }
.ov-name { font-size: 15px; font-weight: 500; }
.ov-count { margin: 6px 0 8px; }
.ov-count b { font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; }
.ov-count span { font-size: 12px; color: var(--el-text-color-secondary); margin-left: 4px; }
.ov-badges { display: flex; gap: 6px; align-items: center; min-height: 22px; flex-wrap: wrap; }
.ov-ok { font-size: 12px; color: var(--el-color-success); }
.ov-meta { margin-top: 8px; }
.ov-price { font-size: 15px; color: var(--el-color-success); font-weight: 500; }
.ov-noprice { font-size: 12px; color: var(--el-text-color-placeholder); }
.ov-dims { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 8px;
  border-top: 0.5px solid var(--el-border-color-lighter); padding-top: 8px; }
.ov-unmodeled { color: var(--el-color-warning); }
/* 表格操作列：强制单行不换行（与卡片 .sku-actions 同款），用 gap 取代 EP 默认按钮间距，
   避免列宽不足时按钮被挤到第二行 */
.row-actions { display: flex; align-items: center; gap: 4px; flex-wrap: nowrap; }
.row-actions > span { display: inline-flex; }
.row-actions :deep(.el-button) { margin-left: 0; }
/* 表格视图：已作废行灰显（沉底由 displayRows 排序保证） */
:deep(.row-retired) { color: var(--el-text-color-secondary); opacity: 0.7; }
</style>

<!-- 非 scoped：el-drawer teleport 到 body，scoped :deep 触达不到其内部；用 .sku-drawer 类限定，
     仅作用于本 SKU 详情抽屉，不影响其它抽屉。清掉 body 顶距，配合 .decide sticky 消除"漏视野"。 -->
<style>
.sku-drawer .el-drawer__body { padding-top: 0; }
</style>
