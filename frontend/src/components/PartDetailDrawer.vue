<script setup lang="ts">
/** 采购件详情抽屉（可复用）：完整信息 + 参考交期 + 灰盒规格 + 关联在售 SKU + 编辑入口。
 *  在 PartsTable 的「件号/件名/详情」点击后滑出；供应商作用域与全部采购件两处共用。 */
import { ArrowRight } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const props = defineProps<{ modelValue: boolean; partId: number | null; editOnLoad?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'changed'): void }>()

const part = ref<any | null>(null)
const loading = ref(false)

const statusMap: Record<string, { label: string; type: string }> = {
  draft: { label: '草稿（待审核）', type: 'warning' },
  active: { label: '正式', type: 'success' },
  merged: { label: '已合并', type: 'info' },
  retired: { label: '已停用', type: 'info' },
}

async function load() {
  if (props.partId == null) return
  loading.value = true
  try {
    part.value = (await api.get(`/purchased-parts/by-id/${props.partId}`)).data
    if (props.editOnLoad && editable()) openEdit()
  } catch {
    ElMessage.error('加载采购件详情失败')
    close()
  } finally {
    loading.value = false
  }
}

watch(() => [props.modelValue, props.partId], ([open]) => {
  if (open && props.partId != null) load()
})

function close() {
  emit('update:modelValue', false)
}

function openSku(s: any) {
  close()
  router.push({ path: '/skus', query: { sku_id: s.id } })
}

function editSpec() {
  if (!part.value) return
  close()
  router.push({ path: '/configure', query: { part_spec_id: part.value.id } })
}

// 编辑基本信息（件名 / 参考交期）——admin
const editDialog = reactive({ visible: false, name: '', lead_time_days: null as number | null, saving: false })
function openEdit() {
  if (!part.value) return
  editDialog.name = part.value.name
  editDialog.lead_time_days = part.value.lead_time_days ?? null
  editDialog.visible = true
}
async function saveEdit() {
  if (!part.value) return
  if (!editDialog.name.trim()) {
    ElMessage.warning('请填写件名')
    return
  }
  editDialog.saving = true
  try {
    await api.patch(`/purchased-parts/${part.value.id}`, {
      name: editDialog.name.trim(),
      lead_time_days: editDialog.lead_time_days ?? undefined,
    })
    editDialog.visible = false
    ElMessage.success('已保存')
    await load()
    emit('changed')
  } catch {
    ElMessage.error('保存失败，请检查输入（交期为非负天数）')
  } finally {
    editDialog.saving = false
  }
}

const editable = () => part.value && ['draft', 'active'].includes(part.value.status)
const isAssembly = () => part.value?.node_type_kind === 'product'

// 整机直采：整台外购成品直接生成可售 SKU（仅整机件）
const creatingSku = ref(false)
async function createDirectSku() {
  if (!part.value) return
  try {
    await ElMessageBox.confirm(
      `将整机采购件「${part.value.name}」整台直接作为可售 SKU（整机直采，无需逐项配置；`
      + `整机的描述规格随灰盒带入，不入指纹/报价）。继续？`,
      '整机直采', { confirmButtonText: '生成 SKU', type: 'info' },
    )
  } catch { return }
  creatingSku.value = true
  try {
    const { data } = await api.post('/skus', {
      config: { root_type_id: part.value.node_type_id, root_purchased_part_id: part.value.id },
    })
    if (data.created) ElMessage.success(`已创建整机直采 ${data.sku.sku_code}`)
    else ElMessage.warning(`该整机已存在 SKU：${data.sku.sku_code}`)
    close()
    router.push({ path: '/skus', query: { sku_id: data.sku.id } })
  } catch { /* 拦截器提示 */ } finally {
    creatingSku.value = false
  }
}
</script>

<template>
  <el-drawer
    :model-value="modelValue" title="采购件详情" size="540px" direction="rtl"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading">
      <template v-if="part">
        <!-- 标题区 -->
        <div class="pd-head">
          <div class="pd-title">{{ part.name }}</div>
          <div class="pd-sub">
            <span class="mono">{{ part.code }}</span>
            <el-tag size="small" effect="plain" :type="isAssembly() ? 'warning' : 'info'">{{ isAssembly() ? '整机' : '部件' }}</el-tag>
            <el-tag :type="statusMap[part.status]?.type as any" size="small">{{ statusMap[part.status]?.label }}</el-tag>
            <span v-if="part.merged_into_id" class="muted">→ 合并至 #{{ part.merged_into_id }}</span>
          </div>
        </div>

        <!-- 关键指标卡 -->
        <div class="pd-stats">
          <div class="pd-stat">
            <div class="pd-stat-num">{{ part.lead_time_days != null ? part.lead_time_days : '—' }}<span v-if="part.lead_time_days != null" class="unit">天</span></div>
            <div class="pd-stat-label">参考交期</div>
          </div>
          <div class="pd-stat">
            <div class="pd-stat-num">{{ part.reference_count }}</div>
            <div class="pd-stat-label">被引用 SKU</div>
          </div>
          <div class="pd-stat">
            <div class="pd-stat-num">{{ part.node_type_name }}</div>
            <div class="pd-stat-label">{{ isAssembly() ? '整机品类' : '部件类型' }}</div>
          </div>
        </div>

        <!-- 基本信息 -->
        <el-descriptions :column="1" border size="small" style="margin-bottom: 16px">
          <el-descriptions-item label="供应商">{{ part.supplier_name }}</el-descriptions-item>
          <el-descriptions-item label="件号">{{ part.code }}</el-descriptions-item>
          <el-descriptions-item label="参考交期">{{ part.lead_time_days != null ? `${part.lead_time_days} 天` : '— 未设置' }}</el-descriptions-item>
        </el-descriptions>

        <!-- 灰盒规格 -->
        <div class="pd-section">
          <div class="pd-section-head">
            <span>规格描述</span>
            <el-button v-if="editable()" size="small" text type="primary" @click="editSpec">
              {{ part.spec_config || part.spec_note ? '编辑规格' : '+ 补充规格' }}
            </el-button>
          </div>
          <div v-if="part.spec_summary" class="pd-spec">{{ part.spec_summary }}</div>
          <div v-if="part.spec_note" class="pd-note">{{ part.spec_note }}</div>
          <el-empty v-if="!part.spec_summary && !part.spec_note" :image-size="40" description="暂无规格（规格仅描述，不入指纹/报价）" />
        </div>

        <!-- 关联在售 SKU -->
        <div class="pd-section">
          <div class="pd-section-head">
            <span>关联在售整机 SKU（{{ part.linked_skus.length }}）</span>
          </div>
          <div v-if="part.linked_skus.length">
            <div v-for="s in part.linked_skus" :key="s.id" class="pd-sku" @click="openSku(s)">
              <span class="mono">{{ s.sku_code }}</span>
              <span class="pd-sku-name">{{ s.name }}</span>
              <el-icon class="muted"><ArrowRight /></el-icon>
            </div>
          </div>
          <el-empty v-else :image-size="40" description="尚无在售整机引用此件" />
        </div>
      </template>
    </div>

    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button
        v-if="isAssembly() && editable()" type="success" :loading="creatingSku" @click="createDirectSku"
      >生成整机直采 SKU</el-button>
      <el-button v-if="auth.isAdmin && editable()" type="primary" @click="openEdit">编辑</el-button>
    </template>
  </el-drawer>

  <!-- 编辑基本信息 -->
  <el-dialog v-model="editDialog.visible" title="编辑采购件" width="440" append-to-body>
    <el-form label-width="90px">
      <el-form-item label="件名" required><el-input v-model="editDialog.name" /></el-form-item>
      <el-form-item label="参考交期">
        <el-input-number v-model="editDialog.lead_time_days" :min="0" :max="3650" placeholder="天" /> 天
        <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">权威交期在件上</span>
      </el-form-item>
      <p style="font-size: 12px; color: var(--el-text-color-secondary); margin: 0">
        供应商不可改（已入指纹·红线）；如需改供应商请新建采购件。规格在「编辑规格」中维护。
      </p>
    </el-form>
    <template #footer>
      <el-button @click="editDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="editDialog.saving" @click="saveEdit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mono { font-family: monospace; }
.muted { color: var(--el-text-color-placeholder); font-size: 12px; }
.pd-head { margin-bottom: 16px; }
.pd-title { font-size: 18px; font-weight: 600; margin-bottom: 6px; }
.pd-sub { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.pd-stats { display: flex; gap: 10px; margin-bottom: 16px; }
.pd-stat { flex: 1; background: var(--el-fill-color-light); border-radius: 8px; padding: 12px; text-align: center; }
.pd-stat-num { font-size: 20px; font-weight: 600; color: var(--el-color-primary); line-height: 1.3; }
.pd-stat-num .unit { font-size: 12px; font-weight: 400; margin-left: 2px; }
.pd-stat-label { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px; }
.pd-section { margin-bottom: 18px; }
.pd-section-head { display: flex; justify-content: space-between; align-items: center; font-weight: 600; font-size: 14px; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid var(--el-border-color-lighter); }
.pd-spec { font-size: 13px; line-height: 1.6; }
.pd-note { font-size: 13px; line-height: 1.6; color: var(--el-text-color-secondary); white-space: pre-wrap; margin-top: 4px; }
.pd-sku { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.pd-sku:hover { background: var(--el-fill-color-light); }
.pd-sku-name { flex: 1; color: var(--el-text-color-regular); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
