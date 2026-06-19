import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../pages/Login.vue') },
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      children: [
        { path: '', redirect: '/skus' },
        { path: 'skus', component: () => import('../pages/SkuList.vue') },
        { path: 'configure', component: () => import('../pages/Configure.vue') },
        { path: 'quotations', component: () => import('../pages/Quotes.vue') },
        { path: 'suppliers', component: () => import('../pages/Suppliers.vue') },
        { path: 'parts', redirect: '/suppliers' },
        { path: 'settings/general', component: () => import('../pages/SettingsGeneral.vue') },
        { path: 'admin/templates', component: () => import('../pages/AdminTemplates.vue') },
        { path: 'admin/import', component: () => import('../pages/AdminImport.vue') },
        { path: 'admin/users', component: () => import('../pages/AdminUsers.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const authed = !!localStorage.getItem('access_token')
  if (!authed && to.path !== '/login') return '/login'
  if (authed && to.path === '/login') return '/skus'
})
