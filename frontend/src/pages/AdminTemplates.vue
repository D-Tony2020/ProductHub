<script setup lang="ts">
/** 产品模板管理（admin）：节点类型 / 属性与选项 / 部件槽。
 *  纪律由后端强制（code 不可变、软停用、引用计数、DAG、可选属性"无"选项禁令），
 *  此页只做呈现与触发。 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'

const types = ref<any[]>([])
const selected = ref<any | null>(null)
const optionRows = reactive<Record<number, any[]>>({})

// code 全部由后端按名称自动生成（拼音转写+查重），UI 不再要求填写
const typeDialog = reactive({ visible: false, form: { name: '', kind: 'part', is_sellable_root: false } })
const attrDialog = reactive({ visible: false, form: { name: '', is_required: true, is_filterable: false } })
const optDialog = reactive({ visible: false, attrId: 0, form: { label: '' } })
const slotDialog = reactive({
  visible: false,
  source: 'existing' as 'existing' | 'new',   // 部件类型来源：选已有 / 现场新建
  form: {
    name: '', child_type_id: null as number | null,
    is_required: true, allow_blackbox: true, variant_group: '',
  },
})

function openSlotDialog() {
  slotDialog.source = 'existing'
  slotDialog.form = { name: '', child_type_id: null, is_required: true, allow_blackbox: true, variant_group: '' }
  slotDialog.visible = true
}

// ---- 在位编辑（仅可变字段；code/所属结构不可改，物理删除不存在）----
const editDialog = reactive({
  visible: false,
  kind: 'attr' as 'type' | 'attr' | 'option' | 'slot',
  id: 0,
  refCount: 0,
  form: {} as Record<string, any>,
})

const EDIT_TITLES = { type: '编辑节点类型', attr: '编辑属性', option: '编辑选项', slot: '编辑部件槽' }

function openEdit(kind: typeof editDialog.kind, row: any, refCount = 0) {
  editDialog.kind = kind
  editDialog.id = row.id
  editDialog.refCount = refCount
  if (kind === 'type') {
    editDialog.form = { name: row.name, is_sellable_root: row.is_sellable_root }
  } else if (kind === 'attr') {
    editDialog.form = {
      name: row.name, unit: row.unit ?? '',
      is_required: row.is_required, is_filterable: row.is_filterable,
    }
  } else if (kind === 'option') {
    editDialog.form = { label: row.label }
  } else {
    editDialog.form = {
      name: row.name, is_required: row.is_required, allow_blackbox: row.allow_blackbox,
      variant_group: row.variant_group ?? '',
    }
  }
  editDialog.visible = true
}

async function saveEdit() {
  const { kind, id } = editDialog
  // 已被 SKU 引用的选项改名：技术安全（编码与指纹不变），但会同步改变历史 SKU 的展示，
  // 必须让管理员区分"纠错"与"换义"
  if (kind === 'option' && editDialog.refCount > 0) {
    try {
      await ElMessageBox.confirm(
        `该选项已被 ${editDialog.refCount} 个 SKU 引用，改名后这些 SKU 的展示会同步变化。`
        + '改名仅用于纠错（错别字、表述规范）；若是换成不同含义（如 4kg 改成 5kg），'
        + '请取消本次操作，新建一个选项并停用旧选项。',
        '改名会影响历史 SKU 的展示',
        { type: 'warning', confirmButtonText: '我确认是纠错改名', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  const urls: Record<string, string> = {
    type: `/template/node-types/${id}`,
    attr: `/template/attributes/${id}`,
    option: `/template/options/${id}`,
    slot: `/template/slots/${id}`,
  }
  const payload = { ...editDialog.form }
  if (payload.unit === '') delete payload.unit
  await api.patch(urls[kind], payload)
  editDialog.visible = false
  await loadTypes()
  if (selected.value) await select(selected.value)
  ElMessage.success('已保存（操作已记录审计）')
}

// ---- 节点类型拖拽排序 ----
const dragIndex = ref<number | null>(null)

function onDragStart(idx: number) {
  dragIndex.value = idx
}

async function onDrop(targetIdx: number) {
  const from = dragIndex.value
  dragIndex.value = null
  if (from === null || from === targetIdx) return
  const moved = types.value.splice(from, 1)[0]
  types.value.splice(targetIdx, 0, moved)
  await api.put('/template/node-types/reorder', { ids: types.value.map((t) => t.id) })
  ElMessage.success('排序已保存')
}

async function loadTypes() {
  types.value = (await api.get('/template/node-types', { params: { include_inactive: true } })).data
}

async function select(t: any) {
  const { data } = await api.get(`/template/node-types/${t.id}`)
  selected.value = data
  for (const a of data.attributes) {
    optionRows[a.id] = (await api.get(`/template/attributes/${a.id}/options`)).data
  }
}

onMounted(() => loadTypes().catch(() => { /* 401 由拦截器跳转登录 */ }))

async function createType() {
  await api.post('/template/node-types', typeDialog.form)
  typeDialog.visible = false
  typeDialog.form = { name: '', kind: 'part', is_sellable_root: false }
  await loadTypes()
  ElMessage.success('已创建')
}

async function toggleTypeActive(t: any) {
  await api.patch(`/template/node-types/${t.id}`, { is_active: !t.is_active })
  await loadTypes()
  if (selected.value?.id === t.id) await select(t)
}

async function createAttr() {
  await api.post(`/template/node-types/${selected.value.id}/attributes`, attrDialog.form)
  attrDialog.visible = false
  attrDialog.form = { name: '', is_required: true, is_filterable: false }
  await select(selected.value)
}

async function createOption() {
  try {
    await api.post(`/template/attributes/${optDialog.attrId}/options`, optDialog.form)
    optDialog.visible = false
    optDialog.form = { label: '' }
    await select(selected.value)
  } catch (e: any) {
    // 409（如可选属性"无"选项禁令）由拦截器提示
  }
}

async function toggleOption(o: any) {
  await api.patch(`/template/options/${o.id}`, { is_active: !o.is_active })
  await select(selected.value)
  ElMessage.success(o.is_active ? '已停用：新配置不可选，既有 SKU 不受影响' : '已启用')
}

async function createSlot() {
  try {
    if (!slotDialog.form.name) {
      ElMessage.warning('请填写部件名称')
      return
    }
    let childTypeId = slotDialog.form.child_type_id
    // 现场新建部件类型：先建一个 part 类型（code 后端自动生成），再用它建槽
    if (slotDialog.source === 'new') {
      const { data } = await api.post('/template/node-types', {
        name: slotDialog.form.name, kind: 'part',
      })
      childTypeId = data.id
      await loadTypes()
    }
    if (!childTypeId) {
      ElMessage.warning('请选择部件类型')
      return
    }
    await api.post(`/template/node-types/${selected.value.id}/slots`, {
      name: slotDialog.form.name,
      child_type_id: childTypeId,
      is_required: slotDialog.form.is_required,
      allow_blackbox: slotDialog.form.allow_blackbox,
      variant_group: slotDialog.form.variant_group.trim() || null,
    })
    slotDialog.visible = false
    await select(selected.value)
    ElMessage.success('部件槽已创建')
  } catch {
    // 409（如 code 重复、形成环）由拦截器提示
  }
}

async function toggleSlot(s: any) {
  await api.patch(`/template/slots/${s.id}`, { is_active: !s.is_active })
  await select(selected.value)
}

function typeName(id: number) {
  return types.value.find((t) => t.id === id)?.name ?? id
}
</script>

<template>
  <el-row :gutter="12">
    <el-col :span="6">
      <el-card>
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            节点类型
            <el-button size="small" type="primary" @click="typeDialog.visible = true">新建</el-button>
          </div>
        </template>
        <div
          v-for="(t, idx) in types" :key="t.id" class="type-item"
          :class="{ active: selected?.id === t.id, inactive: !t.is_active, dragging: dragIndex === idx }"
          draggable="true"
          @click="select(t)"
          @dragstart="onDragStart(idx)"
          @dragover.prevent
          @drop.prevent="onDrop(idx)"
          @dragend="dragIndex = null"
        >
          <span class="drag-handle" title="拖动排序">⠿</span>
          <el-tag size="small" :type="t.kind === 'product' ? 'success' : 'info'">
            {{ t.kind === 'product' ? '品类' : '部件' }}
          </el-tag>
          {{ t.name }}
          <small style="color: var(--el-text-color-secondary)">{{ t.code }}</small>
        </div>
        <p style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 8px">
          按住任意一行拖动可调整显示顺序（影响配置看板与筛选器的排列）
        </p>
      </el-card>
    </el-col>

    <el-col :span="18">
      <el-card v-if="selected">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>{{ selected.name }}（{{ selected.code }}）</span>
            <span>
              <el-button size="small" @click="openEdit('type', selected)">编辑</el-button>
              <el-button size="small" :type="selected.is_active ? 'danger' : 'success'" plain
                         @click="toggleTypeActive(selected)">
                {{ selected.is_active ? '停用' : '启用' }}
              </el-button>
            </span>
          </div>
        </template>

        <h4>规格属性
          <el-button size="small" style="margin-left: 8px" @click="attrDialog.visible = true">+ 属性</el-button>
        </h4>
        <el-collapse>
          <el-collapse-item v-for="a in selected.attributes" :key="a.id">
            <template #title>
              {{ a.name }}（{{ a.code }}）
              <el-tag v-if="a.is_required" size="small" style="margin-left: 6px">必选</el-tag>
              <el-tag v-if="a.is_filterable" size="small" type="success" style="margin-left: 4px">筛选项</el-tag>
              <el-tag v-if="!a.is_active" size="small" type="info" style="margin-left: 4px">已停用</el-tag>
              <el-button
                text type="primary" size="small" style="margin-left: 8px"
                @click.stop="openEdit('attr', a)"
              >编辑</el-button>
            </template>
            <el-table :data="optionRows[a.id] ?? []" size="small">
              <el-table-column prop="code" label="选项 code（不可变）" width="170" />
              <el-table-column prop="label" label="显示名" />
              <el-table-column prop="reference_count" label="被引用" width="80" />
              <el-table-column label="状态 / 操作" width="220">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
                    {{ row.is_active ? '可用' : '已停用' }}
                  </el-tag>
                  <el-button text type="primary" size="small"
                             @click="openEdit('option', row, row.reference_count)">编辑</el-button>
                  <el-button text size="small" @click="toggleOption(row)">
                    {{ row.is_active ? '停用' : '启用' }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-button size="small" style="margin-top: 6px"
                       @click="optDialog.visible = true; optDialog.attrId = a.id">+ 选项</el-button>
          </el-collapse-item>
        </el-collapse>

        <h4 style="margin-top: 18px">部件槽
          <el-button size="small" style="margin-left: 8px" @click="openSlotDialog">+ 部件槽</el-button>
        </h4>
        <el-table :data="selected.slots" size="small">
          <el-table-column prop="code" label="槽 code（不可变）" width="160" />
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column label="部件类型" width="130">
            <template #default="{ row }">{{ typeName(row.child_type_id) }}</template>
          </el-table-column>
          <el-table-column label="必配" width="70">
            <template #default="{ row }">{{ row.is_required ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="允许成品件" width="100">
            <template #default="{ row }">{{ row.allow_blackbox ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="互斥组" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.variant_group" size="small" type="warning">{{ row.variant_group }}</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="状态 / 操作" width="210">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
                {{ row.is_active ? '可用' : '已停用' }}
              </el-tag>
              <el-button text type="primary" size="small" @click="openEdit('slot', row)">编辑</el-button>
              <el-button text size="small" @click="toggleSlot(row)">
                {{ row.is_active ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-alert
          type="info" :closable="false" style="margin-top: 16px"
          title="模板纪律（系统强制）"
          description="编码由系统按名称自动生成、一经创建不可修改（进入 SKU 唯一性校验）；删除一律软停用，被 SKU 引用的对象数据库层禁止物理删除；停用只影响新配置，既有 SKU 的展示与指纹永不改变；可选属性禁止创建“无/不带”语义的选项。"
        />
      </el-card>
      <el-empty v-else description="左侧选择一个节点类型" />
    </el-col>
  </el-row>

  <!-- 对话框们 -->
  <el-dialog v-model="typeDialog.visible" title="新建节点类型" width="460">
    <el-form label-width="110px">
      <el-form-item label="名称" required>
        <el-input v-model="typeDialog.form.name" placeholder="如：顶杆（编码由系统自动生成）" />
      </el-form-item>
      <el-form-item label="类别">
        <el-radio-group v-model="typeDialog.form.kind">
          <el-radio value="product">整机品类</el-radio>
          <el-radio value="part">部件类型</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="可作可售根">
        <el-switch v-model="typeDialog.form.is_sellable_root" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="typeDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createType">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="attrDialog.visible" title="新建属性" width="460">
    <el-form label-width="110px">
      <el-form-item label="名称" required>
        <el-input v-model="attrDialog.form.name" placeholder="如：充装量" />
      </el-form-item>
      <el-form-item label="必选"><el-switch v-model="attrDialog.form.is_required" /></el-form-item>
      <el-form-item label="作为筛选项"><el-switch v-model="attrDialog.form.is_filterable" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="attrDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createAttr">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="optDialog.visible" title="新建选项" width="460">
    <el-form label-width="110px">
      <el-form-item label="显示名" required>
        <el-input v-model="optDialog.form.label" placeholder="如 4kg（编码由系统自动生成）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="optDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createOption">创建</el-button>
    </template>
  </el-dialog>

  <!-- 在位编辑对话框：只暴露安全可变字段；code 与所属结构不可改 -->
  <el-dialog v-model="editDialog.visible" :title="EDIT_TITLES[editDialog.kind]" width="460">
    <el-form label-width="110px">
      <template v-if="editDialog.kind === 'type'">
        <el-form-item label="名称" required><el-input v-model="editDialog.form.name" /></el-form-item>
        <el-form-item label="可作可售根"><el-switch v-model="editDialog.form.is_sellable_root" /></el-form-item>
      </template>
      <template v-else-if="editDialog.kind === 'attr'">
        <el-form-item label="名称" required><el-input v-model="editDialog.form.name" /></el-form-item>
        <el-form-item label="单位"><el-input v-model="editDialog.form.unit" placeholder="如 kg、MPa（可空）" /></el-form-item>
        <el-form-item label="必选"><el-switch v-model="editDialog.form.is_required" /></el-form-item>
        <el-form-item label="作为筛选项"><el-switch v-model="editDialog.form.is_filterable" /></el-form-item>
      </template>
      <template v-else-if="editDialog.kind === 'option'">
        <el-form-item label="显示名" required><el-input v-model="editDialog.form.label" /></el-form-item>
        <el-alert
          v-if="editDialog.refCount > 0" type="warning" :closable="false"
          :title="`该选项被 ${editDialog.refCount} 个 SKU 引用，改名将同步改变它们的展示`"
          description="仅限纠错（错别字/表述）。若是换成不同含义（如 4kg→5kg），请新建选项并停用本选项。"
        />
      </template>
      <template v-else>
        <el-form-item label="名称" required><el-input v-model="editDialog.form.name" /></el-form-item>
        <el-form-item label="必配"><el-switch v-model="editDialog.form.is_required" /></el-form-item>
        <el-form-item label="允许成品件"><el-switch v-model="editDialog.form.allow_blackbox" /></el-form-item>
        <el-form-item label="互斥组">
          <el-input
            v-model="editDialog.form.variant_group"
            placeholder="如 型号：同组槽配置时 N 选 1；留空=普通槽"
          />
        </el-form-item>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="editDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="saveEdit">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="slotDialog.visible" title="新建部件槽" width="460">
    <el-form label-width="110px">
      <el-form-item label="名称" required>
        <el-input v-model="slotDialog.form.name" placeholder="部件名，如 顶杆；新建类型时同时作为部件名" />
      </el-form-item>
      <el-form-item label="部件类型" required>
        <el-radio-group v-model="slotDialog.source" style="margin-bottom: 8px">
          <el-radio-button value="existing">选用已有类型</el-radio-button>
          <el-radio-button value="new">现场新建类型</el-radio-button>
        </el-radio-group>
        <el-select
          v-if="slotDialog.source === 'existing'"
          v-model="slotDialog.form.child_type_id" filterable style="width: 100%"
          placeholder="选择已有的部件类型"
        >
          <el-option
            v-for="t in types.filter(t => t.is_active)" :key="t.id" :value="t.id"
            :label="`${t.name}（${t.code}）`"
          />
        </el-select>
        <el-alert
          v-else type="info" :closable="false"
          title="将以上面的名称新建一个部件类型（编码自动生成）并挂到当前部件下"
        />
      </el-form-item>
      <el-form-item label="必配"><el-switch v-model="slotDialog.form.is_required" /></el-form-item>
      <el-form-item label="允许成品件"><el-switch v-model="slotDialog.form.allow_blackbox" /></el-form-item>
      <el-form-item label="互斥组">
        <el-input
          v-model="slotDialog.form.variant_group"
          placeholder="如 型号：同组多个槽配置时 N 选 1；留空=普通槽"
        />
      </el-form-item>
      <el-alert
        v-if="slotDialog.source === 'new'" type="info" :closable="false"
        title="将新建一个部件类型并挂到当前部件下。建好后可在左栏选中它，继续给它加属性和下一级部件（递归拆解）。"
      />
    </el-form>
    <template #footer>
      <el-button @click="slotDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createSlot">创建</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.type-item {
  padding: 7px 8px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 2px;
}
.type-item:hover { background: var(--el-fill-color-light); }
.type-item.active { background: var(--el-color-primary-light-9); }
.type-item.inactive { opacity: 0.5; }
.type-item.dragging { opacity: 0.4; border: 1px dashed var(--el-color-primary); }
.drag-handle {
  cursor: grab;
  color: var(--el-text-color-placeholder);
  margin-right: 4px;
  user-select: none;
}
</style>
