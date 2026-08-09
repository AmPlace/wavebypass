export const appRoutes = [
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
    path: '/settings',
    component: () => import('../views/settings/SettingsView.vue'),
    redirect: '/settings/sources',
    meta: { requiresAdmin: true },
    children: [
      {
        path: 'sources',
        name: 'settings-sources',
        component: () => import('../views/settings/LiveSourcesSettings.vue'),
      },
      {
        path: 'epg',
        component: () => import('../views/settings/EpgSettingsView.vue'),
        redirect: '/settings/epg/sources',
        children: [
          {
            path: 'sources',
            name: 'settings-epg-sources',
            component: () => import('../views/settings/EpgSourcesSettings.vue'),
          },
          {
            path: 'matching',
            name: 'settings-epg-matching',
            component: () => import('../views/settings/EpgMatchingSettings.vue'),
          },
          {
            path: ':epgPath(.*)*',
            redirect: '/settings/epg/sources',
          },
        ],
      },
      {
        path: 'security',
        name: 'settings-security',
        component: () => import('../views/settings/SecuritySettings.vue'),
      },
      {
        path: ':settingsPath(.*)*',
        redirect: '/settings/sources',
      },
    ],
  },
  {
    path: '/admin',
    redirect: '/settings/sources',
    meta: { requiresAdmin: true, compatibilityRoute: true },
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
    meta: { requiresAdmin: true, legacyUi: true },
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
