<script setup lang="ts">
import {
  Box, Document, Expand, Fold, Goods, Search, Setting, ShoppingCart,
} from '@element-plus/icons-vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import logoUrl from '../assets/logo-square.png'
import { useAuthStore } from '../stores/auth'
import { useQuoteCartStore } from '../stores/quoteCart'

const auth = useAuthStore()
const cart = useQuoteCartStore()
const router = useRouter()
// 品牌参数化（构建期注入，支持多租户白标）：默认北京合胜+显示 logo；VITE_SHOW_LOGO=false 则隐藏 logo
const brandName = import.meta.env.VITE_BRAND_NAME || '北京合胜'
const showLogo = import.meta.env.VITE_SHOW_LOGO !== 'false'
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

// 左侧一级导航折叠（localStorage 持久化）：折叠后只剩图标，子菜单悬浮弹出
const navCollapsed = ref(localStorage.getItem('ph-nav-collapsed') === '1')
function toggleNav() {
  navCollapsed.value = !navCollapsed.value
  localStorage.setItem('ph-nav-collapsed', navCollapsed.value ? '1' : '0')
}

// 移动端适配：≤768px 视为手机——侧栏转覆盖式抽屉（汉堡唤出/遮罩关闭/点菜单自动收起）
const isMobile = ref(false)
const mobileNavOpen = ref(false)
let mq: MediaQueryList | null = null
function applyMq(matches: boolean) {
  isMobile.value = matches
  if (!matches) mobileNavOpen.value = false
}
const onMqChange = (e: MediaQueryListEvent) => applyMq(e.matches)
onMounted(() => {
  mq = window.matchMedia('(max-width: 768px)')
  applyMq(mq.matches)
  mq.addEventListener('change', onMqChange)
})
onUnmounted(() => { mq?.removeEventListener('change', onMqChange) })
function onNavSelect() {
  if (isMobile.value) mobileNavOpen.value = false
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
    <el-aside
      :width="isMobile ? '248px' : (navCollapsed ? '64px' : '210px')"
      class="aside"
      :class="{ collapsed: navCollapsed && !isMobile, mobile: isMobile, 'mobile-open': isMobile && mobileNavOpen }"
    >
      <div class="brand">
        <div v-if="showLogo" class="logo"><img :src="logoUrl" class="logo-img" alt="ProductHub" /></div>
        <div v-show="!navCollapsed || isMobile" class="brand-text">ProductHub<br /><small>{{ brandName }} · 产品中台</small></div>
      </div>
      <el-menu
        :default-active="route.path" router class="nav-menu"
        :collapse="navCollapsed && !isMobile" :collapse-transition="false"
        @select="onNavSelect"
      >
        <el-menu-item-group title="业务">
          <el-menu-item index="/skus"><el-icon><Goods /></el-icon><template #title>产品库</template></el-menu-item>
          <el-menu-item index="/configure"><el-icon><Box /></el-icon><template #title>配置看板</template></el-menu-item>
          <el-menu-item index="/quotations"><el-icon><Document /></el-icon><template #title>报价单</template></el-menu-item>
          <el-menu-item index="/suppliers"><el-icon><ShoppingCart /></el-icon><template #title>供应商与采购件</template></el-menu-item>
        </el-menu-item-group>
        <el-sub-menu index="/admin">
          <template #title><el-icon><Setting /></el-icon><span>系统设置</span></template>
          <el-menu-item index="/settings/general">通用设置</el-menu-item>
          <template v-if="auth.isAdmin">
            <el-menu-item index="/admin/templates">产品模板</el-menu-item>
            <el-menu-item index="/admin/import">数据导入</el-menu-item>
            <el-menu-item index="/admin/users">用户管理</el-menu-item>
          </template>
        </el-sub-menu>
      </el-menu>
      <div class="aside-foot">
        <el-tooltip :content="navCollapsed ? '展开导航' : '收起导航'" placement="right" :disabled="!navCollapsed">
          <el-button text class="fold-btn" @click="toggleNav">
            <el-icon :size="18"><component :is="navCollapsed ? Expand : Fold" /></el-icon>
            <span v-show="!navCollapsed">收起导航</span>
          </el-button>
        </el-tooltip>
      </div>
    </el-aside>
    <!-- 移动端抽屉遮罩 -->
    <div v-if="isMobile && mobileNavOpen" class="mobile-backdrop" @click="mobileNavOpen = false" />
    <el-container>
      <el-header class="topbar">
        <el-button v-if="isMobile" text class="hamburger" @click="mobileNavOpen = true">
          <el-icon :size="22"><Expand /></el-icon>
        </el-button>
        <div class="topbar-search">
          <el-autocomplete
            v-model="searchText"
            :fetch-suggestions="fetchSuggestions"
            placeholder="搜索 SKU 编码 / 名称 / 成品件…"
            style="width: 100%"
            clearable
            @select="onSelectSuggestion as any"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
            <template #default="{ item }">
              <el-tag size="small" style="margin-right: 6px">{{ item.kind }}</el-tag>
              <span>{{ item.value }}</span>
            </template>
          </el-autocomplete>
        </div>
        <div class="topbar-right">
          <el-badge :value="cart.itemCount" :hidden="!cart.itemCount" class="cart-badge">
            <el-button text @click="router.push('/quotations')">
              <el-icon size="20"><Document /></el-icon><span class="btn-label">&nbsp;当前报价单</span>
            </el-button>
          </el-badge>
          <el-dropdown>
            <span class="user-trigger">
              <span class="avatar">{{ avatarText }}</span>
              <span class="user-name">{{ auth.user?.display_name ?? '…' }}</span>
              <el-tag size="small" type="info" effect="plain" class="role-tag">
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
.aside {
  border-right: 1px solid var(--el-border-color-light); background: var(--el-bg-color);
  display: flex; flex-direction: column; overflow: hidden;
  transition: width var(--ph-duration-base) var(--ph-ease);
}
.brand { display: flex; align-items: center; gap: 10px; padding: 16px; flex-shrink: 0; }
.aside.collapsed .brand { justify-content: center; padding: 16px 0; }
/* 折叠态：隐藏分组标题（64px 容不下）；菜单与底部收起条 */
.aside.collapsed :deep(.el-menu-item-group__title) { display: none; }
.nav-menu:not(.el-menu--collapse) { width: 100%; }
.nav-menu { flex: 1; overflow-y: auto; overflow-x: hidden; }
.aside-foot { flex-shrink: 0; border-top: 1px solid var(--el-border-color-lighter); padding: 6px; }
.fold-btn {
  width: 100%; height: 40px; justify-content: flex-start; gap: 8px;
  color: var(--el-text-color-secondary); padding-left: 20px;
}
.aside.collapsed .fold-btn { justify-content: center; padding-left: 0; }
.fold-btn:hover { color: var(--ph-brand-600); background: var(--ph-gray-50); }
.logo {
  width: 34px; height: 34px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.logo-img { width: 100%; height: 100%; object-fit: contain; display: block; }
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
.topbar-search { width: 360px; }
.topbar-right { display: flex; align-items: center; }
.cart-badge { margin-right: 18px; }
.user-trigger { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px; outline: none; }
.avatar {
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--ph-brand-600); color: var(--el-color-white);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 500;
}
.user-name { color: var(--el-text-color-regular); }

/* ── 移动端（≤768px）：侧栏转覆盖式抽屉 + 顶栏精简，消除横向溢出 ── */
.mobile-backdrop {
  position: fixed; inset: 0; z-index: 1999;
  background: rgba(0, 0, 0, 0.45);
}
@media (max-width: 768px) {
  .aside.mobile {
    position: fixed; top: 0; bottom: 0; left: -264px; z-index: 2000;
    transition: left var(--ph-duration-base) var(--ph-ease);
    box-shadow: var(--ph-shadow-lg);
  }
  .aside.mobile.mobile-open { left: 0; }
  .aside-foot { display: none; }
  .topbar { padding: 0 10px; gap: 8px; }
  .hamburger { flex-shrink: 0; padding: 4px; }
  .topbar-search { width: auto; flex: 1; min-width: 0; }
  .cart-badge { margin-right: 6px; }
  .topbar-right .btn-label { display: none; }
  .user-name { display: none; }
  .role-tag { display: none; }
}
</style>
