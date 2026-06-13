<script setup lang="ts">
/** SKU 库（货架，默认首页）：统计带 + 品类树 + 卡片/表格双视图 + 详情抽屉。
 *  P1：统计与计数走聚合端点，检索复用 /skus，零数据层改动。 */
import { CopyDocument, Goods, Grid, List } from '@element-plus/icons-vue'
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
  option_id: [] as number[], purchased_part_id: null as number | null, mine: false,
})
const stats = ref({ active: 0, pending_price: 0, new_this_week: 0, stale_30d: 0 })
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
  if (!filters.root_type_id && !filters.status && !filters.q && !filters.option_id.length) return 'all'
  return ''
})

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
    await Promise.all([loadStats(), loadTree(), load()])
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
watch([() => filters.q, () => filters.status, () => filters.option_id, () => filters.mine], () => {
  page.value = 1
  void load()
}, { deep: true })
watch(page, () => void load())

// ---- 快捷视图 / 品类树 ----
function selectQuick(kind: 'all' | 'pending' | 'mine') {
  filters.q = ''
  filters.option_id = []
  filters.root_type_id = null
  filterAttrs.value = []
  filters.status = kind === 'pending' ? 'pending_price' : null
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
  if (r.ok) ElMessage.success('已加入当前报价单')
  else if (r.message === 'NO_ACTIVE') {
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
</script>

<template>
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
              </div>
              <div class="sku-actions" @click.stop>
                <el-button size="small" type="primary"
                           :disabled="!row.current_prices?.length || row.status !== 'active'"
                           @click="addToQuote(row)">加入报价单</el-button>
                <el-button v-if="auth.canSetPrice" size="small" @click="openPriceDialog(row)">改价</el-button>
                <span style="flex: 1"></span>
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
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                {{ row.status === 'active' ? '在售' : '已作废' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="240">
            <template #default="{ row }">
              <el-button size="small" type="primary"
                         :disabled="!row.current_prices?.length || row.status !== 'active'"
                         @click.stop="addToQuote(row)">加入报价单</el-button>
              <el-button v-if="auth.canSetPrice" size="small" @click.stop="openPriceDialog(row)">改价</el-button>
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
      </p>
      <el-tabs>
        <el-tab-pane label="产品构成（事实视图）">
          <pre style="font-family: inherit; line-height: 1.9; white-space: pre-wrap">{{
            drawer.sku.config_tree ? renderTreeText(drawer.sku.config_tree).join('\n') : '—'
          }}</pre>
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
        <el-button
          type="primary" :disabled="!drawer.sku.current_prices?.length || drawer.sku.status !== 'active'"
          @click="addToQuote(drawer.sku)"
        >加入报价单</el-button>
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
  grid-template-columns: repeat(4, 1fr);
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
</style>
