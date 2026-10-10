import { createMemoryHistory, createRouter } from 'vue-router'
import { expect, it } from 'vitest'
import { router as applicationRouter } from '@/app/router'

it('keeps the established route paths, names and query state', async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: applicationRouter.options.routes.map((record) => ({
      ...record,
      component: { template: '<div />' },
    })),
  })

  await router.push('/workflows/new?stage=sources')
  expect(router.currentRoute.value.name).toBe('workflow-new')
  expect(router.currentRoute.value.query).toEqual({ stage: 'sources' })

  await router.push('/workflows/daily/edit?stage=channels&advanced=1')
  expect(router.currentRoute.value.name).toBe('workflow-edit')
  expect(router.currentRoute.value.params.id).toBe('daily')
  expect(router.currentRoute.value.query).toEqual({ stage: 'channels', advanced: '1' })

  await router.push('/runs/run-1?tab=notify')
  expect(router.currentRoute.value.name).toBe('run-detail')
  expect(router.currentRoute.value.query).toEqual({ tab: 'notify' })

})
