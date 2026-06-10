<script setup lang="ts">
/** 成品采购件库：检索 + admin 审核/合并/停用。 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const rows = ref<any[]>([])
const nodeTypes = ref<any[]>([])
const filters = reactive({ q: '', node_type_id: null as number | null, status: null as string | null })
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    rows.value = (await api.get('/purchased-parts', {
      params: {
        q: filters.q || undefined,
        node_type_id: filters.node_type_id ?? undefined,
        status: filters.status ?? undefined,
      },
    })).data
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  nodeTypes.value = (await api.get('/template/node-types')).data.filter((t: any) => t.kind === 'part')
  await load()
})
watch(filters, () => void load())

async function approve(row: any) {
  await api.post(`/purchased-parts/${row.id}/approve`)
  ElMessage.success('已转正')
  await load()
}

async function retire(row: any) {
  await ElMessageBox.confirm(
    `停用「${row.name}」？停用后不可用于新配置，已引用它的 ${row.reference_count} 个 SKU 不受影响。`,
    '停用成品件', { type: 'warning' },
  )
  await api.post(`/purchased-parts/${row.id}/retire`)
  await load()
}

async function merge(row: any) {
  const { value } = await ElMessageBox.prompt(
    `将「${row.name}」标记为重复件，合并指向哪个件？请输入目标件的 ID（同部件类型）。`
    + '合并只影响未来配置；历史 SKU 保持原引用。',
    '合并重复件', { inputPattern: /^\d+$/, inputErrorMessage: '请输入数字 ID' },
  )
  await api.post(`/purchased-parts/${row.id}/merge`, { target_part_id: Number(value) })
  ElMessage.success('已合并')
  await load()
}

const statusMap: Record<string, { label: string; type: string }> = {
  draft: { label: '草稿', type: 'warning' },
  active: { label: '正式', type: 'success' },
  merged: { label: '已合并', type: 'info' },
  retired: { label: '已停用', type: 'info' },
}
</script>

<template>
  <el-card>
    <div style="display: flex; gap: 10px; margin-bottom: 12px">
      <el-select v-model="filters.node_type_id" placeholder="部件类型" clearable style="width: 160px">
        <el-option v-for="t in nodeTypes" :key="t.id" :value="t.id" :label="t.name" />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" clearable style="width: 130px">
        <el-option value="draft" label="草稿（待审核）" />
        <el-option value="active" label="正式" />
        <el-option value="merged" label="已合并" />
        <el-option value="retired" label="已停用" />
      </el-select>
      <el-input v-model="filters.q" placeholder="供应商 / 件名" clearable style="width: 220px" />
    </div>
    <el-table :data="rows" v-loading="loading">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="code" label="件号" width="130" />
      <el-table-column prop="name" label="件名" min-width="180" />
      <el-table-column prop="supplier_name" label="供应商" width="140" />
      <el-table-column prop="node_type_name" label="部件类型" width="110" />
      <el-table-column prop="reference_count" label="被引用 SKU" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusMap[row.status]?.type as any" size="small">
            {{ statusMap[row.status]?.label }}
          </el-tag>
          <div v-if="row.merged_into_id" style="font-size: 11px; color: var(--el-text-color-secondary)">
            → #{{ row.merged_into_id }}
          </div>
        </template>
      </el-table-column>
      <el-table-column v-if="auth.isAdmin" label="操作" width="200">
        <template #default="{ row }">
          <el-button v-if="row.status === 'draft'" size="small" type="success" @click="approve(row)">转正</el-button>
          <el-button v-if="['draft', 'active'].includes(row.status)" size="small" @click="merge(row)">合并</el-button>
          <el-button v-if="['draft', 'active'].includes(row.status)" size="small" type="danger" plain @click="retire(row)">停用</el-button>
        </template>
      </el-table-column>
    </el-table>
    <p style="color: var(--el-text-color-secondary); font-size: 12px">
      业务员在配置看板现场新建的件为「草稿」，可直接用于配置；管理员在此审核转正或标记重复合并。
    </p>
  </el-card>
</template>
