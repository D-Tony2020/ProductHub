<script setup lang="ts">
/** 结果工具条：命中计数 + 排序 + 逐币种选择器 + 卡片/表格切换 + 生效筛选 chips（可逐个移除/清空）。
 *  纯展示+受控组件：所有状态由父级（SkuList）持有并经 v-model / emit 回传，组件自身不持数据。 */
import { Grid, List } from '@element-plus/icons-vue'

import { CURRENCY_OPTIONS, SORT_OPTIONS } from '../constants/facets'

defineProps<{
  total: number
  sort: string
  currency: string
  view: 'card' | 'table'
  chips: { key: string; text: string }[]
}>()
const emit = defineEmits<{
  'update:sort': [v: string]
  'update:currency': [v: string]
  'update:view': [v: 'card' | 'table']
  remove: [key: string]
  'clear-all': []
}>()
</script>

<template>
  <div class="sortbar">
    <div class="sb-row">
      <span class="sb-count">共 <b>{{ total.toLocaleString() }}</b> 个 SKU</span>
      <span style="flex: 1"></span>
      <span class="sb-lbl">排序</span>
      <el-select
        :model-value="sort" size="default" style="width: 150px"
        @update:model-value="(v: any) => emit('update:sort', v)"
      >
        <el-option v-for="o in SORT_OPTIONS" :key="o.value" :value="o.value" :label="o.label" />
      </el-select>
      <el-select
        :model-value="currency" size="default" style="width: 92px"
        @update:model-value="(v: any) => emit('update:currency', v)"
      >
        <el-option v-for="c in CURRENCY_OPTIONS" :key="c" :value="c" :label="c" />
      </el-select>
      <el-radio-group
        :model-value="view" size="default"
        @update:model-value="(v: any) => emit('update:view', v)"
      >
        <el-radio-button value="card"><el-icon><Grid /></el-icon></el-radio-button>
        <el-radio-button value="table"><el-icon><List /></el-icon></el-radio-button>
      </el-radio-group>
    </div>
    <div v-if="chips.length" class="sb-chips">
      <span class="sb-chips-lbl">已筛选</span>
      <el-tag
        v-for="c in chips" :key="c.key" closable size="small" type="info" effect="plain"
        disable-transitions @close="emit('remove', c.key)"
      >{{ c.text }}</el-tag>
      <el-button link type="primary" size="small" @click="emit('clear-all')">清空全部</el-button>
    </div>
  </div>
</template>

<style scoped>
.sortbar { margin-bottom: 12px; }
.sb-row { display: flex; align-items: center; gap: 8px; }
.sb-count { font-size: 13px; color: var(--el-text-color-secondary); }
.sb-count b { color: var(--el-text-color-primary); font-variant-numeric: tabular-nums; }
.sb-lbl { font-size: 13px; color: var(--el-text-color-secondary); }
.sb-chips {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--el-border-color-lighter);
}
.sb-chips-lbl { font-size: 12px; color: var(--el-text-color-secondary); }
</style>
