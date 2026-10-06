import { effectScope, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElPopconfirm } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SourceStepCard from '@/modules/workflows/ui/SourceStepCard.vue'
import { createResource } from '@/modules/resources/model/public'
import { createWorkflow, useWorkflowEditor } from '@/modules/workflows/public'
import type { SourceConfigEditorGateway } from '@/modules/resources/public'

const source = { ...createResource('sources'), id: 'logs', collector: 'mock', enabled: true }
const override = { source, options: {}, setters: {}, template: null }

function setup(sources = [source]) {
  const scope = effectScope()
  const editor = scope.run(() =>
    useWorkflowEditor({
      identity: 'workflow',
      data: undefined,
    }),
  )!
  editor.replace({
    ...createWorkflow(),
    id: 'workflow',
    sources: ['logs'],
    source_overrides: { logs: override },
  })
  const gateway: SourceConfigEditorGateway = {
    resolve: vi.fn().mockResolvedValue(source),
    save: vi.fn().mockResolvedValue(undefined),
  }
  const wrapper = mount(SourceStepCard, {
    props: {
      editor,
      sources,
      usage: () => [{ id: 'workflow', name: 'workflow', detached: true }],
      gateway,
      capabilities: [],
      protect: vi.fn(),
    },
    global: { plugins: [ElementPlus] },
  })
  return { editor, gateway, scope, wrapper }
}

afterEach(() => vi.restoreAllMocks())

describe('workflow source confirmation', () => {
  it('does not publish a detached source until the confirmation is accepted', async () => {
    const { editor, gateway, scope, wrapper } = setup()
    const button = wrapper.findAll('button').find((item) => item.text() === '保存为共用数据源')
    expect(button).toBeDefined()

    await button!.trigger('click')
    expect(gateway.save).not.toHaveBeenCalled()
    expect(editor.draft.value?.source_overrides.logs).toBeDefined()

    const popups = wrapper.findAllComponents(ElPopconfirm)
    expect(popups).toHaveLength(2)
    await popups[1].vm.$emit('confirm', new MouseEvent('click'))
    await flushPromises()
    expect(gateway.save).toHaveBeenCalledTimes(1)
    scope.stop()
  })

  it('keeps the detached override when the shared catalog entry was deleted', async () => {
    const { editor, scope, wrapper } = setup([])
    expect(wrapper.text()).toContain('资源中心中已不存在此来源')

    const restore = wrapper.findAll('button').find((item) => item.text() === '恢复共用配置')
    expect(restore).toBeDefined()
    await restore!.trigger('click')
    const popups = wrapper.findAllComponents(ElPopconfirm)
    expect(popups).toHaveLength(2)
    await popups[0].vm.$emit('confirm', new MouseEvent('click'))
    await nextTick()

    expect(editor.draft.value?.source_overrides.logs).toEqual(override)
    expect(wrapper.text()).toContain('来源不存在，无法恢复共用配置')
    scope.stop()
  })
})
