/** @type {import('tailwindcss').Config} */
export default {
  // 使用 class 策略控制深色模式。
  // App.vue 会根据系统偏好或用户手动选择，在 html 上切换 dark 类。
  darkMode: 'class',

  // 告诉 Tailwind 扫描哪些文件里的 class 名。
  content: ['./index.html', './src/**/*.{vue,js}'],

  // 主题扩展。
  theme: {
    extend: {
      // 使用系统无衬线字体栈，接近 Apple / Vercel 的干净观感。
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Inter',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'Noto Sans SC',
          'sans-serif',
        ],
      },
    },
  },

  // 当前暂不需要额外插件，保持依赖简单。
  plugins: [],
}
