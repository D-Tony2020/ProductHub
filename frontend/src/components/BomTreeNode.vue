<script setup lang="ts">
/** 产品构成 BOM 树递归节点（纯展示·零数据流）。三态：
 *  白盒(configured) caret 可展开 + 属性 chip；黑盒(purchased) 工业蓝色条 + 成品 tag + 供应商(终止)；
 *  灰盒规格行挂在黑盒下方。折叠态由父级传入的 reactive Set<path> 管。详见 frontend/DESIGN.md。 */
import { ArrowDown, ArrowRight, Right } from '@element-plus/icons-vue'
import { computed } from 'vue'

defineOptions({ name: 'BomTreeNode' })  // 显式名，保证模板自递归可解析

const props = defineProps<{ node: any; depth?: number; path?: string; collapsed: Set<string> }>()

const p = computed(() => props.path ?? '0')
const isBlackbox = computed(() => props.node?.mode === 'purchased')
const hasChildren = computed(() => Array.isArray(props.node?.children) && props.node.children.length > 0)
const open = computed(() => !props.collapsed.has(p.value))
const spec = computed(() =>
  [props.node?.part_spec_summary, props.node?.part_spec_note].filter(Boolean).join('；'))

function toggle() {
  if (props.collapsed.has(p.value)) props.collapsed.delete(p.value)
  else props.collapsed.add(p.value)
}
</script>

<template>
  <div class="bom-node">
    <div class="bom-row" :class="{ blackbox: isBlackbox }">
      <i v-if="hasChildren" class="bom-caret" @click="toggle">
        <el-icon><component :is="open ? ArrowDown : ArrowRight" /></el-icon>
      </i>
      <span v-else class="bom-leaf">·</span>

      <el-tag v-if="isBlackbox" size="small" type="primary" effect="dark" class="bom-tag">成品</el-tag>
      <span v-if="node.slot_name" class="bom-slot">{{ node.slot_name }}：</span>
      <span class="bom-name">{{ isBlackbox ? node.purchased_part_name : node.node_type_name }}</span>

      <!-- 黑盒：供应商（终止） -->
      <span v-if="isBlackbox && node.supplier_name" class="bom-sup">
        <el-icon class="bom-sup-arrow"><Right /></el-icon>{{ node.supplier_name }}
      </span>

      <!-- 白盒：属性 chip -->
      <template v-else>
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
.bom-row.blackbox { border-left: 3px solid var(--ph-brand-600); padding-left: 6px; }
.bom-caret { cursor: pointer; color: var(--el-text-color-secondary); display: inline-flex; }
.bom-leaf { color: var(--ph-gray-400); width: 16px; text-align: center; }
.bom-slot { color: var(--el-text-color-secondary); }
.bom-name { color: var(--el-text-color-primary); }
.bom-tag { flex-shrink: 0; }
.bom-chip { font-weight: 400; }
.bom-sup { color: var(--ph-brand-600); display: inline-flex; align-items: center; }
.bom-sup-arrow { margin: 0 2px; }
.bom-spec {
  font-family: var(--ph-font-mono); font-size: var(--ph-font-size-xs);
  color: var(--el-text-color-secondary); background: var(--el-fill-color-light);
  border-radius: var(--ph-radius-xs); padding: 3px 8px; margin: 2px 0 4px 22px;
}
.bom-children { border-left: 1px solid var(--el-border-color); margin-left: 7px; padding-left: 14px; }
</style>
