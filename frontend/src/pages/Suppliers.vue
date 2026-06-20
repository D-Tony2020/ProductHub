<script setup lang="ts">
/** 供应商管理：左导航替换"成品采购件"并吸纳之。
 *  master-detail（供应商列表 + 详情 Tab：概览 / 成品采购件 / 关联成品），
 *  外加"全部采购件"全局搜索模式。供应商 code 已入指纹·不可变（编辑只给 name/联系/采购字段）。 */
import { Filter, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import PartsTable from '../components/PartsTable.vue'
import StatCard from '../components/StatCard.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
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
  // overview 带用量指标（采购项/整机供应/部件供应/关联成品），含已停用
  suppliers.value = (await api.get('/suppliers/overview')).data
  const wantId = keepSelId ?? selected.value?.id
  if (wantId) selected.value = suppliers.value.find((s) => s.id === wantId) ?? null
  if (!selected.value && suppliers.value.length) selected.value = suppliers.value[0]
}

onMounted(() => loadSuppliers().catch(() => { /* 401 由拦截器跳转登录 */ }))

function selectSupplier(s: any) {
  selected.value = s
  tab.value = 'overview'
}

// KPI 仪表点击跳转：采购项/整机供应/部件供应 → 成品采购件 Tab(带大类预筛)；关联成品 → 关联成品 Tab
const partsKind = ref<'product' | 'part' | null>(null)
function goParts(kind: 'product' | 'part' | null) {
  partsKind.value = kind
  tab.value = 'parts'
}

// 关联成品：用到该供应商的在售 SKU（黑盒经成品件 ∪ 白盒节点标注），支持下钻到产品详情
const linkedSkus = ref<any[]>([])
const linkedLoading = ref(false)
async function loadLinked() {
  if (!selected.value) return
  linkedLoading.value = true
  try {
    linkedSkus.value = (await api.get(`/suppliers/${selected.value.id}/linked-skus`)).data
  } finally {
    linkedLoading.value = false
  }
}
function drillSku(skuId: number) {
  router.push({ path: '/skus', query: { sku_id: skuId } })  // 下钻：跳产品库并打开该 SKU 详情
}
// 并轨：跳产品库并按本供应商（黑∪白·在售）预筛，享完整分面筛选/排序/分页
function openInLibrary() {
  if (!selected.value) return
  router.push({ path: '/skus', query: { supplier: selected.value.id, status: 'active' } })
}
// 进入「关联成品」Tab 或切换供应商时按需加载
watch([tab, () => selected.value?.id], ([t]) => {
  if (t === 'skus') loadLinked()
})

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
    <el-col :span="6" :xs="24">
      <el-card body-style="padding: 12px">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
          <span style="font-size: 13px; color: var(--el-text-color-secondary)">供应商</span>
          <el-button v-if="auth.isAdmin" size="small" type="primary" @click="createDialog.visible = true">新建</el-button>
        </div>
        <el-input v-model="search" placeholder="搜索名称 / 编码" clearable size="small" style="margin-bottom: 8px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div
          v-for="s in filtered" :key="s.id" class="sup-card"
          :class="{ active: selected?.id === s.id, inactive: !s.is_active }"
          @click="selectSupplier(s)"
        >
          <div class="sc-top">
            <span class="sc-name" :title="s.name">{{ s.name }}</span>
            <el-tag v-if="!s.is_active" size="small" type="info" class="sc-flag">已停用</el-tag>
          </div>
          <el-rate v-if="s.rating" :model-value="s.rating" disabled size="small" class="sc-rate" />
          <div class="sc-metrics">
            <div class="m"><b>{{ s.procurement_items }}</b><span>采购</span></div>
            <div class="m"><b>{{ s.assembly_count }}</b><span>整机</span></div>
            <div class="m"><b>{{ s.component_count }}</b><span>部件</span></div>
            <div class="m"><b>{{ s.linked_skus }}</b><span>关联</span></div>
          </div>
        </div>
        <el-empty v-if="!filtered.length" :image-size="50" description="无供应商" />
      </el-card>
    </el-col>

    <el-col :span="18" :xs="24">
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

        <!-- 看板指标卡（四个均可点击跳转到对应视图） -->
        <div class="dash">
          <StatCard
            label="采购项" tone="brand" :value="selected.procurement_items" clickable
            :active="tab === 'parts' && partsKind === null" @click="goParts(null)"
          />
          <StatCard
            label="整机供应" tone="info" :value="selected.assembly_count" clickable
            :active="tab === 'parts' && partsKind === 'product'" @click="goParts('product')"
          />
          <StatCard
            label="部件供应" tone="warning" :value="selected.component_count" clickable
            :active="tab === 'parts' && partsKind === 'part'" @click="goParts('part')"
          />
          <StatCard
            label="关联成品" hint="在售SKU" tone="success" :value="selected.linked_skus" clickable
            :active="tab === 'skus'" @click="tab = 'skus'"
          />
        </div>

        <el-tabs v-model="tab">
          <el-tab-pane label="概览" name="overview">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="名称">{{ selected.name }}</el-descriptions-item>
              <el-descriptions-item label="编码">{{ selected.code }}</el-descriptions-item>
              <el-descriptions-item label="联系方式">{{ selected.contact || '—' }}</el-descriptions-item>
              <el-descriptions-item label="默认参考交期">{{ selected.lead_time_days != null ? `${selected.lead_time_days} 天` : '—' }}</el-descriptions-item>
              <el-descriptions-item label="付款条件">{{ selected.payment_terms || '—' }}</el-descriptions-item>
              <el-descriptions-item label="评级">
                <el-rate v-if="selected.rating" :model-value="selected.rating" disabled />
                <span v-else>—</span>
              </el-descriptions-item>
            </el-descriptions>
            <p style="color: var(--el-text-color-secondary); font-size: 12px; margin-top: 8px">
              <b>默认参考交期</b>为该供应商的标称默认值，新建采购件时预填、每件可覆盖（权威值在件上）；
              <b>非每批订单的实际承诺</b>。付款条件/评级为关系级条款。
            </p>
          </el-tab-pane>

          <el-tab-pane label="成品采购件" name="parts">
            <PartsTable
              :supplier-id="selected.id" :supplier-default-lead="selected.lead_time_days"
              :kind="partsKind" @changed="loadSuppliers(selected.id)"
            />
          </el-tab-pane>

          <el-tab-pane label="关联成品" name="skus">
            <div v-loading="linkedLoading">
              <div class="linked-head">
                <span class="lh-note">用到该供应商的在售 SKU · 黑盒经成品件 ∪ 白盒节点标注</span>
                <el-button type="primary" plain :icon="Filter" @click="openInLibrary">
                  在产品库筛选 / 排序（{{ selected.linked_skus }}）→
                </el-button>
              </div>
              <el-table
                v-if="linkedSkus.length" :data="linkedSkus" class="linked-tbl"
                @row-click="(r: any) => drillSku(r.sku_id)"
              >
                <el-table-column prop="sku_code" label="SKU 编码" width="160">
                  <template #default="{ row }">
                    <el-button text type="primary" class="cell-link" @click.stop="drillSku(row.sku_id)">
                      {{ row.sku_code }}
                    </el-button>
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称 / 规格摘要" min-width="240" show-overflow-tooltip />
                <el-table-column label="该供应商在此 SKU 的用法" min-width="220">
                  <template #default="{ row }">
                    <el-tag
                      v-for="p in row.via_blackbox" :key="p" size="small" type="primary"
                      effect="plain" class="src-tag"
                    >黑盒 · {{ p }}</el-tag>
                    <el-tag v-if="row.via_whitebox" size="small" type="success" effect="plain" class="src-tag">
                      白盒来源标注
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="" width="90" align="right">
                  <template #default="{ row }">
                    <el-button size="small" text type="primary" @click.stop="drillSku(row.sku_id)">下钻 →</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-else :image-size="60" description="暂无用到该供应商的在售 SKU" />
              <p style="color: var(--el-text-color-secondary); font-size: 12px; margin-top: 8px">
                点任意行可<b>下钻</b>到产品详情；需筛选 / 排序 / 翻页请用上方「在产品库」入口。
              </p>
            </div>
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
      <el-form-item label="默认参考交期">
        <el-input-number v-model="editForm.lead_time_days" :min="0" :max="3650" placeholder="天" /> 天
        <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">新建采购件预填，件可覆盖</span>
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
      <el-form-item label="默认参考交期">
        <el-input-number v-model="createDialog.form.lead_time_days" :min="0" :max="3650" placeholder="天" /> 天
        <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">新建采购件预填，件可覆盖</span>
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
/* 左侧供应商卡片（带用量指标） */
.sup-card { padding: 10px 10px 8px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; border: 1px solid var(--el-border-color-lighter); transition: all .15s; }
.sup-card:hover { border-color: var(--el-color-primary-light-5); background: var(--el-fill-color-light); }
.sup-card.active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.sup-card.inactive { opacity: 0.55; }
.sc-top { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.sc-name { font-size: 14px; font-weight: 600; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sc-flag { flex-shrink: 0; }
.sc-rate { height: 14px; margin: -2px 0 6px; }
.sc-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
.sc-metrics .m { text-align: center; background: var(--el-fill-color); border-radius: 5px; padding: 4px 2px; }
.sc-metrics .m b { display: block; font-size: 15px; font-weight: 600; color: var(--el-color-primary); line-height: 1.2; font-variant-numeric: tabular-nums; }
.sc-metrics .m span { font-size: 10px; color: var(--el-text-color-secondary); white-space: nowrap; }

/* 右侧看板指标卡（StatCard 统一） */
.dash { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
@media (max-width: 768px) {
  .dash, .sc-metrics { grid-template-columns: repeat(2, 1fr); }
}

/* 关联成品：桥接产品库的入口条 + 表整行可下钻 */
.linked-head {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--el-border-color-lighter);
}
.lh-note { font-size: 12px; color: var(--el-text-color-secondary); }
.linked-tbl :deep(.el-table__row) { cursor: pointer; }
.cell-link { padding: 0; height: auto; font-weight: 500; font-family: var(--ph-font-mono); }
.cell-link :deep(span) { white-space: normal; }
.src-tag { margin: 2px 4px 2px 0; }
</style>
