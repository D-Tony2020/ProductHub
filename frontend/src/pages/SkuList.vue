<script setup lang="ts">
/** SKU 查价（默认首页）：筛选 + 表格 + 详情抽屉（只读配置树/价格历史）。 */
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useQuoteCartStore } from '../stores/quoteCart'

const auth = useAuthStore()
const cart = useQuoteCartStore()
const router = useRouter()
const route = useRoute()

const filters = reactive({
  q: '', root_type_id: null as number | null, status: null as string | null,
  option_id: [] as number[], purchased_part_id: null as number | null,
})
const rootTypes = ref<any[]>([])
const filterAttrs = ref<any[]>([])
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)

const drawer = reactive({ visible: false, sku: null as any, prices: [] as any[] })

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/skus', {
      params: {
        q: filters.q || undefined,
        root_type_id: filters.root_type_id ?? undefined,
        status: filters.status ?? undefined,
        option_id: filters.option_id.length ? filters.option_id : undefined,
        purchased_part_id: filters.purchased_part_id ?? undefined,
        page: page.value, page_size: 20,
      },
      paramsSerializer: { indexes: null },
    })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    const { data } = await api.get('/template/node-types')
    rootTypes.value = data.filter((t: any) => t.is_sellable_root)
    await load()
    if (route.query.sku_id) await openDetailById(Number(route.query.sku_id))
  } catch { /* 401 由拦截器跳转登录 */ }
})

watch(() => filters.root_type_id, async (id) => {
  filters.option_id = []
  filterAttrs.value = []
  if (id) {
    const { data } = await api.get(`/template/node-types/${id}`)
    filterAttrs.value = data.attributes.filter((a: any) => a.is_filterable && a.is_active)
  }
  page.value = 1
  await load()
})
watch([() => filters.q, () => filters.status, () => filters.option_id], () => {
  page.value = 1
  void load()
}, { deep: true })
watch(page, () => void load())

async function openDetailById(id: number) {
  const { data } = await api.get(`/skus/${id}`)
  drawer.sku = data
  drawer.prices = (await api.get(`/skus/${id}/prices`)).data
  drawer.visible = true
}

async function addToQuote(sku: any) {
  const r = await cart.addSku(sku.id, 1)
  if (r.ok) ElMessage.success('已加入当前报价单')
  else if (r.message === 'NO_ACTIVE') {
    ElMessage.warning('请先到「报价单」页新建/选择草稿单')
    router.push('/quotations')
  } else ElMessage.error(r.message!)
}

async function setPrice(sku: any) {
  const { value } = await (await import('element-plus')).ElMessageBox.prompt(
    `为 ${sku.sku_code} 录入新价（USD）。改价只追加不覆盖，历史全量保留。`, '录入价格',
    { inputPattern: /^\d+(\.\d{1,4})?$/, inputErrorMessage: '请输入合法金额' },
  )
  await api.post(`/skus/${sku.id}/prices`, { price: value })
  ElMessage.success('价格已生效')
  await load()
  if (drawer.visible && drawer.sku?.id === sku.id) await openDetailById(sku.id)
}

function exportList() {
  const token = localStorage.getItem('access_token')
  fetch(`/api/v1/skus/export${filters.root_type_id ? `?root_type_id=${filters.root_type_id}` : ''}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(async (r) => {
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'SKU清单.xlsx'
    a.click()
    URL.revokeObjectURL(url)
  })
}

function priceText(s: any) {
  if (!s.current_prices?.length) return null
  const p = s.current_prices[0]
  return `${p.currency} ${p.price}`
}

function renderTreeText(node: any, depth = 0): string[] {
  const pad = '　'.repeat(depth)
  const lines: string[] = []
  const head = node.slot_name ? `${node.slot_name}：` : ''
  if (node.mode === 'purchased') {
    lines.push(`${pad}${head}【成品】${node.supplier_name} | ${node.purchased_part_name}`)
  } else {
    const attrs = (node.attributes ?? [])
      .map((a: any) => `${a.attribute_name}=${a.option_label}${a.option_active ? '' : '（选项已停用）'}`)
      .join('，')
    lines.push(`${pad}${head}${node.node_type_name}${attrs ? `（${attrs}）` : ''}`)
    for (const c of node.children ?? []) lines.push(...renderTreeText(c, depth + 1))
  }
  return lines
}
</script>

<template>
  <el-card>
    <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px">
      <el-select v-model="filters.root_type_id" placeholder="品类" clearable style="width: 180px">
        <el-option v-for="t in rootTypes" :key="t.id" :value="t.id" :label="t.name" />
      </el-select>
      <el-select
        v-for="a in filterAttrs" :key="a.id" v-model="filters.option_id" multiple collapse-tags
        :placeholder="a.name" style="width: 170px"
      >
        <el-option
          v-for="o in a.options.filter((o: any) => o.is_active)" :key="o.id"
          :value="o.id" :label="`${a.name}: ${o.label}`"
        />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" clearable style="width: 130px">
        <el-option value="active" label="在售" />
        <el-option value="pending_price" label="待录价" />
        <el-option value="retired" label="已作废" />
      </el-select>
      <el-input
        v-model="filters.q" placeholder="SKU 编码 / 名称" clearable style="width: 220px"
      />
      <el-button @click="exportList">导出清单 Excel</el-button>
      <el-button type="primary" @click="router.push('/configure')">+ 新配置</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" @row-click="(r: any) => openDetailById(r.id)">
      <el-table-column prop="sku_code" label="SKU 编码" width="150" />
      <el-table-column prop="name" label="名称 / 规格摘要" min-width="280" />
      <el-table-column label="现价" width="130">
        <template #default="{ row }">
          <b v-if="priceText(row)" style="color: var(--el-color-success)">{{ priceText(row) }}</b>
          <el-tag v-else type="warning" size="small">待录价</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
            {{ row.status === 'active' ? '在售' : '已作废' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="230">
        <template #default="{ row }">
          <el-button size="small" :disabled="!row.current_prices?.length || row.status !== 'active'"
                     @click.stop="addToQuote(row)">加入报价单</el-button>
          <el-button size="small" @click.stop="router.push({ path: '/configure', query: { sku_id: row.id } })">
            以此再配置
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page" :total="total" :page-size="20"
      layout="total, prev, pager, next" style="margin-top: 12px; justify-content: end"
    />
  </el-card>

  <el-drawer v-model="drawer.visible" size="50%" :title="drawer.sku?.sku_code">
    <template v-if="drawer.sku">
      <h3 style="margin-top: 0">{{ drawer.sku.name }}</h3>
      <p>
        <el-tag :type="drawer.sku.status === 'active' ? 'success' : 'info'">
          {{ drawer.sku.status === 'active' ? '在售' : '已作废' }}
        </el-tag>
        <span v-if="priceText(drawer.sku)" style="font-size: 22px; margin-left: 12px; color: var(--el-color-success)">
          {{ priceText(drawer.sku) }}
        </span>
        <el-tag v-else type="warning" style="margin-left: 12px">待录价</el-tag>
      </p>
      <el-tabs>
        <el-tab-pane label="产品构成（事实视图）">
          <pre style="font-family: inherit; line-height: 1.9; white-space: pre-wrap">{{
            drawer.sku.config_tree ? renderTreeText(drawer.sku.config_tree).join('\n') : '—'
          }}</pre>
        </el-tab-pane>
        <el-tab-pane label="价格历史">
          <el-table :data="drawer.prices">
            <el-table-column prop="price" label="单价" width="110" />
            <el-table-column prop="currency" label="币种" width="70" />
            <el-table-column prop="valid_from" label="生效日" width="110" />
            <el-table-column prop="valid_to" label="失效日" width="110">
              <template #default="{ row }">{{ row.valid_to ?? '长期' }}</template>
            </el-table-column>
            <el-table-column prop="created_by_name" label="录入人" width="100" />
            <el-table-column prop="note" label="备注" />
          </el-table>
          <p style="color: var(--el-text-color-secondary); font-size: 12px">
            价格记录只追加不覆盖；历史永久可查。
          </p>
        </el-tab-pane>
      </el-tabs>
      <div style="display: flex; gap: 8px; margin-top: 12px">
        <el-button
          type="primary" :disabled="!drawer.sku.current_prices?.length || drawer.sku.status !== 'active'"
          @click="addToQuote(drawer.sku)"
        >加入报价单</el-button>
        <el-button @click="router.push({ path: '/configure', query: { sku_id: drawer.sku.id } })">
          以此为模板再配置
        </el-button>
        <el-button v-if="auth.canSetPrice" @click="setPrice(drawer.sku)">录入新价</el-button>
      </div>
    </template>
  </el-drawer>
</template>
