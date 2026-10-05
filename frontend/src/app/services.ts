import { createApplicationServices } from './bootstrap'
export const services = createApplicationServices()
export const { resourcesApi, workflowsApi, runsApi, agentsApi, systemApi } = services
