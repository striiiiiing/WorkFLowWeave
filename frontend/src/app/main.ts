import { provideApplicationServices } from './bootstrap'
import { services } from './services'
import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import 'element-plus/es/components/message/style/css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/main.css'

provideApplicationServices(createApp(App), services).use(router).mount('#app')
