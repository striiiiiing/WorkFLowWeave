import { errorFormatterKey } from '@/shared/async/errorFormatter'
import { errorMessage } from './errorMessage'
import type { App } from 'vue'
import { createHttpClient, type HttpClient } from '@/shared/api'
import { createResourcesApi, resourcesApiKey } from '@/modules/resources/public'
import { createWorkflowsApi, workflowsApiKey } from '@/modules/workflows/public'
import { createRunsApi, runsApiKey } from '@/modules/runs/public'
import { createAgentsApi, agentsApiKey } from '@/modules/agents/public'
import { createSystemApi, systemApiKey } from '@/modules/system/public'

export function createApplicationServices(http: HttpClient = createHttpClient()) {
  return {
    resourcesApi: createResourcesApi(http),
    workflowsApi: createWorkflowsApi(http),
    runsApi: createRunsApi(http),
    agentsApi: createAgentsApi(http),
    systemApi: createSystemApi(http),
  }
}
export type ApplicationServices = ReturnType<typeof createApplicationServices>
export function provideApplicationServices(app: App, services: ApplicationServices) {
  app.provide(errorFormatterKey, errorMessage)
  app.provide(resourcesApiKey, services.resourcesApi)
  app.provide(workflowsApiKey, services.workflowsApi)
  app.provide(runsApiKey, services.runsApi)
  app.provide(agentsApiKey, services.agentsApi)
  app.provide(systemApiKey, services.systemApi)
  return app
}
