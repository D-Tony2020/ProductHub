<script setup lang="ts">
/** SKU 库（货架，默认首页）：统计带 + 品类树 + 卡片/表格双视图 + 详情抽屉。
 *  P1：统计与计数走聚合端点，检索复用 /skus，零数据层改动。 */
import { CopyDocument, EditPen, Goods, Grid, List, Right, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useQuoteCartStore } from '../stores/quoteCart'

const auth = useAuthStore()
const cart = useQuoteCartStore()
const router = useRouter()
const route = useRoute()

const filters = reactive({
  q: '', root_type_id: null as number | null, status: null as string | null,
  option_id: [] as number[], purchased_part_id: null as number | null,
  supplier_id: null as number | null, mine: false,
})
const stats = ref({ active: 0, pending_price: 0, new_this_week: 0, stale_30d: 0, incomplete: 0 })
const suppliers = ref<any[]>([])
const tree = ref<{ products: any[]; parts: any[] }>({ products: [], parts: [] })
const filterAttrs = ref<any[]>([])
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const viewMode = ref<'card' | 'table'>(
  (localStorage.getItem('sku_view_mode') as 'card' | 'table') || 'card',
)
watch(viewMode, (v) => localStorage.setItem('sku_view_mode', v))

const activeQuick = computed(() => {
  if (filters.mine) return 'mine'
  if (filters.status === 'pending_price') return 'pending'
  if (filters.status === 'incomplete') return 'incomplete'
  if (!filters.root_type_id && !filters.status && !filters.q && !filters.option_id.length) return 'all'
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
  if (s.status !== 'active') return '已作废 SKU 不可报价'
  if (s.health_status === 'incomplete') return '配置不完整（缺必选项/必配部件或违反互斥组），需先治理后才能报价'
  if (!s.current_prices?.length) return '待录价，录入现价后才能加入报价单'
  return null
}

const drawer = reactive({ visible: false, sku: null as any, prices: [] as any[] })

async function loadStats() {
  try {
    stats.value = (await api.get('/skus/stats')).data
  } catch { /* 401 由拦截器处理 */ }
}

async function loadTree() {
  const { data } = await api.get('/template/node-types', { params: { with_counts: true } })
  tree.value = {
    products: data.filter((t: any) => t.kind === 'product' && t.is_sellable_root),
    parts: data.filter((t: any) => t.kind === 'part' && t.is_sellable_root),
  }
}

async function loadSuppliers() {
  try { suppliers.value = (await api.get('/suppliers')).data } catch { /* 忽略 */ }
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
        mine: filters.mine || undefined,
        page: page.value, page_size: 20,
      },
      paramsSerializer: { indexes: null },
    })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    await Promise.all([loadStats(), loadTree(), loadSuppliers(), loadOverview(), load()])
    if (route.query.sku_id) await openDetailById(Number(route.query.sku_id))
  } catch { /* 401 由拦截器跳转登录 */ }
})

watch(() => filters.root_type_id, async (id) => {
  filters.option_id = []
  filterAttrs.value = []
  if (id) {
    const { data } = await api.get(`/template/node-types/${id}`)
    filterAttrs.value = data.attributes.filter((a: any) => a.is_filterable && a.is_active)
  }
  page.value = 1
  await load()
})
watch([() => filters.q, () => filters.status, () => filters.option_id, () => filters.mine,
       () => filters.supplier_id], () => {
  page.value = 1
  void load()
}, { deep: true })
watch(page, () => void load())

// ---- 快捷视图 / 品类树 ----
function selectQuick(kind: 'all' | 'pending' | 'mine' | 'incomplete') {
  filters.q = ''
  filters.option_id = []
  filters.root_type_id = null
  filters.supplier_id = null
  filterAttrs.value = []
  filters.status = kind === 'pending' ? 'pending_price' : kind === 'incomplete' ? 'incomplete' : null
  filters.mine = kind === 'mine'
}
function selectCategory(id: number) {
  filters.mine = false
  filters.status = null
  filters.root_type_id = filters.root_type_id === id ? null : id
}

async function openDetailById(id: number) {
  const { data } = await api.get(`/skus/${id}`)
  drawer.sku = data
  drawer.prices = (await api.get(`/skus/${id}/prices`)).data
  drawer.visible = true
}

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
  const p = s.current_prices[0]
  return `${p.currency} ${p.price}`
}

function renderTreeText(node: any, depth = 0): string[] {
  const pad = '　'.repeat(depth)
  const lines: string[] = []
  const head = node.slot_name ? `${node.slot_name}：` : ''
  if (node.mode === 'purchased') {
    lines.push(`${pad}${head}【成品】${node.supplier_name} | ${node.purchased_part_name}`)
  } else {
    const attrs = (node.attributes ?? [])
      .map((a: any) => `${a.attribute_name}=${a.option_label}${a.option_active ? '' : '（选项已停用）'}`)
      .join('，')
    lines.push(`${pad}${head}${node.node_type_name}${attrs ? `（${attrs}）` : ''}`)
    for (const c of node.children ?? []) lines.push(...renderTreeText(c, depth + 1))
  }
  return lines
}

// 来源地图：把配置树摊成 部件→供应商 行（黑盒派生、白盒标注、未标注=缺口）
function sourcingRows(tree: any): { label: string; supplier: string | null; black: boolean }[] {
  const rows: { label: string; supplier: string | null; black: boolean }[] = []
  function walk(node: any, isRoot: boolean) {
    const label = node.slot_name || node.node_type_name
    if (!isRoot) {
      rows.push({ label, supplier: node.supplier_name ?? null, black: node.mode === 'purchased' })
    } else if (node.supplier_name) {
      rows.push({ label: `${node.node_type_name}（整机）`, supplier: node.supplier_name, black: false })
    }
    for (const c of node.children ?? []) walk(c, false)
  }
  walk(tree, true)
  return rows
}

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
    <span class="toggle-hint">{{ homeView === 'shelf'
      ? '业务员日常：找货 / 查价 / 加报价单'
      : '公司有哪些产品（按品类聚合，比 SKU 粗一档）' }}</span>
    <span style="flex: 1"></span>
    <el-button type="primary" @click="router.push('/configure')">+ 新配置</el-button>
  </div>

  <template v-if="homeView === 'shelf'">
  <!-- 统计带 -->
  <div class="stat-band">
    <div class="stat-card">
      <div class="stat-label">在售 SKU</div>
      <div class="stat-value">{{ stats.active }}</div>
    </div>
    <div class="stat-card clickable" :class="{ warn: stats.pending_price > 0 }"
         @click="selectQuick('pending')">
      <div class="stat-label">待录价 <el-icon><Goods /></el-icon></div>
      <div class="stat-value">{{ stats.pending_price }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">近 7 天新增</div>
      <div class="stat-value">{{ stats.new_this_week }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">30 天未调价</div>
      <div class="stat-value">{{ stats.stale_30d }}</div>
    </div>
    <div class="stat-card clickable" :class="{ danger: stats.incomplete > 0 }"
         @click="selectQuick('incomplete')">
      <div class="stat-label">待治理 <el-icon><WarningFilled /></el-icon></div>
      <div class="stat-value">{{ stats.incomplete }}</div>
    </div>
  </div>

  <el-row :gutter="12">
    <!-- 左栏：快捷视图 + 品类树 -->
    <el-col :span="5">
      <el-card body-style="padding: 12px">
        <div class="side-title">快捷视图</div>
        <div class="side-item" :class="{ active: activeQuick === 'all' }" @click="selectQuick('all')">
          全部 SKU
        </div>
        <div class="side-item" :class="{ active: activeQuick === 'pending' }" @click="selectQuick('pending')">
          待录价
          <el-tag v-if="stats.pending_price" size="small" type="warning">{{ stats.pending_price }}</el-tag>
        </div>
        <div class="side-item" :class="{ active: activeQuick === 'incomplete' }" @click="selectQuick('incomplete')">
          待治理
          <el-tag v-if="stats.incomplete" size="small" type="danger">{{ stats.incomplete }}</el-tag>
        </div>
        <div class="side-item" :class="{ active: activeQuick === 'mine' }" @click="selectQuick('mine')">
          我创建的
        </div>

        <div class="side-title" style="margin-top: 14px">品类</div>
        <div class="side-group">整机</div>
        <div v-for="t in tree.products" :key="t.id" class="side-item indent"
             :class="{ active: filters.root_type_id === t.id }" @click="selectCategory(t.id)">
          <span>{{ t.name }}</span>
          <span class="cnt">{{ t.sku_count ?? 0 }}</span>
        </div>
        <template v-if="tree.parts.length">
          <div class="side-group">配件单卖</div>
          <div v-for="t in tree.parts" :key="t.id" class="side-item indent"
               :class="{ active: filters.root_type_id === t.id }" @click="selectCategory(t.id)">
            <span>{{ t.name }}</span>
            <span class="cnt">{{ t.sku_count ?? 0 }}</span>
          </div>
        </template>
      </el-card>
    </el-col>

    <!-- 主区 -->
    <el-col :span="19">
      <el-card>
        <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 12px">
          <el-select
            v-for="a in filterAttrs" :key="a.id" v-model="filters.option_id" multiple collapse-tags
            :placeholder="a.name" style="width: 160px"
          >
            <el-option
              v-for="o in a.options.filter((o: any) => o.is_active)" :key="o.id"
              :value="o.id" :label="`${a.name}: ${o.label}`"
            />
          </el-select>
          <el-select
            v-model="filters.supplier_id" clearable filterable placeholder="按供应商"
            style="width: 160px"
          >
            <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.name" />
          </el-select>
          <el-input v-model="filters.q" placeholder="SKU 编码 / 名称" clearable style="width: 200px" />
          <span style="flex: 1"></span>
          <el-radio-group v-model="viewMode" size="small">
            <el-radio-button value="card"><el-icon><Grid /></el-icon></el-radio-button>
            <el-radio-button value="table"><el-icon><List /></el-icon></el-radio-button>
          </el-radio-group>
          <el-button @click="exportList">导出 Excel</el-button>
          <el-button type="primary" @click="router.push('/configure')">+ 新配置</el-button>
        </div>

        <!-- 卡片视图 -->
        <div v-if="viewMode === 'card'" v-loading="loading">
          <div v-if="rows.length" class="card-grid">
            <el-card v-for="row in rows" :key="row.id" shadow="hover" body-style="padding: 10px"
                     class="sku-card" @click="openDetailById(row.id)">
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
        <el-table v-else :data="rows" v-loading="loading" @row-click="(r: any) => openDetailById(r.id)">
          <el-table-column prop="sku_code" label="SKU 编码" width="150" />
          <el-table-column prop="name" label="名称 / 规格摘要" min-width="260" />
          <el-table-column label="现价" width="120">
            <template #default="{ row }">
              <b v-if="priceText(row)" style="color: var(--el-color-success)">{{ priceText(row) }}</b>
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
          <el-table-column label="操作" width="240">
            <template #default="{ row }">
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
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-model:current-page="page" :total="total" :page-size="20"
          layout="total, prev, pager, next" style="margin-top: 12px; justify-content: end"
        />
      </el-card>
    </el-col>
  </el-row>
  </template>

  <!-- 产品全貌：按品类聚合的卡片墙（比 SKU 粗一档）-->
  <template v-else>
    <div class="stat-band ov-band">
      <div class="stat-card"><div class="stat-label">产品类型(有货)</div><div class="stat-value">{{ ovStats.types }}</div></div>
      <div class="stat-card"><div class="stat-label">SKU 总数</div><div class="stat-value">{{ ovStats.skus }}</div></div>
      <div class="stat-card" :class="{ warn: ovStats.pending > 0 }"><div class="stat-label">待录价</div><div class="stat-value">{{ ovStats.pending }}</div></div>
      <div class="stat-card" :class="{ danger: ovStats.incomplete > 0 }"><div class="stat-label">待治理</div><div class="stat-value">{{ ovStats.incomplete }}</div></div>
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
            <span v-if="priceRange(t)" class="ov-price">{{ priceRange(t) }}</span>
            <span v-else class="ov-noprice">{{ t.sku_count ? '待录价' : '暂无 SKU' }}</span>
          </div>
          <div class="ov-dims">
            <template v-if="t.slot_count || t.attr_count">选配维度 · {{ t.slot_count }} 部件槽 · {{ t.attr_count }} 属性轴</template>
            <span v-else class="ov-unmodeled">待建模 · 去「系统设置 · 产品模板」建属性与部件槽</span>
          </div>
        </el-card>
      </div>
    </template>
    <p class="ov-foot">
      点任一品类卡 → 下钻到该品类的 SKU 货架。产品全貌只读，看"公司有哪些产品"；
      改产品类型结构请到「系统设置 · 产品模板」。
    </p>
  </template>

  <el-drawer v-model="drawer.visible" size="50%" :title="drawer.sku?.sku_code">
    <template v-if="drawer.sku">
      <h3 style="margin-top: 0">{{ drawer.sku.name }}</h3>
      <p>
        <el-tag :type="drawer.sku.status === 'active' ? 'success' : 'info'">
          {{ drawer.sku.status === 'active' ? '在售' : '已作废' }}
        </el-tag>
        <span v-if="priceText(drawer.sku)" style="font-size: 22px; margin-left: 12px; color: var(--el-color-success)">
          {{ priceText(drawer.sku) }}
        </span>
        <el-tag v-else type="warning" style="margin-left: 12px">待录价</el-tag>
        <el-tag v-if="drawer.sku.superseded_by_sku_code" type="info" effect="plain" style="margin-left: 8px">
          已被 {{ drawer.sku.superseded_by_sku_code }} 取代
        </el-tag>
      </p>
      <el-alert
        v-if="drawer.sku.health && drawer.sku.health.status !== 'ok'"
        :type="drawer.sku.health.blocking ? 'error' : 'warning'"
        :closable="false" show-icon style="margin-bottom: 12px"
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
      <el-tabs>
        <el-tab-pane label="产品构成（事实视图）">
          <pre style="font-family: inherit; line-height: 1.9; white-space: pre-wrap">{{
            drawer.sku.config_tree ? renderTreeText(drawer.sku.config_tree).join('\n') : '—'
          }}</pre>
        </el-tab-pane>
        <el-tab-pane label="来源地图">
          <div v-if="drawer.sku.config_tree" class="sourcing-map">
            <div v-for="(r, i) in sourcingRows(drawer.sku.config_tree)" :key="i" class="src-row">
              <span class="src-label">{{ r.label }}</span>
              <span v-if="r.supplier" class="src-sup">
                <el-tag size="small" :type="r.black ? 'info' : 'primary'" effect="plain">
                  {{ r.black ? '成品件' : '标注' }}
                </el-tag>
                <el-icon style="vertical-align: -2px; margin: 0 4px"><Right /></el-icon>{{ r.supplier }}
              </span>
              <span v-else class="src-none">
                <el-icon style="vertical-align: -2px; margin-right: 2px"><WarningFilled /></el-icon>未标注来源
              </span>
            </div>
          </div>
          <p style="color: var(--el-text-color-secondary); font-size: 12px; margin-top: 8px">
            黑盒成品件来源由其供应商派生；白盒配置件来源为节点级标注（已入指纹，改来源生成新 SKU）。
          </p>
        </el-tab-pane>
        <el-tab-pane label="价格历史">
          <el-table :data="drawer.prices"
                    :row-class-name="({ row }) => (row.superseded ? 'price-superseded' : '')">
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.superseded" size="small" type="info">已作废</el-tag>
                <el-tag v-else-if="!row.valid_to" size="small" type="success">生效</el-tag>
                <el-tag v-else size="small">历史</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="price" label="单价" width="100" />
            <el-table-column prop="currency" label="币种" width="64" />
            <el-table-column prop="valid_from" label="生效日" width="106" />
            <el-table-column prop="valid_to" label="失效日" width="106">
              <template #default="{ row }">{{ row.valid_to ?? '长期' }}</template>
            </el-table-column>
            <el-table-column prop="created_by_name" label="录入人" width="90" />
            <el-table-column prop="note" label="备注" />
          </el-table>
          <p style="color: var(--el-text-color-secondary); font-size: 12px">
            价格只追加不覆盖；同日纠错的旧价标"已作废"灰显、物理保留可追溯。
          </p>
        </el-tab-pane>
      </el-tabs>
      <div style="display: flex; gap: 8px; margin-top: 12px">
        <el-tooltip :disabled="!addDisabledReason(drawer.sku)" :content="addDisabledReason(drawer.sku) || ''" placement="top">
          <span>
            <el-button type="primary" :disabled="!!addDisabledReason(drawer.sku)"
                       @click="addToQuote(drawer.sku)">加入报价单</el-button>
          </span>
        </el-tooltip>
        <el-button
          v-if="drawer.sku.status === 'active' && !drawer.sku.superseded_by_sku_id"
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
.stat-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 14px;
}
.stat-card.clickable { cursor: pointer; }
.stat-card.clickable:hover { border-color: var(--el-color-primary); }
.stat-card.warn { background: var(--el-color-warning-light-9); }
.stat-card.danger { background: var(--el-color-danger-light-9); }
.stat-card.danger:hover { border-color: var(--el-color-danger); }
.stat-label { font-size: 12px; color: var(--el-text-color-secondary); }
.stat-value { font-size: 24px; font-weight: 500; margin-top: 2px; }

.side-title { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
.side-group { font-weight: 500; margin: 6px 0 2px; font-size: 13px; }
.side-item {
  display: flex; align-items: center; justify-content: space-between; gap: 6px;
  padding: 5px 8px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.side-item:hover { background: var(--el-fill-color-light); }
.side-item.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.side-item.indent { padding-left: 16px; }
.side-item .cnt { color: var(--el-text-color-secondary); font-size: 12px; }

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}
.sku-card { cursor: pointer; }
.sku-thumb {
  height: 60px; display: flex; align-items: center; justify-content: center;
  background: var(--el-fill-color-light); border-radius: 6px; color: var(--el-text-color-secondary);
}
.sku-code { font-weight: 500; font-size: 13px; margin-top: 8px; }
.sku-name {
  font-size: 12px; color: var(--el-text-color-secondary); margin: 2px 0 6px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  min-height: 32px;
}
.sku-foot { display: flex; align-items: center; gap: 6px; min-height: 24px; }
.sku-foot .price { color: var(--el-color-success); font-size: 16px; }
.sku-actions { display: flex; gap: 4px; margin-top: 8px; }

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
.sourcing-map { display: flex; flex-direction: column; gap: 6px; }
.src-row {
  display: flex; align-items: center; justify-content: space-between;
  background: var(--el-fill-color-lighter); border-radius: 6px; padding: 7px 11px;
}
.src-label { font-size: 13px; }
.src-sup { font-size: 13px; color: var(--el-color-primary); }
.src-none { font-size: 13px; color: var(--el-color-danger); }

/* 产品库视图切换 + 产品全貌 */
.home-toggle { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.toggle-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.stat-card.danger { background: var(--el-color-danger-light-9); }
.ov-group { font-weight: 500; font-size: 14px; margin: 14px 0 8px; color: var(--el-text-color-primary); }
.ov-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.ov-card { cursor: pointer; transition: border-color .15s; }
.ov-card.empty { opacity: 0.6; }
.ov-name { font-size: 15px; font-weight: 500; }
.ov-count { margin: 6px 0 8px; }
.ov-count b { font-size: 26px; font-weight: 600; }
.ov-count span { font-size: 12px; color: var(--el-text-color-secondary); margin-left: 4px; }
.ov-badges { display: flex; gap: 6px; align-items: center; min-height: 22px; flex-wrap: wrap; }
.ov-ok { font-size: 12px; color: var(--el-color-success); }
.ov-meta { margin-top: 8px; }
.ov-price { font-size: 15px; color: var(--el-color-success); font-weight: 500; }
.ov-noprice { font-size: 12px; color: var(--el-text-color-placeholder); }
.ov-dims { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 8px;
  border-top: 0.5px solid var(--el-border-color-lighter); padding-top: 8px; }
.ov-unmodeled { color: var(--el-color-warning); }
.ov-foot { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 14px; }
</style>
