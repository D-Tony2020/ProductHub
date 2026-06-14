<script setup lang="ts">
/** 供应商管理：左导航替换"成品采购件"并吸纳之。
 *  master-detail（供应商列表 + 详情 Tab：概览 / 成品采购件 / 关联成品），
 *  外加"全部采购件"全局搜索模式。供应商 code 已入指纹·不可变（编辑只给 name/联系/采购字段）。 */
import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'
import PartsTable from '../components/PartsTable.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const mode = ref<'by_supplier' | 'all_parts'>('by_supplier')
const suppliers = ref<any[]>([])
const selected = ref<any | null>(null)
const search = ref('')
const tab = ref('overview')

const filtered = computed(() => {
  const kw = search.value.trim().toLowerCase()
  if (!kw) return suppliers.value
  return suppliers.value.filter((s) => s.name.toLowerCase().includes(kw) || s.code.toLowerCase().includes(kw))
})

async function loadSuppliers(keepSelId?: number) {
  suppliers.value = (await api.get('/suppliers', { params: { include_inactive: true } })).data
  if (keepSelId) selected.value = suppliers.value.find((s) => s.id === keepSelId) ?? null
  if (!selected.value && suppliers.value.length) selected.value = suppliers.value[0]
}

onMounted(() => loadSuppliers().catch(() => { /* 401 由拦截器跳转登录 */ }))

function selectSupplier(s: any) {
  selected.value = s
  tab.value = 'overview'
}

// 概览编辑
const editForm = reactive({ name: '', contact: '', lead_time_days: null as number | null, payment_terms: '', rating: null as number | null })
const editing = ref(false)
function startEdit() {
  if (!selected.value) return
  editForm.name = selected.value.name
  editForm.contact = selected.value.contact ?? ''
  editForm.lead_time_days = selected.value.lead_time_days ?? null
  editForm.payment_terms = selected.value.payment_terms ?? ''
  editForm.rating = selected.value.rating ?? null
  editing.value = true
}
async function saveEdit() {
  if (!selected.value) return
  if (!editForm.name.trim()) {
    ElMessage.warning('请填写供应商名称')
    return
  }
  try {
    await api.patch(`/suppliers/${selected.value.id}`, {
      name: editForm.name.trim(),
      contact: editForm.contact || null,
      lead_time_days: editForm.lead_time_days ?? null,
      payment_terms: editForm.payment_terms || null,
      rating: editForm.rating || null,  // el-rate 未评为 0 → 转 null（后端 rating∈[1,5]）
    })
    editing.value = false
    ElMessage.success('已保存')
    await loadSuppliers(selected.value.id)
  } catch {
    ElMessage.error('保存失败，请检查输入（评级须 1–5 星或留空，交期为非负天数）')
  }
}

async function toggleActive() {
  if (!selected.value) return
  const s = selected.value
  if (s.is_active) {
    await ElMessageBox.confirm(
      `停用供应商「${s.name}」？停用后不可用于新配置（既有 SKU 与指纹不受影响）。`
      + '若其名下仍有在用成品件或被在售 SKU 标注，建议先处理。',
      '停用供应商', { type: 'warning' },
    )
  }
  await api.patch(`/suppliers/${s.id}`, { is_active: !s.is_active })
  await loadSuppliers(s.id)
}

// 新建供应商（code 后端自动生成）
const createDialog = reactive({
  visible: false,
  form: { name: '', contact: '', lead_time_days: null as number | null, payment_terms: '', rating: null as number | null },
})
async function submitCreate() {
  if (!createDialog.form.name.trim()) {
    ElMessage.warning('请填写供应商名称')
    return
  }
  try {
    const { data } = await api.post('/suppliers', {
      name: createDialog.form.name.trim(),
      contact: createDialog.form.contact || null,
      lead_time_days: createDialog.form.lead_time_days ?? null,
      payment_terms: createDialog.form.payment_terms || null,
      rating: createDialog.form.rating || null,  // el-rate 未评为 0 → 转 null
    })
    createDialog.visible = false
    createDialog.form = { name: '', contact: '', lead_time_days: null, payment_terms: '', rating: null }
    ElMessage.success('已创建')
    await loadSuppliers(data.id)
  } catch {
    ElMessage.error('创建失败，请检查输入（评级须 1–5 星或留空，交期为非负天数）')
  }
}
</script>

<template>
  <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px">
    <el-radio-group v-model="mode">
      <el-radio-button value="by_supplier">按供应商</el-radio-button>
      <el-radio-button value="all_parts">全部采购件</el-radio-button>
    </el-radio-group>
    <span style="font-size: 12px; color: var(--el-text-color-secondary)">
      贸易公司采购视角：供应商为一等公民，成品采购件归于其下
    </span>
  </div>

  <!-- 全部采购件：跨供应商全局搜索 -->
  <el-card v-if="mode === 'all_parts'">
    <PartsTable />
  </el-card>

  <!-- 按供应商：master-detail -->
  <el-row v-else :gutter="12">
    <el-col :span="6">
      <el-card body-style="padding: 12px">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
          <span style="font-size: 13px; color: var(--el-text-color-secondary)">供应商</span>
          <el-button v-if="auth.isAdmin" size="small" type="primary" @click="createDialog.visible = true">新建</el-button>
        </div>
        <el-input v-model="search" placeholder="搜索名称 / 编码" clearable size="small" style="margin-bottom: 8px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div
          v-for="s in filtered" :key="s.id" class="sup-item"
          :class="{ active: selected?.id === s.id, inactive: !s.is_active }"
          @click="selectSupplier(s)"
        >
          <div class="sup-name">
            {{ s.name }}
            <el-tag v-if="!s.is_active" size="small" type="info">已停用</el-tag>
            <el-rate v-if="s.rating" :model-value="s.rating" disabled size="small" style="height: 16px" />
          </div>
          <div class="sup-meta">{{ s.code }}<span v-if="s.lead_time_days"> · 参考交期 {{ s.lead_time_days }}天</span></div>
        </div>
        <el-empty v-if="!filtered.length" :image-size="50" description="无供应商" />
      </el-card>
    </el-col>

    <el-col :span="18">
      <el-card v-if="selected">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>
              {{ selected.name }}
              <span style="font-size: 12px; color: var(--el-text-color-placeholder); font-family: monospace">
                {{ selected.code }} · code 不可变
              </span>
              <el-tag v-if="!selected.is_active" size="small" type="info" style="margin-left: 6px">已停用</el-tag>
            </span>
            <span v-if="auth.isAdmin">
              <el-button size="small" @click="startEdit">编辑</el-button>
              <el-button size="small" :type="selected.is_active ? 'danger' : 'success'" plain @click="toggleActive">
                {{ selected.is_active ? '停用' : '启用' }}
              </el-button>
            </span>
          </div>
        </template>

        <el-tabs v-model="tab">
          <el-tab-pane label="概览" name="overview">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="名称">{{ selected.name }}</el-descriptions-item>
              <el-descriptions-item label="编码">{{ selected.code }}</el-descriptions-item>
              <el-descriptions-item label="联系方式">{{ selected.contact || '—' }}</el-descriptions-item>
              <el-descriptions-item label="参考交期">{{ selected.lead_time_days != null ? `${selected.lead_time_days} 天` : '—' }}</el-descriptions-item>
              <el-descriptions-item label="付款条件">{{ selected.payment_terms || '—' }}</el-descriptions-item>
              <el-descriptions-item label="评级">
                <el-rate v-if="selected.rating" :model-value="selected.rating" disabled />
                <span v-else>—</span>
              </el-descriptions-item>
            </el-descriptions>
            <p style="color: var(--el-text-color-secondary); font-size: 12px; margin-top: 8px">
              参考交期为该供应商的<b>标称默认值</b>（用于报价估发货期、横向比选供应商、卷算整机交期），
              <b>非每批订单的实际承诺</b>——每批实际交期随数量/排产而变，属采购订单层。付款条件为关系级标准条款。
            </p>
          </el-tab-pane>

          <el-tab-pane label="成品采购件" name="parts">
            <PartsTable :supplier-id="selected.id" @changed="loadSuppliers(selected.id)" />
          </el-tab-pane>

          <el-tab-pane label="关联成品" name="skus">
            <el-empty description="P2b 将在此展示用到该供应商的整机 SKU（含白盒来源标注），并支持下钻" :image-size="60" />
          </el-tab-pane>
        </el-tabs>
      </el-card>
      <el-empty v-else description="左侧选择一个供应商" />
    </el-col>
  </el-row>

  <!-- 编辑供应商（不含 code） -->
  <el-dialog v-model="editing" title="编辑供应商" width="460">
    <el-form label-width="90px">
      <el-form-item label="名称" required><el-input v-model="editForm.name" /></el-form-item>
      <el-form-item label="联系方式"><el-input v-model="editForm.contact" placeholder="联系人 / 电话（可空）" /></el-form-item>
      <el-form-item label="参考交期">
        <el-input-number v-model="editForm.lead_time_days" :min="0" :max="3650" placeholder="天" /> 天
        <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">标称默认值，非每批承诺</span>
      </el-form-item>
      <el-form-item label="付款条件"><el-input v-model="editForm.payment_terms" placeholder="如 30% 预付，70% 见提单" /></el-form-item>
      <el-form-item label="评级"><el-rate v-model="editForm.rating" clearable /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editing = false">取消</el-button>
      <el-button type="primary" @click="saveEdit">保存</el-button>
    </template>
  </el-dialog>

  <!-- 新建供应商（code 自动生成） -->
  <el-dialog v-model="createDialog.visible" title="新建供应商" width="460">
    <el-form label-width="90px">
      <el-form-item label="名称" required><el-input v-model="createDialog.form.name" placeholder="如 华消（编码自动生成）" /></el-form-item>
      <el-form-item label="联系方式"><el-input v-model="createDialog.form.contact" placeholder="联系人 / 电话（可空）" /></el-form-item>
      <el-form-item label="参考交期">
        <el-input-number v-model="createDialog.form.lead_time_days" :min="0" :max="3650" placeholder="天" /> 天
        <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">标称默认值，非每批承诺</span>
      </el-form-item>
      <el-form-item label="付款条件"><el-input v-model="createDialog.form.payment_terms" placeholder="可空" /></el-form-item>
      <el-form-item label="评级"><el-rate v-model="createDialog.form.rating" clearable /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="submitCreate">创建</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.sup-item { padding: 8px 10px; border-radius: 6px; cursor: pointer; margin-bottom: 2px; }
.sup-item:hover { background: var(--el-fill-color-light); }
.sup-item.active { background: var(--el-color-primary-light-9); }
.sup-item.inactive { opacity: 0.55; }
.sup-name { font-size: 14px; display: flex; align-items: center; gap: 6px; }
.sup-meta { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
</style>
