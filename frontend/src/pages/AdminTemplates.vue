<script setup lang="ts">
/** 产品模板管理（admin）：节点类型 / 属性与选项 / 部件槽。
 *  纪律由后端强制（code 不可变、软停用、引用计数、DAG、可选属性"无"选项禁令），
 *  此页只做呈现与触发。 */
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'

const types = ref<any[]>([])
const selected = ref<any | null>(null)
const optionRows = reactive<Record<number, any[]>>({})

const typeDialog = reactive({ visible: false, form: { code: '', name: '', kind: 'part', is_sellable_root: false } })
const attrDialog = reactive({ visible: false, form: { code: '', name: '', is_required: true, is_filterable: false } })
const optDialog = reactive({ visible: false, attrId: 0, form: { code: '', label: '' } })
const slotDialog = reactive({
  visible: false,
  form: { code: '', name: '', child_type_id: null as number | null, is_required: true, allow_blackbox: true },
})

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

onMounted(loadTypes)

async function createType() {
  await api.post('/template/node-types', typeDialog.form)
  typeDialog.visible = false
  typeDialog.form = { code: '', name: '', kind: 'part', is_sellable_root: false }
  await loadTypes()
  ElMessage.success('已创建。注意：code 一经创建不可修改')
}

async function toggleTypeActive(t: any) {
  await api.patch(`/template/node-types/${t.id}`, { is_active: !t.is_active })
  await loadTypes()
  if (selected.value?.id === t.id) await select(t)
}

async function createAttr() {
  await api.post(`/template/node-types/${selected.value.id}/attributes`, attrDialog.form)
  attrDialog.visible = false
  attrDialog.form = { code: '', name: '', is_required: true, is_filterable: false }
  await select(selected.value)
}

async function createOption() {
  try {
    await api.post(`/template/attributes/${optDialog.attrId}/options`, optDialog.form)
    optDialog.visible = false
    optDialog.form = { code: '', label: '' }
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
  await api.post(`/template/node-types/${selected.value.id}/slots`, slotDialog.form)
  slotDialog.visible = false
  slotDialog.form = { code: '', name: '', child_type_id: null, is_required: true, allow_blackbox: true }
  await select(selected.value)
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
          v-for="t in types" :key="t.id" class="type-item"
          :class="{ active: selected?.id === t.id, inactive: !t.is_active }" @click="select(t)"
        >
          <el-tag size="small" :type="t.kind === 'product' ? 'success' : 'info'">
            {{ t.kind === 'product' ? '品类' : '部件' }}
          </el-tag>
          {{ t.name }}
          <small style="color: var(--el-text-color-secondary)">{{ t.code }}</small>
        </div>
      </el-card>
    </el-col>

    <el-col :span="18">
      <el-card v-if="selected">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>{{ selected.name }}（{{ selected.code }}）</span>
            <el-button size="small" :type="selected.is_active ? 'danger' : 'success'" plain
                       @click="toggleTypeActive(selected)">
              {{ selected.is_active ? '停用' : '启用' }}
            </el-button>
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
            </template>
            <el-table :data="optionRows[a.id] ?? []" size="small">
              <el-table-column prop="code" label="选项 code（不可变）" width="170" />
              <el-table-column prop="label" label="显示名" />
              <el-table-column prop="reference_count" label="被引用" width="80" />
              <el-table-column label="状态" width="160">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
                    {{ row.is_active ? '可用' : '已停用' }}
                  </el-tag>
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
          <el-button size="small" style="margin-left: 8px" @click="slotDialog.visible = true">+ 部件槽</el-button>
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
          <el-table-column label="状态" width="150">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
                {{ row.is_active ? '可用' : '已停用' }}
              </el-tag>
              <el-button text size="small" @click="toggleSlot(row)">
                {{ row.is_active ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-alert
          type="info" :closable="false" style="margin-top: 16px"
          title="模板纪律（系统强制）"
          description="code 一经创建不可修改（进入 SKU 指纹）；删除一律软停用，被 SKU 引用的对象数据库层禁止物理删除；停用只影响新配置，既有 SKU 的展示与指纹永不改变；可选属性禁止创建“无/不带”语义的选项。"
        />
      </el-card>
      <el-empty v-else description="左侧选择一个节点类型" />
    </el-col>
  </el-row>

  <!-- 对话框们 -->
  <el-dialog v-model="typeDialog.visible" title="新建节点类型" width="460">
    <el-form label-width="110px">
      <el-form-item label="code" required>
        <el-input v-model="typeDialog.form.code" placeholder="大写字母/数字/下划线，如 VALVE" />
      </el-form-item>
      <el-form-item label="名称" required><el-input v-model="typeDialog.form.name" /></el-form-item>
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
      <el-form-item label="code" required><el-input v-model="attrDialog.form.code" /></el-form-item>
      <el-form-item label="名称" required><el-input v-model="attrDialog.form.name" /></el-form-item>
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
      <el-form-item label="code" required>
        <el-input v-model="optDialog.form.code" placeholder="如 KG4（不可变，入指纹）" />
      </el-form-item>
      <el-form-item label="显示名" required>
        <el-input v-model="optDialog.form.label" placeholder="如 4kg（可改）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="optDialog.visible = false">取消</el-button>
      <el-button type="primary" @click="createOption">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="slotDialog.visible" title="新建部件槽" width="460">
    <el-form label-width="110px">
      <el-form-item label="code" required><el-input v-model="slotDialog.form.code" /></el-form-item>
      <el-form-item label="名称" required><el-input v-model="slotDialog.form.name" /></el-form-item>
      <el-form-item label="部件类型" required>
        <el-select v-model="slotDialog.form.child_type_id" filterable style="width: 100%">
          <el-option
            v-for="t in types.filter(t => t.is_active)" :key="t.id" :value="t.id"
            :label="`${t.name}（${t.code}）`"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="必配"><el-switch v-model="slotDialog.form.is_required" /></el-form-item>
      <el-form-item label="允许成品件"><el-switch v-model="slotDialog.form.allow_blackbox" /></el-form-item>
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
</style>
