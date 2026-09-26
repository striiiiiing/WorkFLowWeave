import { defineComponent, h, effectScope, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, it, expect, vi } from 'vitest'
import { useSourceEditor } from '@/modules/resources/composables/useSourceEditor'
import { createResource } from '@/modules/resources/model/resources'
import { filterSources } from '@/modules/resources/model/sourceFiltering'
import { createResourcesApi } from '@/modules/resources/api/resourcesApi'
import SourceConfigEditor from '@/modules/resources/ui/SourceConfigEditor.vue'
import type {
  SourceConfig,
  SourceConfigEditorGateway,
  SourceSaveTarget,
  SourceOverride,
} from '@/modules/resources/model/types'

const source = (): SourceConfig => ({
  ...(createResource('sources') as SourceConfig),
  id: 'logs',
  collector: 'mock',
  options: { limit: 3, optional: null },
  template: 'legacy-template',
})
const capabilities = [
  {
    name: 'mock',
    description: '',
    capabilities: [],
    options_schema: { type: 'object' },
    setters_schema: null,
    fields: [],
    count_unit: null,
  },
]
function setup(target: SourceSaveTarget, gateway: SourceConfigEditorGateway) {
  let editor!: ReturnType<typeof useSourceEditor>
  const wrapper = mount(
    defineComponent({
      setup() {
        editor = useSourceEditor({ initial: source(), target }, gateway)
        return () =>
          h(SourceConfigEditor, { editor, target, initial: true, capabilities, protect: vi.fn() })
      },
    }),
    { global: { plugins: [ElementPlus] } },
  )
  return {
    wrapper,
    get editor() {
      return editor
    },
  }
}

describe('single source editor save ownership', () => {
  it('keeps source actions together at the bottom with enablement on the left', async () => {
    const { wrapper } = setup(
      { kind: 'shared-resource', resourceId: 'logs' },
      { resolve: async () => source(), save: vi.fn() },
    )
    await flushPromises()
    const actions = wrapper.get('.source-editor-actions')
    expect(actions.find('[role="switch"]').exists()).toBe(true)
    expect(actions.findAll('button').map((button) => button.text())).toEqual(['取消', '保存资源'])
    expect(actions.element.firstElementChild?.classList.contains('el-switch')).toBe(true)
    wrapper.unmount()
  })

  it.each(['shared-resource', 'workflow-draft'] as const)(
    'uses the same component for %s and only the injected destination writes',
    async (kind) => {
      const request = vi.fn().mockResolvedValue(source())
      const api = createResourcesApi({ request })
      let workflowSnapshot: SourceConfig | undefined
      const target: SourceSaveTarget =
        kind === 'shared-resource'
          ? { kind, resourceId: 'logs' }
          : { kind, workflowId: 'wf', sourceId: 'logs' }
      const gateway: SourceConfigEditorGateway = {
        resolve: api.resolveSource,
        async save(destination, value) {
          if (destination.kind === 'workflow-draft') workflowSnapshot = value
          else await api.replace('sources', destination.resourceId, value)
        },
      }
      const { wrapper, editor } = setup(target, gateway)
      await flushPromises()
      editor.updateOptions({ limit: 8, optional: null })
      await nextTick()
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      if (kind === 'workflow-draft') {
        expect(workflowSnapshot?.options).toEqual({ limit: 8, optional: null })
        expect(request.mock.calls.some(([value]) => value.method === 'PUT')).toBe(false)
      } else
        expect(request).toHaveBeenCalledWith(
          expect.objectContaining({
            method: 'PUT',
            url: '/sources/logs',
            data: expect.objectContaining({
              options: { limit: 8, optional: null },
              template: 'legacy-template',
            }),
          }),
        )
      wrapper.unmount()
    },
  )

  it('retains invalid JSON text, blocks saving the last valid value and resumes after correction', async () => {
    const save = vi.fn()
    const { wrapper, editor } = setup(
      { kind: 'shared-resource', resourceId: 'logs' },
      { resolve: async () => source(), save },
    )
    await flushPromises()
    const collection = wrapper.get('section[aria-label="采集参数"]')
    await collection
      .findAll('button')
      .find((button) => button.text() === '编辑 JSON')!
      .trigger('click')
    const raw = collection.get('textarea')
    await raw.setValue('{')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(save).not.toHaveBeenCalled()
    expect((raw.element as HTMLTextAreaElement).value).toBe('{')
    expect(editor.value.value?.options.limit).toBe(3)
    await raw.setValue('{"limit":0,"optional":null}')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(save).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ options: { limit: 0, optional: null } }),
    )
    wrapper.unmount()
  })

  it('keeps edits and legacy template after a failed save and does not mutate the input', async () => {
    const original = source()
    const save = vi.fn().mockRejectedValue(new Error('写入失败'))
    const { wrapper, editor } = setup(
      { kind: 'shared-resource', resourceId: 'logs' },
      { resolve: async () => original, save },
    )
    await flushPromises()
    editor.updateBasic({ display_name: 'new draft' })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('写入失败')
    expect(editor.value.value?.display_name).toBe('new draft')
    expect(editor.value.value?.template).toBe('legacy-template')
    expect(original.display_name).toBe('')
    wrapper.unmount()
  })

  it('passes sparse overrides to backend resolve and ignores a response after editor disposal', async () => {
    let finish!: (value: SourceConfig) => void
    const resolve = vi.fn().mockImplementation(
      () =>
        new Promise<SourceConfig>((next) => {
          finish = next
        }),
    )
    const override: SourceOverride = { options: { limit: 0 }, setters: {}, template: null }
    const scope = effectScope()
    const editor = scope.run(() =>
      useSourceEditor(
        {
          initial: source(),
          override,
          target: { kind: 'workflow-draft', workflowId: 'wf', sourceId: 'logs' },
        },
        { resolve, save: vi.fn() },
      ),
    )!
    expect(resolve).toHaveBeenCalledWith('logs', override, expect.any(AbortSignal))
    scope.stop()
    finish(source())
    await flushPromises()
    expect(editor.value.value).toBeUndefined()
  })

  it('preserves a failed resolve as an error instead of editing an empty source', async () => {
    const scope = effectScope()
    const editor = scope.run(() =>
      useSourceEditor(
        { initial: source(), target: { kind: 'shared-resource', resourceId: 'logs' } },
        {
          resolve: async () => {
            throw new Error('模板不存在')
          },
          save: vi.fn(),
        },
      ),
    )!
    await flushPromises()
    expect(editor.value.value).toBeUndefined()
    expect(editor.load.error.value).toContain('模板不存在')
    scope.stop()
  })
})

it('does not treat unknown usages as zero and filters shared/independent projections', () => {
  const sources = [source()]
  expect(filterSources(sources, '', 'unused', () => undefined)).toEqual([])
  expect(filterSources(sources, '', 'all', () => undefined)).toEqual(sources)
  expect(
    filterSources(sources, '', 'shared', () => [{ id: 'wf', name: 'W', detached: false }]),
  ).toEqual(sources)
  expect(
    filterSources(sources, '', 'independent', () => [{ id: 'wf', name: 'W', detached: true }]),
  ).toEqual(sources)
})
