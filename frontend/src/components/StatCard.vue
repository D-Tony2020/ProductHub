<script setup lang="ts">
/** 统一指标卡（设计系统组件）：收编全站原本各写一遍的「数字+标签」卡。
 *  纯展示，仅 props + 一个 click 事件。详见 frontend/DESIGN.md。 */
defineProps<{
  label: string
  value: string | number
  tone?: 'default' | 'brand' | 'success' | 'warning' | 'danger' | 'info'
  unit?: string
  hint?: string
  clickable?: boolean
  active?: boolean
  alert?: boolean  // true=告警态(染浅底+前景色，用于待录价/待治理)；默认仅左色条+白底
}>()
const emit = defineEmits<{ (e: 'click'): void }>()
</script>

<template>
  <div
    class="ph-stat" :class="[`tone-${tone || 'default'}`, { clickable, active, alert }]"
    :role="clickable ? 'button' : undefined" :tabindex="clickable ? 0 : undefined"
    @click="clickable && emit('click')"
    @keydown.enter.prevent="clickable && emit('click')"
  >
    <div class="ph-stat-label">{{ label }}<span v-if="hint" class="ph-stat-hint"> · {{ hint }}</span></div>
    <div class="ph-stat-value ph-num">{{ value }}<span v-if="unit" class="ph-stat-unit">{{ unit }}</span></div>
  </div>
</template>

<style scoped>
.ph-stat {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-left: 3px solid transparent;
  border-radius: var(--ph-radius-md);
  padding: var(--ph-space-4);
  transition: transform var(--ph-duration-fast) var(--ph-ease),
    box-shadow var(--ph-duration-fast) var(--ph-ease),
    border-color var(--ph-duration-fast) var(--ph-ease);
}
.ph-stat-label { font-size: var(--ph-font-size-xs); color: var(--el-text-color-secondary); }
.ph-stat-hint { color: var(--el-text-color-placeholder); }
.ph-stat-value {
  font-size: var(--ph-font-size-2xl); font-weight: 600; line-height: 1.25;
  color: var(--el-text-color-primary); margin-top: var(--ph-space-1);
}
.ph-stat-unit { font-size: var(--ph-font-size-xs); font-weight: 400; color: var(--el-text-color-secondary); margin-left: 2px; }

.tone-brand { border-left-color: var(--ph-brand-600); }
.tone-brand .ph-stat-value { color: var(--ph-brand-600); }
.tone-info { border-left-color: var(--ph-info); }
.tone-success { border-left-color: var(--ph-success); }
.tone-warning { border-left-color: var(--el-color-warning); }
.tone-danger { border-left-color: var(--el-color-danger); }
/* 告警态：仅 alert 时染浅底 + 前景色（待录价 / 待治理）*/
.alert.tone-warning { background: var(--el-color-warning-light-9); }
.alert.tone-warning .ph-stat-label, .alert.tone-warning .ph-stat-value { color: var(--ph-warning-fg); }
.alert.tone-danger { background: var(--el-color-danger-light-9); }
.alert.tone-danger .ph-stat-label, .alert.tone-danger .ph-stat-value { color: var(--el-color-danger); }

.clickable { cursor: pointer; }
.clickable:hover { border-color: var(--ph-brand-600); box-shadow: var(--ph-shadow-md); transform: translateY(-1px); }
.clickable:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 1px; }
.active { border-color: var(--ph-brand-600); background: var(--el-color-primary-light-9); }
</style>
