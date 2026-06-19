<script setup lang="ts">
/** 按配置找货（结构化检索·快版）：像配置产品一样，只填在意的几项→命中满足这些项的 SKU。
 *  复用配置器底层(loadType/newNodeState/getTypeMeta)与 NodeState 模型，输出现有 /skus 参数，
 *  后端零改动。快版口径：root_type + 多个规格(option_id, 按 node_type 隐式) + 一个来源(供应商×件类型)。 */
import { Search } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import { api } from '../api/client'
import {
  getTypeMeta, newNodeState, type NodeState,
} from '../composables/useConfigurator'
import ConfigSearchNode from './ConfigSearchNode.vue'

const props = defineProps<{
  modelValue: boolean
  products: any[]        // 整机品类（is_sellable_root, kind=product）
  suppliers: any[]
}>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean]; apply: [q: any] }>()

const rootTypeId = ref<number | null>(null)
const rootNode = ref<NodeState | null>(null)
const hitCount = ref<number | null>(null)
const countLoading = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

async function onPickRoot(id: number) {
  rootTypeId.value = id
  rootNode.value = await newNodeState(id)  // loadType 进缓存 + 初始化空状态
}
function reset() {
  if (rootTypeId.value) void onPickRoot(rootTypeId.value)
}

/** 遍历 NodeState 树 → 现有 /skus 参数。完整版：收集任意多个来源条件(供应商×件类型)成 sp_pair[]。 */
const query = computed(() => {
  const q: any = {
    root_type_id: rootTypeId.value,
    option_id: [] as number[],
    // 多对来源："该件类型由该供应商供应"，可任意多对并立；各自 AND
    supplier_pairs: [] as Array<{ supplier_id: number; node_type_id: number; supplier_name: string; part_type_name: string }>,
    root_type_name: '',
    opt_labels: {} as Record<number, string>,
  }
  if (!rootTypeId.value || !rootNode.value) return q
  q.root_type_name = props.products.find((p) => p.id === rootTypeId.value)?.name
    ?? getTypeMeta(rootTypeId.value)?.name ?? ''
  function walk(node: NodeState, typeId: number) {
    const meta = getTypeMeta(typeId)
    for (const [attrId, optId] of Object.entries(node.attrs)) {
      if (optId == null) continue
      q.option_id.push(optId as number)
      const a = meta?.attributes.find((x) => x.id === Number(attrId))
      const o = a?.options.find((x) => x.id === optId)
      if (a && o) q.opt_labels[optId as number] = `${a.name}: ${o.label}`
    }
    if (node.supplierId != null) {
      q.supplier_pairs.push({
        supplier_id: node.supplierId,
        node_type_id: typeId,
        supplier_name: props.suppliers.find((s) => s.id === node.supplierId)?.name ?? `#${node.supplierId}`,
        part_type_name: meta?.name ?? '',
      })
    }
    for (const [slotId, st] of Object.entries(node.slots)) {
      if (st.mode === 'configured' && st.child) {
        const slotMeta = meta?.slots.find((s) => s.id === Number(slotId))
        if (slotMeta) walk(st.child, slotMeta.child_type_id)
      }
    }
  }
  walk(rootNode.value, rootTypeId.value)
  return q
})

const condCount = computed(() => query.value.option_id.length + query.value.supplier_pairs.length)

function paramsOf(q: any) {
  return {
    root_type_id: q.root_type_id ?? undefined,
    option_id: q.option_id.length ? q.option_id : undefined,
    sp_pair: q.supplier_pairs.length
      ? q.supplier_pairs.map((p: any) => `${p.supplier_id}:${p.node_type_id}`) : undefined,
  }
}

watch(query, () => {
  if (timer) clearTimeout(timer)
  if (!rootTypeId.value) { hitCount.value = null; return }
  countLoading.value = true
  timer = setTimeout(async () => {
    try {
      const { data } = await api.get('/skus', {
        params: { ...paramsOf(query.value), page_size: 1 },
        paramsSerializer: { indexes: null },
      })
      hitCount.value = data.total
    } catch { hitCount.value = null } finally { countLoading.value = false }
  }, 350)
}, { deep: true })

function doSearch() {
  emit('apply', JSON.parse(JSON.stringify(query.value)))
  emit('update:modelValue', false)
}
</script>

<template>
  <el-drawer
    :model-value="modelValue" size="600px" direction="rtl" title="按配置找货"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <p class="ss-sub">像配置产品一样，只填你在意的几项、其余留空；命中满足这些项的在售 SKU。</p>

    <div class="ss-root">
      <span class="ss-label">整机品类</span>
      <el-select
        :model-value="rootTypeId" placeholder="先选整机品类" filterable style="width: 240px"
        @update:model-value="onPickRoot"
      >
        <el-option v-for="p in products" :key="p.id" :value="p.id" :label="p.name" />
      </el-select>
      <el-button v-if="rootTypeId" text size="small" @click="reset">重置</el-button>
    </div>

    <template v-if="rootNode && rootTypeId">
      <div class="ss-hint">按结构填写 · 留空 = 不限 · 展开部件设规格 / 来源</div>
      <div class="ss-tree">
        <ConfigSearchNode :node="rootNode" :type-id="rootTypeId" :suppliers="suppliers" />
      </div>
      <div v-if="query.supplier_pairs.length" class="ss-pairs">
        <el-tag
          v-for="(p, i) in query.supplier_pairs" :key="i" size="small" type="info" effect="plain"
        >{{ p.part_type_name }} ← {{ p.supplier_name }}</el-tag>
      </div>
    </template>
    <el-empty v-else :image-size="60" description="先选一个整机品类开始" />

    <template #footer>
      <div class="ss-foot">
        <div class="ss-foot-l">
          <div class="ss-hit-label">实时命中 · 已设 {{ condCount }} 项条件</div>
          <div class="ss-hit">
            <span v-if="countLoading" class="ss-loading">…</span>
            <template v-else-if="hitCount != null">约 <b>{{ hitCount.toLocaleString() }}</b> 个</template>
            <span v-else class="ss-loading">—</span>
          </div>
        </div>
        <el-button type="primary" :icon="Search" :disabled="!rootTypeId" @click="doSearch">
          搜索这些条件
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.ss-sub { color: var(--el-text-color-secondary); font-size: 13px; margin: 0 0 14px; }
.ss-root { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.ss-label { font-size: 13px; color: var(--el-text-color-secondary); }
.ss-hint { font-size: 12px; color: var(--el-text-color-placeholder); margin-bottom: 8px; }
.ss-tree {
  border: 0.5px solid var(--el-border-color-lighter); border-radius: var(--ph-radius-md);
  padding: 10px 12px;
}
.ss-pairs { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 0; }
.ss-foot { display: flex; align-items: center; gap: 12px; }
.ss-foot-l { flex: 1; }
.ss-hit-label { font-size: 12px; color: var(--el-text-color-tertiary); }
.ss-hit { font-size: 20px; font-weight: 500; }
.ss-hit b { font-variant-numeric: tabular-nums; }
.ss-loading { color: var(--el-text-color-placeholder); }
</style>
