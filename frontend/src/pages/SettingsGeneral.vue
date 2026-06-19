<script setup lang="ts">
/** 通用设置（全员可进）：per-user 界面偏好——默认币种/排序/每页/视图 + 产品库筛选分面自定义。
 *  改动即防抖自动保存（写入 per-user preferences）。 */
import { ArrowDown, ArrowUp, Rank, RefreshLeft } from '@element-plus/icons-vue'
import { ref, watch } from 'vue'

import { CURRENCY_OPTIONS, resolveFacets, SORT_OPTIONS, type ResolvedFacet } from '../constants/facets'
import { usePreferencesStore } from '../stores/preferences'

const pref = usePreferencesStore()

const PAGE_SIZES = [20, 50, 100]

// ---- 分面自定义：显示哪些分面、顺序如何（上下移调序 + 开关显隐）----
const items = ref<ResolvedFacet[]>(resolveFacets(pref.productFacets))
let selfUpdate = false
watch(() => pref.productFacets, () => {
  if (selfUpdate) { selfUpdate = false; return }  // 跳过自身写入引发的回流，避免覆盖编辑中状态
  items.value = resolveFacets(pref.productFacets)
})
function persist() {
  selfUpdate = true
  pref.set({
    product_facets: items.value.map((f) => ({ key: f.key, visible: f.visible, expanded: f.expanded })),
  })
}
function move(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= items.value.length) return
  const arr = items.value.slice();
  [arr[i], arr[j]] = [arr[j], arr[i]]
  items.value = arr
  persist()
}
function toggleVisible(i: number, v: boolean) {
  items.value[i].visible = v
  persist()
}
function resetFacets() {
  items.value = resolveFacets(undefined)  // 回到出厂顺序、全部显示
  persist()
}
</script>

<template>
  <div>
    <h3 class="pg-title">通用设置</h3>
    <p class="pg-sub">以下偏好仅影响你自己的界面，修改后自动保存。</p>

    <el-card class="set-card">
      <template #header><span class="ch">默认显示偏好</span></template>
      <el-form label-width="120px">
        <el-form-item label="默认币种">
          <el-select
            :model-value="pref.currency" style="width: 200px"
            @update:model-value="(v: any) => pref.set({ default_currency: v })"
          >
            <el-option v-for="c in CURRENCY_OPTIONS" :key="c" :value="c" :label="c" />
          </el-select>
          <span class="hint">产品库价格排序 / 筛选所用币种</span>
        </el-form-item>
        <el-form-item label="默认排序">
          <el-select
            :model-value="pref.sort" style="width: 200px"
            @update:model-value="(v: any) => pref.set({ default_sort: v })"
          >
            <el-option v-for="s in SORT_OPTIONS" :key="s.value" :value="s.value" :label="s.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="每页条数">
          <el-select
            :model-value="pref.pageSize" style="width: 200px"
            @update:model-value="(v: any) => pref.set({ page_size: v })"
          >
            <el-option v-for="n in PAGE_SIZES" :key="n" :value="n" :label="`${n} 条 / 页`" />
          </el-select>
        </el-form-item>
        <el-form-item label="默认视图">
          <el-radio-group
            :model-value="pref.view"
            @update:model-value="(v: any) => pref.set({ default_view: v })"
          >
            <el-radio-button value="card">卡片</el-radio-button>
            <el-radio-button value="table">表格</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="set-card">
      <template #header>
        <span class="ch">产品库筛选分面</span>
        <el-button link type="primary" size="small" :icon="RefreshLeft" class="reset-btn"
                   @click="resetFacets">恢复默认</el-button>
      </template>
      <p class="card-note">设置产品库左栏显示哪些分面、以何顺序排列。「快捷视图」与「品类树」为常驻区，不在此列。</p>
      <ul class="facet-list">
        <li v-for="(f, i) in items" :key="f.key" class="facet-row" :class="{ off: !f.visible }">
          <el-icon class="grip"><Rank /></el-icon>
          <span class="fr-main">
            <span class="fr-label">{{ f.label }}</span>
            <span v-if="f.hint" class="fr-hint">{{ f.hint }}</span>
          </span>
          <span class="fr-ord">
            <el-button text :icon="ArrowUp" size="small" :disabled="i === 0" aria-label="上移"
                       @click="move(i, -1)" />
            <el-button text :icon="ArrowDown" size="small" :disabled="i === items.length - 1"
                       aria-label="下移" @click="move(i, 1)" />
          </span>
          <el-switch :model-value="f.visible" size="small"
                     @update:model-value="(v: any) => toggleVisible(i, v)" />
        </li>
      </ul>
    </el-card>
  </div>
</template>

<style scoped>
.pg-title { margin: 0 0 2px; }
.pg-sub { color: var(--el-text-color-secondary); font-size: 13px; margin: 0 0 16px; }
.set-card { max-width: 720px; margin-bottom: 16px; }
.ch { font-weight: 600; }
.reset-btn { float: right; }
.hint { margin-left: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.card-note { color: var(--el-text-color-secondary); font-size: 12px; margin: 0 0 12px; }

.facet-list { list-style: none; margin: 0; padding: 0; }
.facet-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 8px; border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--ph-radius-sm); margin-bottom: 8px; background: var(--el-bg-color);
}
.facet-row.off { opacity: 0.55; }
.grip { color: var(--ph-gray-400); cursor: default; }
.fr-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.fr-label { font-size: 14px; }
.fr-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.fr-ord { display: flex; }
</style>
