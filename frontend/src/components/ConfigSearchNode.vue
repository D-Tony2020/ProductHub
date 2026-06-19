<script setup lang="ts">
/** 结构化检索·递归节点（复用配置器 NodeState 模型，但只为"按配置找货"而生，不落库不校验）。
 *  每个部件节点：可筛选规格(单选→option_id) + 来源供应商(→supplier×件类型) + 懒加载子槽。
 *  全部可选、留空=不限。与配置器共用 loadType/newNodeState/getTypeMeta，不改动 Configure.vue。 */
import { ArrowRightBold } from '@element-plus/icons-vue'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  getTypeMeta, loadType, newNodeState, type NodeState, type SlotMeta, type TypeMeta,
} from '../composables/useConfigurator'

defineOptions({ name: 'ConfigSearchNode' })

const props = defineProps<{ node: NodeState; typeId: number; suppliers: any[]; depth?: number }>()

const meta = ref<TypeMeta | null>(getTypeMeta(props.typeId))
const expanded = reactive(new Set<number>())  // 已展开的子槽 id

// 显示该部件的全部在用规格（含 is_filterable=false 的精细规格，如把手颜色）——
// 「按配置找货」是配置式查询：逐项规格皆可设，选中即转 option_id，后端按"配置树存在该取值"过滤。
const specAttrs = computed(() => meta.value?.attributes ?? [])
const slots = computed(() => meta.value?.slots ?? [])

onMounted(async () => { if (!meta.value) meta.value = await loadType(props.typeId) })

async function toggleSlot(s: SlotMeta) {
  if (expanded.has(s.id)) { expanded.delete(s.id); return }
  expanded.add(s.id)
  const st = props.node.slots[s.id]
  if (st.mode !== 'configured' || !st.child) {
    st.mode = 'configured'
    st.child = await newNodeState(s.child_type_id)
  }
}
function slotHasCondition(s: SlotMeta): boolean {
  const st = props.node.slots[s.id]
  return !!(st && st.mode === 'configured' && st.child && nodeHasCondition(st.child))
}
function nodeHasCondition(n: NodeState): boolean {
  if (n.supplierId != null) return true
  if (Object.values(n.attrs).some((v) => v != null)) return true
  return Object.values(n.slots).some((st) => st.mode === 'configured' && st.child && nodeHasCondition(st.child))
}
</script>

<template>
  <div class="cs-node">
    <!-- 本节点：精细规格(全部在用属性，左) + 来源供应商(右) -->
    <div class="cs-self">
      <div v-for="a in specAttrs" :key="a.id" class="cs-field">
        <span class="cs-label">{{ a.name }}</span>
        <el-select
          v-model="node.attrs[a.id]" clearable placeholder="不限" size="small" style="width: 160px"
        >
          <el-option
            v-for="o in a.options.filter((o: any) => o.is_active)" :key="o.id"
            :value="o.id" :label="o.label"
          />
        </el-select>
      </div>
      <div class="cs-field">
        <span class="cs-label">来源供应商</span>
        <el-select
          v-model="node.supplierId" clearable filterable placeholder="不限" size="small" style="width: 200px"
        >
          <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.name" />
        </el-select>
      </div>
    </div>

    <!-- 子槽：懒展开后递归 -->
    <div v-for="s in slots" :key="s.id" class="cs-slot">
      <div class="cs-slot-head" @click="toggleSlot(s)">
        <el-icon class="cs-caret" :class="{ open: expanded.has(s.id) }"><ArrowRightBold /></el-icon>
        <span class="cs-slot-name">{{ s.name }}</span>
        <span v-if="slotHasCondition(s)" class="cs-dot" />
        <span class="cs-slot-hint">{{ expanded.has(s.id) ? '' : '展开设条件' }}</span>
      </div>
      <div v-if="expanded.has(s.id) && node.slots[s.id]?.child" class="cs-children">
        <ConfigSearchNode
          :node="node.slots[s.id].child!" :type-id="s.child_type_id"
          :suppliers="suppliers" :depth="(depth || 0) + 1"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.cs-self { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; padding: 2px 0 6px; }
.cs-field { display: inline-flex; align-items: center; gap: 6px; }
.cs-label { font-size: 12px; color: var(--el-text-color-secondary); }
.cs-slot { margin-top: 2px; }
.cs-slot-head {
  display: flex; align-items: center; gap: 6px; padding: 5px 4px; border-radius: 6px;
  cursor: pointer; font-size: 13px; user-select: none;
}
.cs-slot-head:hover { background: var(--el-fill-color-light); }
.cs-caret { color: var(--ph-gray-400); transition: transform var(--ph-duration-fast) var(--ph-ease); }
.cs-caret.open { transform: rotate(90deg); }
.cs-slot-name { font-weight: 500; }
.cs-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ph-brand-600); }
.cs-slot-hint { font-size: 11px; color: var(--el-text-color-placeholder); }
.cs-children {
  margin-left: 9px; padding-left: 14px; border-left: 1px solid var(--el-border-color-lighter);
  margin-bottom: 4px;
}
</style>
