import { createApplicationServices } from './bootstrap'
// Only app owns this instance. Legacy aliases disappear with P7.
export const services = createApplicationServices()
export const { resourcesApi, workflowsApi, runsApi, agentsApi, systemApi } = services
