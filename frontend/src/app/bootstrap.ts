import { errorFormatterKey } from '@/shared/async/errorFormatter'
import { errorMessage } from './errorMessage'
import type { App } from 'vue'
import { createHttpClient, type HttpClient } from '@/shared/api'
import { createResourcesApi } from '@/modules/resources/api/resourcesApi'
import { resourcesApiKey } from '@/modules/resources/api/dependencies'
import { createWorkflowsApi } from '@/modules/workflows/api/workflowsApi'
import { workflowsApiKey } from '@/modules/workflows/api/dependencies'
import { createRunsApi } from '@/modules/runs/api/runsApi'
import { runsApiKey } from '@/modules/runs/api/dependencies'
import { createAgentsApi } from '@/modules/agents/api/agentsApi'
import { agentsApiKey } from '@/modules/agents/api/dependencies'
import { createSystemApi } from '@/modules/system/api/systemApi'
import { systemApiKey } from '@/modules/system/api/dependencies'

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
