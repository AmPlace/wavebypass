// 引入 Vite 配置工具。
import { defineConfig } from 'vite'

// 引入 Vue 单文件组件插件，让 Vite 能识别 .vue 文件。
import vue from '@vitejs/plugin-vue'

// 导出 Vite 配置。
export default defineConfig({
  // 注册 Vue 插件。
  plugins: [vue()],

  // 本地开发服务器配置。
  server: {
    // 允许局域网设备访问，Docker 或手机调试时更方便。
    host: '0.0.0.0',

    // 前端开发端口。
    port: 5173,

    // 开发期把 /api 请求代理到本机后端，避免跨域和路径不一致。
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
