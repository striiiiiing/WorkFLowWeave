import { defineComponent, h, effectScope } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { describe, it, expect, vi } from 'vitest'
import { useSourceEditor } from '@/modules/resources/composables/useSourceEditor'
import { createResource } from '@/modules/resources/model/public'
import { filterSources } from '@/modules/resources/model/public'
import { resourcesApiKey } from '@/modules/resources/api/dependencies'
import SourceConfigEditor from '@/modules/resources/ui/SourceConfigEditor.vue'
import SourceSummary from '@/modules/resources/ui/SourceSummary.vue'
import SourceFileFields from '@/modules/resources/ui/SourceFileFields.vue'
import { ApiError } from '@/shared/api/errors'
import type {
  SourceConfig,
  SourceConfigEditorGateway,
  SourceOverride,
  SourceSaveTarget,
} from '@/modules/resources/model/public'

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
  createTextReference: vi.fn().mockImplementation(async (path: string) => ({
    kind: 'file',
    file_type: 'text',
    path,
  })),
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
          reason: '请在运行 WorkFLowWeave 后端的环境中安装 qqmusic-mcp',
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
    expect(wrapper.text()).toContain('请在运行 WorkFLowWeave 后端的环境中安装 qqmusic-mcp')
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

it('renders and searches a CLI source', async () => {
  const cliSource: SourceConfig = {
    ...source(),
    call: { kind: 'cli', mode: 'argv', executable: 'log-reader', argv: ['--recent'], cwd: null },
  }
  const summary = mount(SourceSummary, { props: { source: cliSource } })
  expect(summary.text()).toContain('log-reader')
  expect(filterSources([cliSource], 'log-reader', 'all', () => undefined)).toEqual([cliSource])
  summary.unmount()
})

it('keeps source usage filtering independent of resource kind', () => {
  const sources = [source()]
  expect(filterSources(sources, '', 'unused', () => undefined)).toEqual([])
  expect(filterSources(sources, '', 'all', () => undefined)).toEqual(sources)
  expect(
    filterSources(sources, '', 'shared', () => [{ id: 'wf', name: 'W', detached: false }]),
  ).toEqual(sources)
})

it.each(['shared-resource', 'workflow-draft'] as const)(
  'saves a file reference to %s and retries the resource without creating the file again',
  async (kind) => {
    api.createTextReference.mockReset().mockImplementation(async (path: string) => ({
      kind: 'file',
      file_type: 'text',
      path,
    }))
    const saved = vi
      .fn()
      .mockRejectedValueOnce(new Error('来源保存失败'))
      .mockResolvedValue(undefined)
    const target: SourceSaveTarget =
      kind === 'shared-resource'
        ? { kind, resourceId: 'logs' }
        : { kind, workflowId: 'wf', sourceId: 'logs' }
    const { wrapper } = setup(target, { resolve: async () => source(), save: saved })
    await flushPromises()
    await wrapper.get('input[value="file"]').setValue(true)
    await flushPromises()
    const fields = wrapper.getComponent(SourceFileFields)
    fields.getComponent(ElSelect).vm.$emit('update:modelValue', 'text')
    await fields.get('input[aria-label="相对保存位置"]').setValue('notes/online.txt')
    await fields.get('input[type="checkbox"]').setValue(true)
    await fields.get('textarea').setValue('online body')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('来源保存失败')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.createTextReference).toHaveBeenCalledTimes(1)
    expect(saved).toHaveBeenLastCalledWith(
      target,
      expect.objectContaining({
        call: { kind: 'file', file_type: 'text', path: 'notes/online.txt' },
      }),
    )
    wrapper.unmount()
  },
)

it('renders and searches the file type and relative path', () => {
  const fileSource: SourceConfig = {
    ...source(),
    call: { kind: 'file', file_type: 'text', path: 'team/notes.txt' },
  }
  const summary = mount(SourceSummary, { props: { source: fileSource } })
  expect(summary.text()).toContain('文本 / team/notes.txt')
  expect(filterSources([fileSource], 'team/notes', 'all', () => undefined)).toEqual([fileSource])
  summary.unmount()
})
