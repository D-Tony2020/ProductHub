<script setup lang="ts">
/** 报价单工作台：多草稿并存 + 激活单切换 + 快照价 + 导出冻结。 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { api } from '../api/client'
import { useQuoteCartStore } from '../stores/quoteCart'

const cart = useQuoteCartStore()
const quotes = ref<any[]>([])
const current = ref<any | null>(null)
const showCreate = ref(false)
const form = ref({ customer_name: '', customer_contact: '', currency: 'USD', notes: '' })

const draftQuotes = computed(() => quotes.value.filter((q) => q.status === 'draft'))
const exportedQuotes = computed(() => quotes.value.filter((q) => q.status !== 'draft'))

async function load() {
  quotes.value = (await api.get('/quotes')).data
  if (cart.activeQuoteId) {
    current.value = quotes.value.find((q) => q.id === cart.activeQuoteId) ?? null
  }
  if (!current.value && draftQuotes.value.length) selectQuote(draftQuotes.value[0])
}

onMounted(() => load().catch(() => { /* 401 由拦截器跳转登录 */ }))

function selectQuote(q: any) {
  current.value = q
  if (q.status === 'draft') cart.setActive(q.id)
}

async function createQuote() {
  if (!form.value.customer_name) {
    ElMessage.warning('请填写客户名称')
    return
  }
  const { data } = await api.post('/quotes', form.value)
  showCreate.value = false
  form.value = { customer_name: '', customer_contact: '', currency: 'USD', notes: '' }
  await load()
  selectQuote(data)
}

async function refreshCurrent() {
  if (!current.value) return
  const { data } = await api.get(`/quotes/${current.value.id}`)
  current.value = data
  const idx = quotes.value.findIndex((q) => q.id === data.id)
  if (idx >= 0) quotes.value[idx] = data
  void cart.refreshCount()
}

async function updateQty(item: any, qty: number) {
  await api.patch(`/quotes/${current.value.id}/items/${item.id}`, { qty })
  await refreshCurrent()
}

async function overridePrice(item: any) {
  const { value } = await ElMessageBox.prompt(
    `手动覆盖单价（快照价 ${item.snapshot_price} 将保留留痕）`, '调整单价',
    { inputValue: String(item.unit_price), inputPattern: /^\d+(\.\d{1,4})?$/, inputErrorMessage: '金额非法' },
  )
  await api.patch(`/quotes/${current.value.id}/items/${item.id}`, { unit_price: value })
  await refreshCurrent()
}

async function removeItem(item: any) {
  await api.delete(`/quotes/${current.value.id}/items/${item.id}`)
  await refreshCurrent()
}

async function exportQuote() {
  const q = current.value
  if (!q) return
  // 导出前一致性校验
  const { data: check } = await api.get(`/quotes/${q.id}/price-check`)
  let force = false
  if (!check.consistent) {
    try {
      await ElMessageBox.confirm(
        `${check.changed_items.length} 个 SKU 的现价已与加入时的快照不同。`
        + '「刷新为最新价」将更新明细后再导出；「按原快照导出」保持原价。',
        '价格已变动',
        { confirmButtonText: '刷新为最新价', cancelButtonText: '按原快照导出', distinguishCancelAndClose: true },
      )
      await api.post(`/quotes/${q.id}/refresh-prices`)
    } catch (action) {
      if (action !== 'cancel') return
      force = true
    }
  }
  const token = localStorage.getItem('access_token')
  const resp = await fetch(`/api/v1/quotes/${q.id}/export?force_snapshot=${force}`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}` },
  })
  if (!resp.ok) {
    ElMessage.error('导出失败')
    return
  }
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${q.quote_no}-${q.customer_name}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出并冻结；如需修改请复制为新草稿')
  cart.setActive(null)
  await load()
}

async function duplicateQuote(q: any) {
  const { data } = await api.post(`/quotes/${q.id}/duplicate`)
  await load()
  selectQuote(data)
  ElMessage.success(`已复制为 ${data.quote_no}`)
}
</script>

<template>
  <el-row :gutter="12">
    <el-col :span="7">
      <el-card>
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            我的报价单
            <el-button size="small" type="primary" @click="showCreate = true">新建</el-button>
          </div>
        </template>
        <h5>草稿</h5>
        <div
          v-for="q in draftQuotes" :key="q.id" class="quote-item"
          :class="{ active: current?.id === q.id }" @click="selectQuote(q)"
        >
          <b>{{ q.quote_no }}</b> {{ q.customer_name }}
          <el-tag v-if="cart.activeQuoteId === q.id" size="small" type="success">激活</el-tag>
          <div style="font-size: 12px; color: var(--el-text-color-secondary)">
            {{ q.items.length }} 项 · {{ q.currency }} {{ q.total }}
          </div>
        </div>
        <el-empty v-if="!draftQuotes.length" description="暂无草稿" :image-size="50" />
        <h5>已导出（冻结）</h5>
        <div
          v-for="q in exportedQuotes" :key="q.id" class="quote-item"
          :class="{ active: current?.id === q.id }" @click="current = q"
        >
          <b>{{ q.quote_no }}</b> {{ q.customer_name }}
          <el-button text size="small" type="primary" @click.stop="duplicateQuote(q)">复制为新草稿</el-button>
        </div>
      </el-card>
    </el-col>

    <el-col :span="17">
      <el-card v-if="current">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>
              {{ current.quote_no }} · {{ current.customer_name }}
              <el-tag :type="current.status === 'draft' ? 'primary' : 'info'" size="small">
                {{ current.status === 'draft' ? '草稿' : '已导出（冻结）' }}
              </el-tag>
              <el-tag size="small" style="margin-left: 6px">{{ current.currency }}</el-tag>
            </span>
            <span>
              <el-button v-if="current.status === 'draft'" type="primary" @click="exportQuote">
                导出 Excel
              </el-button>
              <el-button v-else @click="duplicateQuote(current)">复制为新草稿</el-button>
            </span>
          </div>
        </template>
        <el-table :data="current.items"
                  :row-class-name="({ row }: { row: any }) => (row.price_changed ? 'row-price-changed' : '')">
          <el-table-column prop="sku_code" label="SKU" width="140" />
          <el-table-column prop="sku_name" label="品名/规格" min-width="220" />
          <el-table-column label="数量" width="130">
            <template #default="{ row }">
              <el-input-number
                v-if="current.status === 'draft'" :model-value="row.qty" :min="1" size="small"
                @change="(v: number) => updateQty(row, v)"
              />
              <span v-else>{{ row.qty }}</span>
            </template>
          </el-table-column>
          <el-table-column label="单价" width="150">
            <template #default="{ row }">
              <span :style="row.unit_price !== row.snapshot_price ? 'color: var(--el-color-warning)' : ''">
                {{ row.unit_price }}
              </span>
              <el-tooltip v-if="row.price_changed" content="现价已变动，导出前会提示处理">
                <el-tag size="small" type="warning" style="margin-left: 4px">价变</el-tag>
              </el-tooltip>
              <el-button
                v-if="current.status === 'draft'" text size="small" @click="overridePrice(row)"
              >调价</el-button>
            </template>
          </el-table-column>
          <el-table-column label="小计" width="120">
            <template #default="{ row }">{{ row.line_total }}</template>
          </el-table-column>
          <el-table-column v-if="current.status === 'draft'" width="70">
            <template #default="{ row }">
              <el-button text type="danger" size="small" @click="removeItem(row)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="settle-bar">
          <span class="settle-meta">{{ current.items.length }} 项明细</span>
          <span class="settle-total">合计 <b class="ph-num">{{ current.currency }} {{ current.total }}</b></span>
        </div>
        <p style="color: var(--el-text-color-secondary); font-size: 12px">
          同一单据内禁止混币种；不符币种或待录价的 SKU 无法加入。导出后单据冻结，保证对外文件与系统记录一一对应。
        </p>
      </el-card>
      <el-empty v-else description="左侧选择或新建一张报价单" />
    </el-col>
  </el-row>

  <el-dialog v-model="showCreate" title="新建报价单" width="460">
    <el-form label-width="90px">
      <el-form-item label="客户名称" required>
        <el-input v-model="form.customer_name" />
      </el-form-item>
      <el-form-item label="联系方式">
        <el-input v-model="form.customer_contact" />
      </el-form-item>
      <el-form-item label="单据币种">
        <el-select v-model="form.currency" style="width: 120px">
          <el-option value="USD" /><el-option value="CNY" /><el-option value="EUR" />
        </el-select>
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.notes" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="showCreate = false">取消</el-button>
      <el-button type="primary" @click="createQuote">创建并设为激活单</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.quote-item {
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
}
.quote-item:hover {
  background: var(--el-fill-color-light);
}
.quote-item.active {
  background: var(--el-color-primary-light-9);
}

/* 结算条 */
.settle-bar {
  display: flex; align-items: center; justify-content: space-between;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-light);
  border-radius: var(--ph-radius-md);
  padding: 12px 16px; margin-top: 12px;
}
.settle-meta { font-size: 13px; color: var(--el-text-color-secondary); }
.settle-total { font-size: 15px; color: var(--el-text-color-secondary); }
.settle-total b { font-size: 22px; font-weight: 600; color: var(--el-text-color-primary); margin-left: 6px; }
/* 价变行浅警告底 */
:deep(.el-table .row-price-changed td.el-table__cell) { background: var(--el-color-warning-light-9); }
</style>
