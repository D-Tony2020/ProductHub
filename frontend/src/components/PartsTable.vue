<script setup lang="ts">
/** 成品采购件表（可复用）：
 *  - 不传 supplierId = 全部采购件（跨供应商），带供应商列与供应商搜索；
 *  - 传 supplierId  = 某供应商名下，隐藏供应商列，提供"在该供应商下新建采购件"。 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import { PART_STATUS as statusMap } from '../constants/status'
import { useAuthStore } from '../stores/auth'
import PartDetailDrawer from './PartDetailDrawer.vue'

const router = useRouter()

// 采购件详情抽屉
const detail = reactive({ visible: false, partId: null as number | null, editOnLoad: false })
function openDetail(row: any) {
  detail.partId = row.id
  detail.editOnLoad = false
  detail.visible = true
}
function openEdit(row: any) {
  detail.partId = row.id
  detail.editOnLoad = true
  detail.visible = true
}
function onDetailChanged() {
  void load()
  emit('changed')
}

const props = defineProps<{ supplierId?: number | null; supplierDefaultLead?: number | null }>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const auth = useAuthStore()
const rows = ref<any[]>([])
const nodeTypes = ref<any[]>([])
const filters = reactive({ q: '', node_type_id: null as number | null, status: null as string | null })
const loading = ref(false)
const scoped = computed(() => props.supplierId != null)
// 采购件可为部件(part)或整机(product)：两类分别供筛选/新建下拉与列表标签
const partTypes = computed(() => nodeTypes.value.filter((t) => t.kind === 'part'))
const assemblyTypes = computed(() => nodeTypes.value.filter((t) => t.kind === 'product'))
const kindOf = (id: number) => nodeTypes.value.find((t) => t.id === id)?.kind

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
    nodeTypes.value = (await api.get('/template/node-types')).data
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

// 在当前供应商下新建采购件（部件 / 整机 两类，整机即"整机直采"可作SKU根）
const createDialog = reactive({
  visible: false,
  form: {
    kind: 'part' as 'part' | 'product',
    name: '', node_type_id: null as number | null,
    lead_time_days: null as number | null, spec_note: '',
  },
})
const similarItems = ref<any[]>([])
const createTypeOptions = computed(() =>
  createDialog.form.kind === 'product' ? assemblyTypes.value : partTypes.value)

function openCreate() {
  createDialog.form = {
    kind: 'part', name: '', node_type_id: null,
    lead_time_days: props.supplierDefaultLead ?? null, spec_note: '',
  }
  similarItems.value = []
  createDialog.visible = true
}
function onKindChange() {
  createDialog.form.node_type_id = null  // 切换大类清空已选类型
  similarItems.value = []
}

let similarTimer: ReturnType<typeof setTimeout> | null = null
function scheduleSimilar() {
  if (similarTimer) clearTimeout(similarTimer)
  similarTimer = setTimeout(checkSimilar, 350)
}
async function checkSimilar() {
  const { node_type_id, name } = createDialog.form
  if (!node_type_id || !name.trim()) { similarItems.value = []; return }
  try {
    similarItems.value = (await api.get('/purchased-parts/similar', {
      params: { node_type_id, name: name.trim() },
    })).data
  } catch { similarItems.value = [] }
}

async function submitCreate() {
  if (!createDialog.form.name.trim() || !createDialog.form.node_type_id) {
    ElMessage.warning('请填写件名并选择类型')
    return
  }
  try {
    await api.post('/purchased-parts', {
      node_type_id: createDialog.form.node_type_id,
      supplier_id: props.supplierId,
      name: createDialog.form.name.trim(),
      lead_time_days: createDialog.form.lead_time_days,
      spec_note: createDialog.form.spec_note || null,
    })
    createDialog.visible = false
    ElMessage.success('已新建')
    await load(); emit('changed')
  } catch { /* 拦截器提示 */ }
}

</script>

<template>
  <div>
    <div style="display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; align-items: center">
      <el-select v-model="filters.node_type_id" placeholder="类型" clearable style="width: 170px">
        <el-option-group label="整机">
          <el-option v-for="t in assemblyTypes" :key="t.id" :value="t.id" :label="t.name" />
        </el-option-group>
        <el-option-group label="部件">
          <el-option v-for="t in partTypes" :key="t.id" :value="t.id" :label="t.name" />
        </el-option-group>
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
      <el-button v-if="scoped && auth.isAdmin" type="primary" @click="openCreate">
        + 在该供应商下新建采购件
      </el-button>
    </div>
    <el-table :data="rows" v-loading="loading">
      <el-table-column prop="code" label="件号" width="130">
        <template #default="{ row }">
          <el-button text type="primary" class="cell-link" @click="openDetail(row)">{{ row.code }}</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="件名" min-width="170">
        <template #default="{ row }">
          <el-button text type="primary" class="cell-link" @click="openDetail(row)">{{ row.name }}</el-button>
        </template>
      </el-table-column>
      <el-table-column v-if="!scoped" prop="supplier_name" label="供应商" width="130" />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" :type="kindOf(row.node_type_id) === 'product' ? 'warning' : 'info'">
            {{ kindOf(row.node_type_id) === 'product' ? '整机' : '部件' }}
          </el-tag>
          <span style="margin-left: 4px">{{ row.node_type_name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="参考交期" width="90">
        <template #default="{ row }">{{ row.lead_time_days != null ? `${row.lead_time_days} 天` : '—' }}</template>
      </el-table-column>
      <el-table-column prop="reference_count" label="被引用" width="74" />
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
      <el-table-column label="规格" width="100">
        <template #default="{ row }">
          <el-button
            v-if="['draft', 'active'].includes(row.status)" size="small" text type="primary"
            @click="router.push({ path: '/configure', query: { part_spec_id: row.id } })"
          >{{ row.spec_config || row.spec_note ? '规格✓ 编辑' : '+ 规格' }}</el-button>
        </template>
      </el-table-column>
      <el-table-column label="操作" :width="auth.isAdmin ? 290 : 80">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <template v-if="auth.isAdmin">
            <el-button v-if="['draft', 'active'].includes(row.status)" size="small" type="primary" plain @click="openEdit(row)">编辑</el-button>
            <el-button v-if="row.status === 'draft'" size="small" type="success" @click="approve(row)">转正</el-button>
            <el-button v-if="['draft', 'active'].includes(row.status)" size="small" @click="merge(row)">合并</el-button>
            <el-button v-if="['draft', 'active'].includes(row.status)" size="small" type="danger" plain @click="retire(row)">停用</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <p style="color: var(--el-text-color-secondary); font-size: 12px">
      业务员在配置看板现场新建的件为「草稿」，可直接用于配置；管理员在此审核转正、合并重复或停用。
    </p>

    <el-dialog v-model="createDialog.visible" title="新建采购件" width="520">
      <el-form label-width="90px">
        <el-form-item label="采购大类">
          <el-radio-group v-model="createDialog.form.kind" @change="onKindChange">
            <el-radio-button value="part">部件采购件</el-radio-button>
            <el-radio-button value="product">整机采购件</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="createDialog.form.kind === 'product' ? '整机品类' : '部件类型'" required>
          <el-select
            v-model="createDialog.form.node_type_id" filterable style="width: 100%"
            :placeholder="createDialog.form.kind === 'product' ? '选择整机品类（取自产品模板）' : '选择部件类型'"
            @change="scheduleSimilar"
          >
            <el-option v-for="t in createTypeOptions" :key="t.id" :value="t.id" :label="t.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="件名" required>
          <el-input
            v-model="createDialog.form.name" @input="scheduleSimilar"
            :placeholder="createDialog.form.kind === 'product' ? '如 华消2kg干粉整机（件号自动生成）' : '如 华消K2阀门（件号自动生成）'"
          />
        </el-form-item>
        <el-alert
          v-if="similarItems.length" type="warning" :closable="false" show-icon style="margin: 0 0 12px 0"
          :title="`已有 ${similarItems.length} 个相似件，请确认不是重复建档`"
        >
          <div style="font-size: 12px; line-height: 1.7">
            <div v-for="s in similarItems.slice(0, 5)" :key="s.id">
              <span style="font-family: monospace">{{ s.code }}</span> · {{ s.name }}
              <span style="color: var(--el-text-color-secondary)">（{{ s.supplier_name }}）</span>
            </div>
          </div>
        </el-alert>
        <el-form-item label="参考交期">
          <el-input-number v-model="createDialog.form.lead_time_days" :min="0" :max="3650" placeholder="天" /> 天
          <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">缺省取供应商默认交期</span>
        </el-form-item>
        <el-form-item label="规格备注">
          <el-input
            v-model="createDialog.form.spec_note" type="textarea" :rows="2"
            placeholder="选填：灰盒描述规格（仅描述，不入指纹/报价）；完整规格树可稍后在详情维护"
          />
        </el-form-item>
        <p v-if="createDialog.form.kind === 'product'" style="margin: 0; font-size: 12px; color: var(--el-text-color-secondary)">
          整机采购件 = 整台直接外购的成品，可在配置看板用「整机直采」一键生成可售 SKU。
        </p>
      </el-form>
      <template #footer>
        <el-button @click="createDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <PartDetailDrawer
      v-model="detail.visible" :part-id="detail.partId" :edit-on-load="detail.editOnLoad"
      @changed="onDetailChanged"
    />
  </div>
</template>

<style scoped>
.cell-link { padding: 0; height: auto; font-weight: 500; }
.cell-link :deep(span) { white-space: normal; text-align: left; }
</style>
