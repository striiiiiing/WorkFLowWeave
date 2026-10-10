import { effectScope, ref } from 'vue'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus, { ElSelect } from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { resourcesApiKey } from '@/modules/resources/api/dependencies'
import { createResourcesApi, type ResourcesApi } from '@/modules/resources/api/resourcesApi'
import { useChannelConversation } from '@/modules/resources/composables/useChannelConversation'
import ChannelConversation from '@/modules/resources/ui/ChannelConversation.vue'
import ChannelEditor from '@/modules/resources/ui/ChannelEditor.vue'
import type { SchemaCapability } from '@/shared/schema/types'

function bindingApi() {
  return {
    channelConversation: vi.fn().mockResolvedValue({ session_id: 'session-a' }),
    conversationOptions: vi.fn().mockResolvedValue([
      { session_id: 'session-a', title: 'A', status: 'created' },
      { session_id: 'session-b', title: 'B', status: 'created' },
    ]),
    bindChannelConversation: vi.fn().mockImplementation(async (_id, sessionId) => ({
      session_id: sessionId,
    })),
  }
}

describe('channel instance conversation binding', () => {
  it('updates the binding through its own API without modifying resource configuration', async () => {
    const request = vi.fn().mockResolvedValue({ session_id: 'session' })
    const api = createResourcesApi({ request })
    await api.channelConversation('instance / one')
    await api.bindChannelConversation('instance / one', null)
    expect(request.mock.calls.map(([call]) => call.url)).toEqual([
      '/channels/instance%20%2F%20one/conversation',
      '/channels/instance%20%2F%20one/conversation',
    ])
    expect(request.mock.lastCall?.[0]).toMatchObject({ method: 'PUT', data: { session_id: null } })
  })

  it('keeps the server binding visible after a failed save', async () => {
    const api = bindingApi()
    const scope = effectScope()
    const state = scope.run(() => useChannelConversation(() => 'instance', api))!
    await flushPromises()
    state.selected.value = 'session-b'
    api.bindChannelConversation.mockRejectedValue(new Error('disk full'))
    expect((await state.save()).status).toBe('error')
    expect(state.binding.value?.session_id).toBe('session-a')
    expect(state.action.error.value).toContain('disk full')
    scope.stop()
  })

  it('does not apply a pending save result to a different instance', async () => {
    const api = bindingApi()
    const id = ref('instance-a')
    let resolve!: (result: { session_id: string }) => void
    api.bindChannelConversation.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done
        }),
    )
    const scope = effectScope()
    const state = scope.run(() => useChannelConversation(() => id.value, api))!
    await flushPromises()
    const saving = state.save('session-b')
    api.channelConversation.mockResolvedValue({ session_id: 'other-session' })
    id.value = 'instance-b'
    await flushPromises()
    resolve({ session_id: 'session-b' })
    await saving
    expect(state.binding.value?.session_id).toBe('other-session')
    scope.stop()
  })

  it('allows binding, opening the same Web session, and unbinding', async () => {
    const api = bindingApi()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/agents/:sessionId', component: { template: '<div />' } },
      ],
    })
    const wrapper = mount(ChannelConversation, {
      props: { channelId: 'instance' },
      global: { plugins: [ElementPlus, router], provide: { [resourcesApiKey as symbol]: api } },
    })
    await flushPromises()
    expect(wrapper.find('a').attributes('href')).toBe('/agents/session-a')
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 'session-b')
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '保存绑定')!
      .trigger('click')
    await flushPromises()
    expect(api.bindChannelConversation).toHaveBeenCalledWith('instance', 'session-b')
    expect(wrapper.find('a').attributes('href')).toBe('/agents/session-b')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '解绑')!
      .trigger('click')
    await flushPromises()
    expect(api.bindChannelConversation).toHaveBeenLastCalledWith('instance', null)
    expect(wrapper.text()).toContain('未绑定')
    expect(wrapper.find('a').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows the entry only on existing duplex instances', () => {
    const api = {
      ...bindingApi(),
      protectCredential: vi.fn(),
      channelConnection: vi.fn().mockResolvedValue({
        channel_id: 'instance',
        state: 'idle',
        message: '尚未开始连接',
        error: null,
        target_options: {},
      }),
      startChannelConnection: vi.fn(),
      cancelChannelConnection: vi.fn(),
      get: vi.fn(),
    } as unknown as ResourcesApi
    const capability = {
      name: 'telegram',
      kind: 'channel',
      plugin: 'telegram',
      description: '',
      capabilities: ['notification', 'conversation'],
      options_schema: {},
    } as SchemaCapability
    const options = {
      props: {
        initial: {
          id: 'instance',
          channel: 'telegram',
          options: {},
          timeout: 30,
          enabled: true,
          agent_enabled: true,
        },
        capabilities: [capability],
      },
      global: {
        plugins: [ElementPlus],
        provide: { [resourcesApiKey as symbol]: api },
        renderStubDefaultSlot: true,
      },
    }
    const duplex = shallowMount(ChannelEditor, options)
    expect(duplex.findComponent(ChannelConversation).exists()).toBe(true)
    duplex.unmount()
    const simplex = shallowMount(ChannelEditor, {
      ...options,
      props: {
        ...options.props,
        capabilities: [{ ...capability, capabilities: ['notification'] }],
      },
    })
    expect(simplex.findComponent(ChannelConversation).exists()).toBe(false)
    simplex.unmount()
  })
})
