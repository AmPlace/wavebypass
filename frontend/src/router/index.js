import { createRouter, createWebHashHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/',
    name: 'radio',
    component: () => import('../views/Home.vue'),
  },
  {
    path: '/iptv',
    name: 'iptv',
    component: () => import('../views/IptvHome.vue'),
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('../views/AdminView.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/market',
    name: 'market',
    component: () => import('../views/MarketView.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/admin/epg',
    name: 'epg-debug',
    component: () => import('../views/EpgDebug.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/setup',
    name: 'setup',
    component: () => import('../views/SetupView.vue'),
    meta: { authPage: true },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { authPage: true },
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.booted) {
    try {
      await auth.boot()
    } catch {
      auth.booted = true
      auth.status = 'offline'
    }
  }

  if (auth.requiresSetup && to.path !== '/setup') {
    return { path: '/setup' }
  }

  if (!auth.requiresSetup && to.path === '/setup') {
    return { path: '/' }
  }

  if (!to.meta.authPage && !auth.setup.anonymousBrowse && !auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAdmin && !auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.path === '/login' && auth.requiresSetup) {
    return { path: '/setup' }
  }

  if (to.path === '/login' && auth.isAuthenticated) {
    return { path: String(to.query.redirect || '/') }
  }

  return true
})

export default router
