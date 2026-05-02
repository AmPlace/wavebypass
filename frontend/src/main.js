// 引入 Vue 应用创建函数。
import { createApp } from 'vue'

// 引入 Pinia 创建函数。
import { createPinia } from 'pinia'

// 引入根组件。
import App from './App.vue'

// 引入全局样式，内部包含 Tailwind 的基础层、组件层和工具类。
import './style.css'

// 创建 Vue 应用实例。
const app = createApp(App)

// 注册 Pinia，全局组件都可以使用 store。
app.use(createPinia())

// 挂载到 index.html 中的 #app 节点。
app.mount('#app')
