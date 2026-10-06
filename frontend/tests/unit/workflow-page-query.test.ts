import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import WorkflowEditPage from '@/pages/workflows/WorkflowEditPage.vue'
import { resourcesApiKey } from '@/modules/resources/public'
import { systemApiKey } from '@/modules/system/public'
import { workflowsApiKey } from '@/modules/workflows/public'
import { createResource } from '@/modules/resources/model/public'
import type { ResourcesApi } from '@/modules/resources/api/resourcesApi'
import type { SystemApi } from '@/modules/system/api/systemApi'
import type { WorkflowsApi } from '@/modules/workflows/api/workflowsApi'
import type { WorkflowEditorController } from '@/modules/workflows/public'
import { agentsApiKey } from '@/modules/agents/public'

const router = { push: vi.fn(), replace: vi.fn() }
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: {}, query: {} }),
  useRouter: () => router,
}))

const source = { ...createResource('sources'), id: 'logs', collector: 'mock', enabled: true }
const SourceStepStub = defineComponent({
  props: { gateway: { type: Object, required: true }, editor: { type: Object, required: true } },
  setup(props) {
    async function publish() {
      const editor = props.editor as WorkflowEditorController
      editor.addSourceId('logs')
      editor.applySource('logs', source)
      await (
        props.gateway as { save: (target: unknown, value: typeof source) => Promise<void> }
      ).save({ kind: 'shared-resource', resourceId: 'logs' }, source)
      editor.restoreSharedSource('logs')
    }
    return { publish }
  },
  template: '<button data-test="publish" @click="publish">publish</button>',
})

function setup(options: { replace?: () => Promise<unknown> } = {}) {
  const workflowsApi = {
    list: vi.fn().mockResolvedValue([]),
    get: vi.fn(),
    create: vi.fn(),
    replace: vi.fn(options.replace ?? (() => Promise.resolve())),
    delete: vi.fn(),
  } as unknown as WorkflowsApi
  const resourcesApi = {
    list: vi.fn((kind: string) => Promise.resolve(kind === 'sources' ? [source] : [])),
    resolveSource: vi.fn().mockResolvedValue(source),
    create: vi.fn().mockResolvedValue(source),
    replace: vi.fn().mockResolvedValue(source),
    protectCredential: vi.fn(),
  } as unknown as ResourcesApi
  const systemApi = { plugins: vi.fn().mockResolvedValue([]) } as unknown as SystemApi
  const wrapper = mount(WorkflowEditPage, {
    global: {
      plugins: [ElementPlus],
      provide: {
        [workflowsApiKey as symbol]: workflowsApi,
        [resourcesApiKey as symbol]: resourcesApi,
        [systemApiKey as symbol]: systemApi,
        [agentsApiKey as symbol]: { tools: vi.fn().mockResolvedValue([]) },
      },
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
        SourceStepCard: SourceStepStub,
        FanOutTaskCard: true,
        FanInCard: true,
        NotificationCard: true,
        BackupMatrix: true,
      },
    },
  })
  return { wrapper, workflowsApi, resourcesApi }
}

afterEach(() => {
  router.push.mockReset()
  router.replace.mockReset()
})

describe('workflow page query ownership', () => {
  it('refreshes the shared workflow list once when the window regains focus', async () => {
    const { wrapper, workflowsApi } = setup()
    await flushPromises()
    expect(workflowsApi.list).toHaveBeenCalledTimes(1)

    window.dispatchEvent(new Event('focus'))
    await flushPromises()

    expect(workflowsApi.list).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('refreshes usage once after publishing a shared source', async () => {
    const { wrapper, workflowsApi, resourcesApi } = setup()
    await flushPromises()
    await wrapper.get('[data-test="publish"]').trigger('click')
    await flushPromises()

    expect(resourcesApi.replace).toHaveBeenCalledTimes(1)
    expect(workflowsApi.list).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('资源已保存，工作流仍待保存')
    wrapper.unmount()
  })
})
