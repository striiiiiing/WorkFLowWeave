import { defineAsyncComponent } from 'vue'

// API factories share this module's public entry; heavy editors/reports load only when rendered.
export const PhaseReport = defineAsyncComponent(() => import('./PhaseReport.vue'))
export const RunProcessDetails = defineAsyncComponent(() => import('./RunProcessDetails.vue'))
