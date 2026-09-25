import { defineAsyncComponent } from 'vue'

// API factories share this module's public entry; heavy editors/reports load only when rendered.
export const SourceConfigEditor = defineAsyncComponent(() => import('./SourceConfigEditor.vue'))
export const SourceEditorSession = defineAsyncComponent(() => import('./SourceEditorSession.vue'))
export const AIProviderEditor = defineAsyncComponent(() => import('./AIProviderEditor.vue'))
export const ChannelEditor = defineAsyncComponent(() => import('./ChannelEditor.vue'))
