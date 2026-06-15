<script setup lang="ts">
/** 价格趋势折线图（手绘 SVG·零依赖，守"不引重型依赖"红线）。
 *  取非作废价按生效日排序连线；不足 2 点不绘。纯展示，消费 prices 原样字段。 */
import { computed } from 'vue'

const props = defineProps<{ prices: any[] }>()

const W = 520, H = 132, padL = 10, padR = 58, padT = 14, padB = 22

const points = computed(() =>
  (props.prices || [])
    .filter((r) => !r.superseded && r.price != null)
    .map((r) => ({ v: parseFloat(r.price), d: r.valid_from as string, cur: r.currency as string }))
    .filter((r) => !Number.isNaN(r.v))
    .sort((a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : 0)))

const ready = computed(() => points.value.length >= 2)
const minV = computed(() => Math.min(...points.value.map((p) => p.v)))
const maxV = computed(() => Math.max(...points.value.map((p) => p.v)))

const coords = computed(() => {
  const n = points.value.length
  const uw = W - padL - padR, uh = H - padT - padB
  const span = maxV.value - minV.value || 1
  return points.value.map((p, i) => ({
    x: padL + (n === 1 ? uw / 2 : (i * uw) / (n - 1)),
    y: padT + (1 - (p.v - minV.value) / span) * uh,
    v: p.v, d: p.d, cur: p.cur,
  }))
})
const linePath = computed(() =>
  coords.value.map((c, i) => `${i ? 'L' : 'M'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' '))
const areaPath = computed(() => {
  const cs = coords.value
  if (!cs.length) return ''
  return `M${cs[0].x},${H - padB} `
    + cs.map((c) => `L${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
    + ` L${cs[cs.length - 1].x},${H - padB} Z`
})
const last = computed(() => coords.value[coords.value.length - 1])
const fmt = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 })
</script>

<template>
  <div class="trend">
    <svg v-if="ready" :viewBox="`0 0 ${W} ${H}`" width="100%" style="height: auto; display: block" role="img" aria-label="价格趋势">
      <line :x1="0" :x2="W - padR" :y1="H - padB" :y2="H - padB" stroke="var(--el-border-color-lighter)" stroke-width="1" />
      <path :d="areaPath" fill="var(--el-color-success-light-9)" />
      <path :d="linePath" fill="none" stroke="var(--ph-success)" stroke-width="2" stroke-linejoin="round" />
      <circle v-for="(c, i) in coords" :key="i" :cx="c.x" :cy="c.y" r="3" fill="var(--ph-success)" />
      <circle :cx="last.x" :cy="last.y" r="4.5" fill="var(--ph-success)" stroke="#fff" stroke-width="1.5" />
      <text :x="last.x - 6" :y="last.y - 8" text-anchor="end" class="t-val">{{ last.cur }} {{ fmt(last.v) }}</text>
      <text :x="W - padR + 6" :y="padT + 4" class="t-ax">{{ fmt(maxV) }}</text>
      <text :x="W - padR + 6" :y="H - padB" class="t-ax">{{ fmt(minV) }}</text>
      <text :x="padL" :y="H - 6" class="t-ax">{{ coords[0].d }}</text>
      <text :x="W - padR" :y="H - 6" text-anchor="end" class="t-ax">{{ last.d }}</text>
    </svg>
    <div v-else class="trend-empty">价格点不足 2 个，暂无趋势</div>
  </div>
</template>

<style scoped>
.trend { width: 100%; margin: 4px 0 2px; }
.t-val { font-size: 11px; fill: var(--ph-success); font-weight: 600; font-family: var(--ph-font-mono); }
.t-ax { font-size: 10px; fill: var(--el-text-color-secondary); font-family: var(--ph-font-mono); }
.trend-empty { font-size: 12px; color: var(--el-text-color-secondary); padding: 14px 0; text-align: center; }
</style>
