<script setup lang="ts">
import {
  Box, Document, Goods, Setting, ShoppingCart,
} from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useQuoteCartStore } from '../stores/quoteCart'

const auth = useAuthStore()
const cart = useQuoteCartStore()
const router = useRouter()
const route = useRoute()
const searchText = ref('')

onMounted(async () => {
  if (!auth.user) await auth.fetchMe().catch(() => router.push('/login'))
  void cart.refreshCount()
})

interface Suggestion {
  value: string
  kind: string
  id: number
}

async function fetchSuggestions(q: string, cb: (items: Suggestion[]) => void) {
  if (!q || q.length < 1) return cb([])
  const out: Suggestion[] = []
  try {
    const { data } = await api.get('/skus', { params: { q, page_size: 6 } })
    out.push(...data.items.map((s: any) => ({
      value: `${s.sku_code}  ${s.name}`, kind: 'SKU', id: s.id,
    })))
    const parts = await api.get('/purchased-parts', { params: { q } })
    out.push(...parts.data.slice(0, 4).map((p: any) => ({
      value: `${p.supplier_name} | ${p.name}`, kind: '成品件', id: p.id,
    })))
  } catch { /* 静默 */ }
  cb(out)
}

function onSelectSuggestion(item: Suggestion) {
  searchText.value = ''
  if (item.kind === 'SKU') router.push({ path: '/skus', query: { sku_id: item.id } })
  else router.push('/suppliers')
}

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container style="height: 100vh">
    <el-aside width="210px" style="border-right: 1px solid var(--el-border-color)">
      <div class="brand">ProductHub<br /><small>北京合胜 · 产品中台</small></div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/skus"><el-icon><Goods /></el-icon>产品库</el-menu-item>
        <el-menu-item index="/configure"><el-icon><Box /></el-icon>配置看板</el-menu-item>
        <el-menu-item index="/quotations"><el-icon><Document /></el-icon>报价单</el-menu-item>
        <el-menu-item index="/suppliers"><el-icon><ShoppingCart /></el-icon>供应商与采购件</el-menu-item>
        <el-sub-menu v-if="auth.isAdmin" index="/admin">
          <template #title><el-icon><Setting /></el-icon>系统设置</template>
          <el-menu-item index="/admin/templates">产品模板</el-menu-item>
          <el-menu-item index="/admin/import">数据导入</el-menu-item>
          <el-menu-item index="/admin/users">用户管理</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <el-autocomplete
          v-model="searchText"
          :fetch-suggestions="fetchSuggestions"
          placeholder="搜索 SKU 编码 / 名称 / 成品件…"
          style="width: 420px"
          clearable
          @select="onSelectSuggestion as any"
        >
          <template #default="{ item }">
            <el-tag size="small" style="margin-right: 6px">{{ item.kind }}</el-tag>
            <span>{{ item.value }}</span>
          </template>
        </el-autocomplete>
        <div class="topbar-right">
          <el-badge :value="cart.itemCount" :hidden="!cart.itemCount" style="margin-right: 18px">
            <el-button text @click="router.push('/quotations')">
              <el-icon size="20"><Document /></el-icon>&nbsp;当前报价单
            </el-button>
          </el-badge>
          <el-dropdown>
            <span style="cursor: pointer">
              {{ auth.user?.display_name ?? '…' }}
              <el-tag size="small" style="margin-left: 4px">
                {{ auth.isAdmin ? '管理员' : '业务员' }}
              </el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main style="background: var(--el-fill-color-light)">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.brand {
  padding: 16px;
  font-weight: 700;
  font-size: 18px;
  line-height: 1.3;
}
.brand small {
  font-weight: 400;
  color: var(--el-text-color-secondary);
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--el-border-color);
}
.topbar-right {
  display: flex;
  align-items: center;
}
</style>
