<script setup lang="ts">
/** 产品构成 BOM 树递归节点（纯展示·零数据流）：白盒(configured) caret 展开 + 属性 chip；
 *  黑盒(purchased) [成品] + 件名。只讲构成、不含供应商（来源见详情页「来源地图」，职能不交叉）。
 *  折叠态由父级传入的 reactive Set<path> 管。 */
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { computed } from 'vue'

defineOptions({ name: 'BomTreeNode' })  // 显式名，保证模板自递归可解析

const props = defineProps<{ node: any; depth?: number; path?: string; collapsed: Set<string> }>()

const p = computed(() => props.path ?? '0')
const isBlackbox = computed(() => props.node?.mode === 'purchased')
const hasChildren = computed(() => Array.isArray(props.node?.children) && props.node.children.length > 0)
const open = computed(() => !props.collapsed?.has(p.value))
const spec = computed(() =>
  [props.node?.part_spec_summary, props.node?.part_spec_note].filter(Boolean).join('；'))

function toggle() {
  if (!props.collapsed) return
  if (props.collapsed.has(p.value)) props.collapsed.delete(p.value)
  else props.collapsed.add(p.value)
}
</script>

<template>
  <div class="bom-node">
    <div class="bom-row">
      <i v-if="hasChildren" class="bom-caret" @click="toggle">
        <el-icon><component :is="open ? ArrowDown : ArrowRight" /></el-icon>
      </i>
      <span v-else class="bom-leaf"></span>

      <span v-if="node.slot_name" class="bom-slot">{{ node.slot_name }}：</span>
      <el-tag v-if="isBlackbox" size="small" type="primary" effect="dark" class="bom-tag">成品</el-tag>
      <span class="bom-name">{{ isBlackbox ? node.purchased_part_name : node.node_type_name }}</span>

      <!-- 白盒：属性 chip（黑盒只件名；供应商见「来源地图」，职能不交叉） -->
      <template v-if="!isBlackbox">
        <el-tag
          v-for="(a, i) in node.attributes" :key="i" size="small"
          :type="a.option_active === false ? 'warning' : 'info'" effect="plain" class="bom-chip"
        >{{ a.attribute_name }} {{ a.option_label }}{{ a.option_active === false ? '（已停用）' : '' }}</el-tag>
      </template>
    </div>

    <!-- 灰盒规格行（黑盒件已补录规格时） -->
    <div v-if="isBlackbox && spec" class="bom-spec">规格 · {{ spec }}</div>

    <!-- 子节点递归（白盒展开） -->
    <div v-if="hasChildren && open" class="bom-children">
      <BomTreeNode
        v-for="(c, i) in node.children" :key="i"
        :node="c" :depth="(depth || 0) + 1" :path="`${p}-${i}`" :collapsed="collapsed"
      />
    </div>
  </div>
</template>

<style scoped>
.bom-row {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  padding: 4px 0; font-size: var(--ph-font-size-sm); line-height: 1.5;
  border-radius: var(--ph-radius-xs);
}
.bom-row:hover { background: var(--el-fill-color-light); }
.bom-caret { cursor: pointer; color: var(--el-text-color-secondary); display: inline-flex; flex-shrink: 0; }
.bom-leaf { width: 16px; flex-shrink: 0; }
.bom-slot { color: var(--el-text-color-secondary); }
.bom-name { color: var(--el-text-color-primary); }
.bom-tag { flex-shrink: 0; }
.bom-chip { font-weight: 400; }
.bom-spec {
  font-family: var(--ph-font-mono); font-size: var(--ph-font-size-xs);
  color: var(--el-text-color-secondary); background: var(--el-fill-color-light);
  border-radius: var(--ph-radius-xs); padding: 3px 8px; margin: 2px 0 4px 22px;
}
.bom-children { margin-left: 7px; padding-left: 16px; }
</style>
