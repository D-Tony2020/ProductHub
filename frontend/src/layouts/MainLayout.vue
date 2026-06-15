<script setup lang="ts">
import {
  Box, Document, Goods, Search, Setting, ShoppingCart,
} from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useQuoteCartStore } from '../stores/quoteCart'

const auth = useAuthStore()
const cart = useQuoteCartStore()
const router = useRouter()
const route = useRoute()
const searchText = ref('')

// 密度切换（紧凑/宽松）：localStorage 持久化；首帧由 index.html 内联脚本预置，避免闪烁
const density = ref<'comfortable' | 'compact'>(
  (localStorage.getItem('ph-density') as 'comfortable' | 'compact') || 'comfortable',
)
function toggleDensity() {
  density.value = density.value === 'compact' ? 'comfortable' : 'compact'
  if (density.value === 'compact') document.documentElement.setAttribute('data-density', 'compact')
  else document.documentElement.removeAttribute('data-density')
  localStorage.setItem('ph-density', density.value)
}

const avatarText = computed(() => auth.user?.display_name?.[0] ?? '·')

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
    <el-aside width="210px" class="aside">
      <div class="brand">
        <div class="logo"><el-icon :size="18"><Goods /></el-icon></div>
        <div class="brand-text">ProductHub<br /><small>北京合胜 · 产品中台</small></div>
      </div>
      <el-menu :default-active="route.path" router class="nav-menu">
        <el-menu-item-group title="业务">
          <el-menu-item index="/skus"><el-icon><Goods /></el-icon>产品库</el-menu-item>
          <el-menu-item index="/configure"><el-icon><Box /></el-icon>配置看板</el-menu-item>
          <el-menu-item index="/quotations"><el-icon><Document /></el-icon>报价单</el-menu-item>
          <el-menu-item index="/suppliers"><el-icon><ShoppingCart /></el-icon>供应商与采购件</el-menu-item>
        </el-menu-item-group>
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
          style="width: 360px"
          clearable
          @select="onSelectSuggestion as any"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
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
            <span class="user-trigger">
              <span class="avatar">{{ avatarText }}</span>
              <span class="user-name">{{ auth.user?.display_name ?? '…' }}</span>
              <el-tag size="small" type="info" effect="plain">
                {{ auth.isAdmin ? '管理员' : '业务员' }}
              </el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="toggleDensity">
                  {{ density === 'compact' ? '切换宽松模式' : '切换紧凑模式' }}
                </el-dropdown-item>
                <el-dropdown-item divided @click="logout">退出登录</el-dropdown-item>
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
.aside { border-right: 1px solid var(--el-border-color-light); background: var(--el-bg-color); }
.brand { display: flex; align-items: center; gap: 10px; padding: 16px; }
.logo {
  width: 32px; height: 32px; border-radius: var(--ph-radius-sm);
  background: var(--ph-brand-600); color: var(--el-color-white);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.brand-text { font-weight: 600; font-size: 16px; line-height: 1.25; }
.brand-text small { font-weight: 400; font-size: 12px; color: var(--el-text-color-secondary); }

.nav-menu {
  border-right: none;
  --el-menu-active-color: var(--ph-brand-600);
  --el-menu-hover-bg-color: var(--ph-gray-50);
  --el-menu-item-height: 46px;
}
:deep(.el-menu-item-group__title) {
  font-size: 12px; color: var(--el-text-color-secondary); padding: 12px 16px 4px;
}
:deep(.el-menu-item.is-active) { background: var(--el-color-primary-light-9); position: relative; }
:deep(.el-menu-item.is-active)::before {
  content: ''; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px;
  background: var(--ph-brand-600); border-radius: 0 2px 2px 0;
}

.topbar {
  height: 56px;
  display: flex; align-items: center; justify-content: space-between;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  box-shadow: var(--ph-shadow-sm);
  position: relative; z-index: 10;
}
.topbar-right { display: flex; align-items: center; }
.user-trigger { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px; outline: none; }
.avatar {
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--ph-brand-600); color: var(--el-color-white);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 500;
}
.user-name { color: var(--el-text-color-regular); }
</style>
