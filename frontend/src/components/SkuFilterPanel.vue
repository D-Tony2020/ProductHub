<script setup lang="ts">
/** 产品库分面检索面板（左栏）。
 *  常驻区：快捷视图 + 分类导航（「按品类 / 按供应商」视角切换，整块可折叠）。
 *    · 按品类：品类树（整机 / 配件单卖）。
 *    · 按供应商：供应商列表（带关联在售 SKU 计数 + 搜索）→ 展开下钻该供应商的品类分布（双维）。
 *  可自定义区：采购来源 / 价格区间 / 可报价 / 规格属性——顺序与显隐由 per-user 偏好驱动。
 *  受控：filters 为父级 reactive，子组件就地改其字段；有副作用的选择走 emit。 */
import { ArrowRightBold, Search, Setting } from '@element-plus/icons-vue'
import { computed, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import { SOURCING_OPTIONS, type ResolvedFacet } from '../constants/facets'

const props = defineProps<{
  filters: any
  stats: { pending_price: number; incomplete: number }
  tree: { products: any[]; parts: any[] }
  suppliers: any[]
  filterAttrs: any[]
  facets: ResolvedFacet[]
  activeQuick: string
  currency: string
}>()
const emit = defineEmits<{
  quick: [k: string]
  category: [id: number]
  supplier: [id: number]
  'supplier-category': [p: { supplierId: number; partTypeId: number; partTypeName: string }]
  'open-settings': []
}>()

// 折叠态：本地维护，按 facet.expanded 初始化（偏好里 expanded=false 的默认折叠）
const collapsed = reactive(new Set<string>())
watch(() => props.facets, (fs) => {
  collapsed.clear()
  for (const f of fs) if (!f.expanded) collapsed.add(f.key)
}, { immediate: true, deep: true })
function toggle(k: string) { collapsed.has(k) ? collapsed.delete(k) : collapsed.add(k) }

// ---- 分类导航：视角切换（持久化）+ 整块可折叠 ----
const viewBy = ref<'category' | 'supplier'>(
  (localStorage.getItem('ph_filter_viewby') as 'category' | 'supplier') || 'category',
)
watch(viewBy, (v) => localStorage.setItem('ph_filter_viewby', v))
const navCollapsed = ref(false)

// ---- 按供应商视角：搜索 / 排序 / 按需下钻品类分布 ----
const supplierSearch = ref('')
const expanded = reactive(new Set<number>())              // 已展开的供应商
const breakdown = reactive(new Map<number, any[]>())      // supplierId → 品类分布(缓存)
const loadingBreakdown = reactive(new Set<number>())
const filteredSuppliers = computed(() => {
  const kw = supplierSearch.value.trim().toLowerCase()
  return props.suppliers
    .filter((s) => (s.linked_skus ?? 0) > 0)               // 仅显示有关联在售 SKU 的供应商
    .filter((s) => !kw || s.name.toLowerCase().includes(kw)
      || (s.code && s.code.toLowerCase().includes(kw)))
    .sort((a, b) => (b.linked_skus ?? 0) - (a.linked_skus ?? 0))
})
async function toggleExpand(s: any) {
  if (expanded.has(s.id)) { expanded.delete(s.id); return }
  expanded.add(s.id)
  if (!breakdown.has(s.id) && !loadingBreakdown.has(s.id)) {
    loadingBreakdown.add(s.id)
    try {
      breakdown.set(s.id, (await api.get(`/suppliers/${s.id}/category-breakdown`)).data)
    } catch { breakdown.set(s.id, []) } finally { loadingBreakdown.delete(s.id) }
  }
}
// 高亮：纯供应商 vs 供应商×件类型
function isSupplierActive(s: any) {
  return props.filters.supplier_id === s.id && props.filters.supplier_part_type_id == null
}
function isCatActive(s: any, c: any) {
  return props.filters.supplier_id === s.id && props.filters.supplier_part_type_id === c.node_type_id
}
</script>

<template>
  <el-card body-style="padding: 12px" class="fp-card">
    <!-- 常驻：快捷视图 -->
    <div class="side-title">快捷视图</div>
    <div class="side-item" :class="{ active: activeQuick === 'all' }" @click="emit('quick', 'all')">
      全部 SKU
    </div>
    <div class="side-item" :class="{ active: activeQuick === 'pending' }" @click="emit('quick', 'pending')">
      待录价
      <el-tag v-if="stats.pending_price" size="small" type="warning">{{ stats.pending_price }}</el-tag>
    </div>
    <div class="side-item" :class="{ active: activeQuick === 'incomplete' }" @click="emit('quick', 'incomplete')">
      待治理
      <el-tag v-if="stats.incomplete" size="small" type="danger">{{ stats.incomplete }}</el-tag>
    </div>
    <div class="side-item" :class="{ active: activeQuick === 'mine' }" @click="emit('quick', 'mine')">
      我创建的
    </div>

    <!-- 分类导航（整块可折叠）：按品类 / 按供应商 视角切换 -->
    <div class="facet">
      <div class="facet-head" @click="navCollapsed = !navCollapsed">
        <span>分类导航</span>
        <el-icon class="facet-caret" :class="{ open: !navCollapsed }"><ArrowRightBold /></el-icon>
      </div>
      <div v-show="!navCollapsed" class="facet-body">
        <el-radio-group v-model="viewBy" size="small" class="viewby">
          <el-radio-button value="category">按品类</el-radio-button>
          <el-radio-button value="supplier">按供应商</el-radio-button>
        </el-radio-group>

        <!-- 按品类 -->
        <template v-if="viewBy === 'category'">
          <div class="side-group">整机</div>
          <div v-for="t in tree.products" :key="t.id" class="side-item indent"
               :class="{ active: filters.root_type_id === t.id && filters.supplier_id == null }"
               @click="emit('category', t.id)">
            <span class="si-name" :title="t.name">{{ t.name }}</span>
            <span class="cnt">{{ t.sku_count ?? 0 }}</span>
          </div>
          <template v-if="tree.parts.length">
            <div class="side-group">配件单卖</div>
            <div v-for="t in tree.parts" :key="t.id" class="side-item indent"
                 :class="{ active: filters.root_type_id === t.id && filters.supplier_id == null }"
                 @click="emit('category', t.id)">
              <span class="si-name" :title="t.name">{{ t.name }}</span>
              <span class="cnt">{{ t.sku_count ?? 0 }}</span>
            </div>
          </template>
        </template>

        <!-- 按供应商：搜索 + 列表（计数 + 展开下钻品类） -->
        <template v-else>
          <el-input v-model="supplierSearch" placeholder="搜索供应商" size="small" clearable class="sup-search">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <div v-for="s in filteredSuppliers" :key="s.id" class="sup-block">
            <div class="side-item" :class="{ active: isSupplierActive(s) }" @click="emit('supplier', s.id)">
              <el-icon class="sup-caret" :class="{ open: expanded.has(s.id) }"
                       @click.stop="toggleExpand(s)"><ArrowRightBold /></el-icon>
              <span class="si-name" :title="s.name">{{ s.name }}</span>
              <span class="cnt">{{ s.linked_skus }}</span>
            </div>
            <div v-if="expanded.has(s.id)" class="sup-cats">
              <div v-if="loadingBreakdown.has(s.id)" class="fp-empty">加载中…</div>
              <div v-for="c in breakdown.get(s.id) || []" :key="c.node_type_id"
                   class="side-item indent2" :class="{ active: isCatActive(s, c) }"
                   @click="emit('supplier-category', { supplierId: s.id, partTypeId: c.node_type_id, partTypeName: c.name })">
                <span class="si-name" :title="c.name">{{ c.name }}</span>
                <span class="cnt">{{ c.count }}</span>
              </div>
            </div>
          </div>
          <div v-if="!filteredSuppliers.length" class="fp-empty">无匹配供应商</div>
        </template>
      </div>
    </div>

    <!-- 可自定义分面（按偏好顺序，仅显示 visible） -->
    <template v-for="f in facets" :key="f.key">
      <div v-if="f.visible" class="facet">
        <div class="facet-head" @click="toggle(f.key)">
          <span>{{ f.label }}</span>
          <el-icon class="facet-caret" :class="{ open: !collapsed.has(f.key) }"><ArrowRightBold /></el-icon>
        </div>
        <div v-show="!collapsed.has(f.key)" class="facet-body">
          <!-- 采购来源 -->
          <el-checkbox-group v-if="f.key === 'sourcing'" v-model="filters.sourcing" class="fp-checks">
            <el-checkbox v-for="o in SOURCING_OPTIONS" :key="o.value" :value="o.value">
              {{ o.label }}
            </el-checkbox>
          </el-checkbox-group>

          <!-- 价格区间（逐币种，@change 提交避免逐字重载） -->
          <div v-else-if="f.key === 'price'" class="fp-price">
            <el-input-number
              :model-value="filters.price_min" :min="0" :controls="false" placeholder="最低"
              class="fp-num" @change="(v: any) => filters.price_min = (v ?? null)"
            />
            <span class="fp-dash">—</span>
            <el-input-number
              :model-value="filters.price_max" :min="0" :controls="false" placeholder="最高"
              class="fp-num" @change="(v: any) => filters.price_max = (v ?? null)"
            />
            <span class="fp-ccy">{{ currency }}</span>
          </div>

          <!-- 可报价 -->
          <el-checkbox v-else-if="f.key === 'quotable'" v-model="filters.quotable">
            仅看可立即报价
          </el-checkbox>

          <!-- 规格属性（随所选品类动态） -->
          <template v-else-if="f.key === 'attrs'">
            <div v-if="!filters.root_type_id" class="fp-empty">选择品类后展开规格筛选</div>
            <div v-else-if="!filterAttrs.length" class="fp-empty">该品类暂无可筛选规格</div>
            <el-select
              v-for="a in filterAttrs" :key="a.id" v-model="filters.option_id" multiple
              collapse-tags collapse-tags-tooltip :placeholder="a.name" size="default"
              style="width: 100%; margin-bottom: 6px"
            >
              <el-option
                v-for="o in a.options.filter((o: any) => o.is_active)" :key="o.id"
                :value="o.id" :label="`${a.name}: ${o.label}`"
              />
            </el-select>
          </template>
        </div>
      </div>
    </template>

    <div class="fp-foot">
      <el-button link type="primary" size="small" :icon="Setting" @click="emit('open-settings')">
        自定义分面
      </el-button>
    </div>
  </el-card>
</template>

<style scoped>
.fp-card { position: sticky; top: 12px; }
.side-title { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
.side-group { font-weight: 500; margin: 6px 0 2px; font-size: 13px; }
.side-item {
  display: flex; align-items: center; justify-content: space-between; gap: 6px;
  padding: 5px 8px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.side-item:hover { background: var(--el-fill-color-light); }
.side-item.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.side-item.indent { padding-left: 16px; }
.side-item.indent2 { padding-left: 30px; font-size: 12px; }
.si-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.side-item .cnt { color: var(--el-text-color-secondary); font-size: 12px; font-variant-numeric: tabular-nums; flex-shrink: 0; }

.facet { border-top: 1px solid var(--el-border-color-lighter); margin-top: 10px; padding-top: 8px; }
.facet-head {
  display: flex; align-items: center; justify-content: space-between;
  font-weight: 500; font-size: 13px; cursor: pointer; user-select: none; padding: 2px 0;
}
.facet-caret { transition: transform var(--ph-duration-fast) var(--ph-ease); color: var(--ph-gray-400); }
.facet-caret.open { transform: rotate(90deg); }
.facet-body { padding: 8px 2px 2px; }

.viewby { display: flex; width: 100%; margin-bottom: 8px; }
.viewby :deep(.el-radio-button) { flex: 1; }
.viewby :deep(.el-radio-button__inner) { width: 100%; }
.sup-search { margin-bottom: 8px; }
.sup-block { margin-bottom: 1px; }
.sup-caret {
  flex-shrink: 0; color: var(--ph-gray-400); cursor: pointer; padding: 2px; margin: -2px 0 -2px -4px;
  transition: transform var(--ph-duration-fast) var(--ph-ease);
}
.sup-caret.open { transform: rotate(90deg); }
.sup-cats { margin: 1px 0 4px; }

.fp-checks { display: flex; flex-direction: column; gap: 2px; }
.fp-price { display: flex; align-items: center; gap: 6px; }
.fp-num { width: 84px; }
.fp-dash { color: var(--el-text-color-secondary); }
.fp-ccy { font-size: 12px; color: var(--el-text-color-secondary); }
.fp-empty { font-size: 12px; color: var(--el-text-color-placeholder); padding: 2px 0; }
.fp-foot { margin-top: 14px; padding-top: 8px; border-top: 1px solid var(--el-border-color-lighter); text-align: center; }
</style>
