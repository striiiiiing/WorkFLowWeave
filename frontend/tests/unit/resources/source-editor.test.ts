import { defineComponent, h, effectScope } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, it, expect, vi } from 'vitest'
import { useSourceEditor } from '@/modules/resources/composables/useSourceEditor'
import { createResource } from '@/modules/resources/model/resources'
import { filterSources } from '@/modules/resources/model/sourceFiltering'
import { resourcesApiKey } from '@/modules/resources/api/dependencies'
import SourceConfigEditor from '@/modules/resources/ui/SourceConfigEditor.vue'
import SourceSummary from '@/modules/resources/ui/SourceSummary.vue'
import { ApiError } from '@/shared/api/errors'
import type {
  SourceConfig,
  SourceConfigEditorGateway,
  SourceOverride,
  SourceSaveTarget,
} from '@/modules/resources/model/types'

const source = (): SourceConfig => ({
  ...(createResource('sources') as SourceConfig),
  id: 'logs',
  call: { kind: 'mcp', server: 'server', tool: 'read', arguments: { saved: true } },
})
const api = {
  list: vi.fn().mockResolvedValue([{ id: 'server', enabled: true }]),
  mcpCatalog: vi.fn().mockResolvedValue({
    entries: [{ server: 'server', tool: 'read', description: '' }],
    next_cursor: null,
    incomplete: false,
    load_servers: [],
    servers: [],
  }),
  describeMcpTool: vi.fn().mockResolvedValue({
    name: 'read',
    inputSchema: { type: 'object', properties: { limit: { type: 'integer' } } },
  }),
  loadMcpCatalog: vi.fn(),
}
function setup(target: SourceSaveTarget, gateway: SourceConfigEditorGateway, initial = source()) {
  let editor!: ReturnType<typeof useSourceEditor>
  const wrapper = mount(
    defineComponent({
      setup() {
        editor = useSourceEditor({ initial, target }, gateway)
        return () => h(SourceConfigEditor, { editor, target, initial: true })
      },
    }),
    { global: { plugins: [ElementPlus], provide: { [resourcesApiKey as symbol]: api } } },
  )
  return {
    wrapper,
    get editor() {
      return editor
    },
  }
}

describe('MCP/CLI source editor', () => {
  it('shows the backend startup diagnosis when loading a tool catalog fails', async () => {
    api.loadMcpCatalog.mockRejectedValueOnce(
      new ApiError(400, {
        code: 'mcp_directory_failed',
        message: 'MCP 工具目录加载失败',
        details: {
          exception_type: 'FileNotFoundError',
          reason: '请在运行 LogAgent 后端的环境中安装 qqmusic-mcp',
        },
      }),
    )
    const { wrapper } = setup(
      { kind: 'shared-resource', resourceId: 'logs' },
      { resolve: async () => source(), save: vi.fn() },
    )
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '加载/刷新目录')!
      .trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请在运行 LogAgent 后端的环境中安装 qqmusic-mcp')
    expect(wrapper.text()).toContain('FileNotFoundError')
    expect(wrapper.text()).not.toContain('ApiError:')
    wrapper.unmount()
  })

  it('lets the save button submit when Element Plus number inputs fail native step validation', async () => {
    const { wrapper } = setup(
      { kind: 'shared-resource', resourceId: 'logs' },
      { resolve: async () => source(), save: vi.fn() },
    )
    await flushPromises()
    const button = wrapper.get('button[type="submit"]').element as HTMLButtonElement
    expect(button.formNoValidate).toBe(true)
    wrapper.unmount()
  })

  it.each(['shared-resource', 'workflow-draft'] as const)(
    'saves %s only through its gateway',
    async (kind) => {
      const saved = vi.fn()
      const target: SourceSaveTarget =
        kind === 'shared-resource'
          ? { kind, resourceId: 'logs' }
          : { kind, workflowId: 'wf', sourceId: 'logs' }
      const { wrapper, editor } = setup(target, { resolve: async () => source(), save: saved })
      await flushPromises()
      editor.updateCall({
        kind: 'mcp',
        server: 'server',
        tool: 'read',
        arguments: { saved: true, limit: 3 },
      })
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(saved).toHaveBeenCalledWith(
        target,
        expect.objectContaining({
          call: {
            kind: 'mcp',
            server: 'server',
            tool: 'read',
            arguments: { saved: true, limit: 3 },
          },
        }),
      )
      wrapper.unmount()
    },
  )

  it('keeps an edited call after a failed save without mutating the initial source', async () => {
    const original = source()
    const { wrapper, editor } = setup(
      { kind: 'shared-resource', resourceId: 'logs' },
      { resolve: async () => original, save: vi.fn().mockRejectedValue(new Error('写入失败')) },
    )
    await flushPromises()
    editor.updateCall({ kind: 'cli', mode: 'shell', command: 'date', cwd: '/tmp' })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('写入失败')
    expect(editor.value.value?.call).toEqual({
      kind: 'cli',
      mode: 'shell',
      command: 'date',
      cwd: '/tmp',
    })
    expect(original.call?.kind).toBe('mcp')
    wrapper.unmount()
  })

  it('passes sparse arguments and limits to resolve, then ignores a disposed response', async () => {
    let finish!: (value: SourceConfig) => void
    const resolve = vi.fn().mockImplementation(
      () =>
        new Promise<SourceConfig>((next) => {
          finish = next
        }),
    )
    const override: SourceOverride = {
      arguments: { limit: 2 },
      limits: { item_tokens: 100, field_tokens: null },
    }
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
})

it('renders and edits a collector source without a call', async () => {
  const pluginSource: SourceConfig = {
    ...source(),
    collector: 'qwenpaw_flomo',
    call: null,
    options: { kind: 'hourly', limit: 8 },
  }
  const summary = mount(SourceSummary, { props: { source: pluginSource } })
  expect(summary.text()).toContain('插件 / qwenpaw_flomo')
  expect(filterSources([pluginSource], 'qwenpaw_flomo', 'all', () => undefined)).toEqual([
    pluginSource,
  ])
  summary.unmount()

  const saved = vi.fn()
  const { wrapper, editor } = setup(
    { kind: 'shared-resource', resourceId: pluginSource.id },
    { resolve: async () => pluginSource, save: saved },
    pluginSource,
  )
  await flushPromises()
  expect(wrapper.text()).toContain('采集插件')
  editor.updateOptions({ kind: 'hourly', limit: 10 })
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(saved).toHaveBeenCalledWith(
    { kind: 'shared-resource', resourceId: pluginSource.id },
    expect.objectContaining({
      collector: 'qwenpaw_flomo',
      call: null,
      options: { kind: 'hourly', limit: 10 },
    }),
  )
  wrapper.unmount()
})

it('keeps source usage filtering independent of resource kind', () => {
  const sources = [source()]
  expect(filterSources(sources, '', 'unused', () => undefined)).toEqual([])
  expect(filterSources(sources, '', 'all', () => undefined)).toEqual(sources)
  expect(
    filterSources(sources, '', 'shared', () => [{ id: 'wf', name: 'W', detached: false }]),
  ).toEqual(sources)
})
