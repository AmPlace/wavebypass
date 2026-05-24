import { createRouter, createWebHashHistory } from 'vue-router'

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
  },
  {
    path: '/admin/epg',
    name: 'epg-debug',
    component: () => import('../views/EpgDebug.vue'),
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
