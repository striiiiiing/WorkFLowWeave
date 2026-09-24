import { effectScope } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { useCapabilities, useSystemApi } from '@/modules/system/public'
import { sourceUsage, useWorkflowList, type WorkflowDefinition } from '@/modules/workflows/public'
import type { SourceUsageView } from '@/modules/resources/public'
import type { SchemaCapability } from '@/shared/schema/types'

describe('P1 public consumers', () => {
  it('uses injected list/catalog APIs once and aborts both when the page scope leaves', async () => {
    const list = vi.fn().mockResolvedValue([])
    const plugins = vi.fn().mockResolvedValue([])
    const scope = effectScope()
    const queries = scope.run(() => ({
      workflows: useWorkflowList({ list }),
      capabilities: useCapabilities({ plugins }),
    }))!
    await flushPromises()
    expect(queries.workflows.data.value).toEqual([])
    expect(queries.capabilities.data.value).toEqual([])
    expect(list).toHaveBeenCalledTimes(1)
    expect(plugins).toHaveBeenCalledTimes(1)
    const catalog: readonly SchemaCapability[] = queries.capabilities.data.value!
    expect(catalog).toEqual([])
    await queries.workflows.refresh()
    expect(list).toHaveBeenCalledTimes(2)
    scope.stop()
    expect(list.mock.lastCall![0].aborted).toBe(true)
    expect(plugins.mock.lastCall![0].aborted).toBe(true)
  })

  it('fails explicitly when the module dependency is missing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(() =>
      mount({
        setup() {
          useSystemApi()
          return () => null
        },
      }),
    ).toThrow('缺少 systemApi 注入')
    warn.mockRestore()
  })

  it('projects shared and detached source usage into the resource-owned view', () => {
    const workflow = (id: string, detached: boolean) =>
      ({
        id,
        name: id === 'shared' ? 'Shared workflow' : '',
        sources: ['source'],
        source_overrides: detached ? { source: { source: { id: 'source' } } } : {},
      }) as WorkflowDefinition
    const workflows = [workflow('shared', false), workflow('detached', true)]
    const views: SourceUsageView[] = sourceUsage('source', workflows)
    expect(views).toEqual([
      { id: 'shared', name: 'Shared workflow', detached: false },
      { id: 'detached', name: 'detached', detached: true },
    ])
    expect(sourceUsage('unused', workflows)).toEqual([])
  })
})
