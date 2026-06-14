<script setup lang="ts">
/** 成品采购件表（可复用）：
 *  - 不传 supplierId = 全部采购件（跨供应商），带供应商列与供应商搜索；
 *  - 传 supplierId  = 某供应商名下，隐藏供应商列，提供"在该供应商下新建采购件"。 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'

const router = useRouter()

const props = defineProps<{ supplierId?: number | null }>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const auth = useAuthStore()
const rows = ref<any[]>([])
const nodeTypes = ref<any[]>([])
const filters = reactive({ q: '', node_type_id: null as number | null, status: null as string | null })
const loading = ref(false)
const scoped = computed(() => props.supplierId != null)

async function load() {
  loading.value = true
  try {
    rows.value = (await api.get('/purchased-parts', {
      params: {
        q: filters.q || undefined,
        node_type_id: filters.node_type_id ?? undefined,
        status: filters.status ?? undefined,
        supplier_id: props.supplierId ?? undefined,
      },
    })).data
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    nodeTypes.value = (await api.get('/template/node-types')).data.filter((t: any) => t.kind === 'part')
    await load()
  } catch { /* 401 由拦截器跳转登录 */ }
})
watch(filters, () => void load())
watch(() => props.supplierId, () => void load())

async function approve(row: any) {
  await api.post(`/purchased-parts/${row.id}/approve`)
  ElMessage.success('已转正')
  await load(); emit('changed')
}

async function retire(row: any) {
  await ElMessageBox.confirm(
    `停用「${row.name}」？停用后不可用于新配置，已引用它的 ${row.reference_count} 个 SKU 不受影响。`,
    '停用成品件', { type: 'warning' },
  )
  await api.post(`/purchased-parts/${row.id}/retire`)
  await load(); emit('changed')
}

async function merge(row: any) {
  const { value } = await ElMessageBox.prompt(
    `将「${row.name}」标记为重复件，合并指向哪个件？请输入目标件的 ID（同部件类型）。`
    + '合并只影响未来配置；历史 SKU 保持原引用。',
    '合并重复件', { inputPattern: /^\d+$/, inputErrorMessage: '请输入数字 ID' },
  )
  await api.post(`/purchased-parts/${row.id}/merge`, { target_part_id: Number(value) })
  ElMessage.success('已合并')
  await load(); emit('changed')
}

// 在当前供应商下新建采购件
const createDialog = reactive({ visible: false, form: { name: '', node_type_id: null as number | null } })
async function submitCreate() {
  if (!createDialog.form.name || !createDialog.form.node_type_id) {
    ElMessage.warning('请填写件名并选择部件类型')
    return
  }
  try {
    await api.post('/purchased-parts', {
      node_type_id: createDialog.form.node_type_id,
      supplier_id: props.supplierId,
      name: createDialog.form.name,
    })
    createDialog.visible = false
    createDialog.form = { name: '', node_type_id: null }
    ElMessage.success('已新建')
    await load(); emit('changed')
  } catch { /* 拦截器提示 */ }
}

const statusMap: Record<string, { label: string; type: string }> = {
  draft: { label: '草稿', type: 'warning' },
  active: { label: '正式', type: 'success' },
  merged: { label: '已合并', type: 'info' },
  retired: { label: '已停用', type: 'info' },
}
</script>

<template>
  <div>
    <div style="display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; align-items: center">
      <el-select v-model="filters.node_type_id" placeholder="部件类型" clearable style="width: 160px">
        <el-option v-for="t in nodeTypes" :key="t.id" :value="t.id" :label="t.name" />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" clearable style="width: 130px">
        <el-option value="draft" label="草稿（待审核）" />
        <el-option value="active" label="正式" />
        <el-option value="merged" label="已合并" />
        <el-option value="retired" label="已停用" />
      </el-select>
      <el-input
        v-model="filters.q" :placeholder="scoped ? '件名' : '供应商 / 件名'" clearable style="width: 200px"
      />
      <span style="flex: 1"></span>
      <el-button v-if="scoped && auth.isAdmin" type="primary" @click="createDialog.visible = true">
        + 在该供应商下新建采购件
      </el-button>
    </div>
    <el-table :data="rows" v-loading="loading">
      <el-table-column prop="code" label="件号" width="120" />
      <el-table-column prop="name" label="件名" min-width="170" />
      <el-table-column v-if="!scoped" prop="supplier_name" label="供应商" width="130" />
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
      <el-table-column v-if="auth.isAdmin" label="状态/规格" width="110">
        <template #default="{ row }">
          <el-button
            v-if="['draft', 'active'].includes(row.status)" size="small" text type="primary"
            @click="router.push({ path: '/configure', query: { part_spec_id: row.id } })"
          >{{ row.spec_config || row.spec_note ? '规格✓ 编辑' : '+ 规格' }}</el-button>
        </template>
      </el-table-column>
      <el-table-column v-if="auth.isAdmin" label="操作" width="190">
        <template #default="{ row }">
          <el-button v-if="row.status === 'draft'" size="small" type="success" @click="approve(row)">转正</el-button>
          <el-button v-if="['draft', 'active'].includes(row.status)" size="small" @click="merge(row)">合并</el-button>
          <el-button v-if="['draft', 'active'].includes(row.status)" size="small" type="danger" plain @click="retire(row)">停用</el-button>
        </template>
      </el-table-column>
    </el-table>
    <p style="color: var(--el-text-color-secondary); font-size: 12px">
      业务员在配置看板现场新建的件为「草稿」，可直接用于配置；管理员在此审核转正、合并重复或停用。
    </p>

    <el-dialog v-model="createDialog.visible" title="新建成品采购件" width="460">
      <el-form label-width="90px">
        <el-form-item label="件名" required>
          <el-input v-model="createDialog.form.name" placeholder="如 华消K2阀门（件号自动生成）" />
        </el-form-item>
        <el-form-item label="部件类型" required>
          <el-select v-model="createDialog.form.node_type_id" filterable style="width: 100%" placeholder="选择部件类型">
            <el-option v-for="t in nodeTypes" :key="t.id" :value="t.id" :label="t.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>
