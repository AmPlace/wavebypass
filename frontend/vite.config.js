import { defineConfig } from 'vite'

import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig(({ mode }) => {
  const isDesktop = mode === 'desktop'

  return {
    base: isDesktop ? './' : '/',
    plugins: [
      vue(),
      !isDesktop && VitePWA({
        registerType: 'autoUpdate',
        includeAssets: ['logos/*.png'],
        manifest: {
          name: 'WaveBypass Radio',
          short_name: 'WaveBypass',
          description: '极简电台聚合播放器',
          theme_color: '#f8f8f7',
          background_color: '#f8f8f7',
          display: 'standalone',
          orientation: 'any',
          start_url: '/',
          scope: '/',
          icons: [
            { src: '/icons/apple-touch-icon.png', sizes: '180x180', type: 'image/png' },
            { src: '/icons/android-chrome-192x192.png', sizes: '192x192', type: 'image/png' },
            { src: '/icons/android-chrome-512x512.png', sizes: '512x512', type: 'image/png' },
            { src: '/icons/android-chrome-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          ],
        },
        workbox: {
          globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
          navigateFallback: 'index.html',
          navigateFallbackDenylist: [/^\/api/],
          runtimeCaching: [
            {
              // /api/stations 和 /api/config：stale-while-revalidate
              urlPattern: /^\/api\/(stations|config)$/,
              handler: 'StaleWhileRevalidate',
              options: {
                cacheName: 'api-config',
                expiration: { maxEntries: 10, maxAgeSeconds: 3600 },
              },
            },
            {
              urlPattern: /\/logos\/.*\.(png|jpg|svg)$/,
              handler: 'CacheFirst',
              options: {
                cacheName: 'station-logos',
                expiration: { maxEntries: 100, maxAgeSeconds: 30 * 24 * 3600 },
              },
            },
          ],
        },
      }),
    ].filter(Boolean),

    server: {
      host: '0.0.0.0',

      port: 5173,

      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          xfwd: true,
        },
      },
    },
  }
})
