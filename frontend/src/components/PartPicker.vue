<script setup lang="ts">
/** 成品采购件选择器：按槽的部件类型预过滤；可现场新建（强制相似查重）。 */
import { ElMessage } from 'element-plus'
import { onMounted, ref, watch } from 'vue'

import { api } from '../api/client'

const props = defineProps<{
  visible: boolean
  nodeTypeId: number
  slotName: string
}>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'selected', part: { id: number; label: string }): void
}>()

const search = ref('')
const rows = ref<any[]>([])
const loading = ref(false)
const creating = ref(false)
const suppliers = ref<any[]>([])
const similar = ref<any[]>([])
const form = ref({ supplier_id: null as number | null, new_supplier_name: '', name: '', spec_note: '' })

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/purchased-parts', {
      params: { node_type_id: props.nodeTypeId, q: search.value || undefined, usable_only: true },
    })
    rows.value = data
  } finally {
    loading.value = false
  }
}

watch(() => props.visible, (v) => {
  if (v) {
    creating.value = false
    search.value = ''
    void load()
  }
}, { immediate: true })  // immediate：整机直采时 picker 挂载即 visible=true，无变化事件，须立即加载
watch(search, () => void load())

onMounted(async () => {
  const { data } = await api.get('/suppliers')
  suppliers.value = data
})

let similarTimer: ReturnType<typeof setTimeout> | null = null
watch(() => form.value.name, (name) => {
  if (similarTimer) clearTimeout(similarTimer)
  if (!name) {
    similar.value = []
    return
  }
  similarTimer = setTimeout(async () => {
    const { data } = await api.get('/purchased-parts/similar', {
      params: { node_type_id: props.nodeTypeId, name },
    })
    similar.value = data
  }, 400)
})

function partSpec(row: any): string {
  return [row.spec_summary, row.spec_note].filter(Boolean).join('；')
}
function pick(row: any) {
  const spec = partSpec(row)
  // 把规格并入 label：配置看板槽位与 SKU 即可见（灰盒渐进披露），spec 仅描述不入指纹
  const label = `${row.supplier_name} | ${row.name}${spec ? `（规格：${spec}）` : ''}`
  emit('selected', { id: row.id, label })
  emit('update:visible', false)
}

async function create() {
  if (!form.value.name || (!form.value.supplier_id && !form.value.new_supplier_name)) {
    ElMessage.warning('请填写件名并选择/填写供应商')
    return
  }
  try {
    const { data } = await api.post('/purchased-parts', {
      node_type_id: props.nodeTypeId,
      supplier_id: form.value.supplier_id,
      new_supplier_name: form.value.supplier_id ? null : form.value.new_supplier_name,
      name: form.value.name,
      spec_note: form.value.spec_note || null,
    })
    ElMessage.success(data.status === 'draft' ? '已建为草稿件（待管理员审核），本次可直接使用' : '成品件已建档')
    pick(data)
  } catch { /* 拦截器已提示 */ }
}
</script>

<template>
  <el-dialog
    :model-value="visible" width="720" :title="`选用成品采购件 — ${slotName}`"
    @update:model-value="emit('update:visible', $event)"
  >
    <template v-if="!creating">
      <el-input v-model="search" placeholder="按供应商 / 件名搜索…" clearable style="margin-bottom: 10px" />
      <el-table :data="rows" v-loading="loading" height="320" @row-dblclick="pick">
        <el-table-column prop="name" label="件名" min-width="150" />
        <el-table-column prop="supplier_name" label="供应商" width="120" />
        <el-table-column label="规格" min-width="160">
          <template #default="{ row }">
            <span v-if="partSpec(row)" style="font-size: 12px; color: var(--el-text-color-secondary)">{{ partSpec(row) }}</span>
            <span v-else style="font-size: 12px; color: var(--el-text-color-placeholder)">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="reference_count" label="被引用" width="70" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'warning'" size="small">
              {{ row.status === 'active' ? '正式' : '草稿' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column width="90">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="pick(row)">选用</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top: 12px; text-align: center">
        没找到？<el-button text type="primary" @click="creating = true">新建成品采购件</el-button>
      </div>
    </template>

    <template v-else>
      <el-form label-width="90px">
        <el-form-item label="供应商">
          <el-select v-model="form.supplier_id" placeholder="选择已有供应商" clearable filterable style="width: 100%">
            <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.name" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!form.supplier_id" label="新供应商">
          <el-input v-model="form.new_supplier_name" placeholder="供应商名称（自动建档）" />
        </el-form-item>
        <el-form-item label="件名" required>
          <el-input v-model="form.name" placeholder="如：K2 阀门总成" />
        </el-form-item>
        <el-form-item label="规格备注">
          <el-input v-model="form.spec_note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="similar.length" type="warning" :closable="false" style="margin-bottom: 10px"
        title="发现相似件，请确认不是同一个（点击可直接选用）："
      >
        <div v-for="p in similar" :key="p.id">
          <el-button text type="primary" size="small" @click="pick(p)">
            {{ p.supplier_name }} | {{ p.name }}（被 {{ p.reference_count }} 个 SKU 引用）
          </el-button>
        </div>
      </el-alert>
      <div style="text-align: right">
        <el-button @click="creating = false">返回列表</el-button>
        <el-button type="primary" @click="create">确认新建并选用</el-button>
      </div>
    </template>
  </el-dialog>
</template>
