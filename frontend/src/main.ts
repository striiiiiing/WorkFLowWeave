import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import 'element-plus/es/components/message/style/css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './assets/main.css'

createApp(App).use(router).mount('#app')
