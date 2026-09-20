import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, it, expect, vi } from 'vitest'
import ResourcesView from '@/views/ResourcesView.vue'
import { resourcesApi } from '@/api/resources'

vi.mock('@/api/resources', () => ({
  resourcesApi: {
    list: vi.fn().mockResolvedValue([{ id: 'provider', provider: 'http', models: {} }]),
    checkAIConnection: vi.fn().mockRejectedValue(new Error('上游 HTTP 405')),
  },
}))

describe('resource category actions', () => {
  it('names the action by category and only checks connection explicitly', async () => {
    vi.mocked(resourcesApi.list).mockResolvedValue([
      { id: 'provider', provider: 'http', models: {} },
    ] as never)
    vi.mocked(resourcesApi.checkAIConnection).mockRejectedValue(new Error('上游 HTTP 405'))
    const wrapper = mount(ResourcesView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('添加数据源')
    await wrapper.get('#tab-ai').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('添加供应商渠道')
    expect(resourcesApi.checkAIConnection).not.toHaveBeenCalled()
    await vi.waitFor(() => expect(wrapper.text()).toContain('检查连接'))
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '检查连接')!
      .trigger('click')
    await flushPromises()
    expect(resourcesApi.checkAIConnection).toHaveBeenCalledWith('provider')
    expect(wrapper.text()).toContain('上游 HTTP 405')
    expect(wrapper.text()).toContain('provider')
    expect(
      wrapper
        .findAll('button')
        .find((b) => b.text() === '添加供应商渠道')!
        .attributes('disabled'),
    ).toBeUndefined()
    await wrapper.get('#tab-channels').trigger('click')
    expect(wrapper.text()).toContain('添加通知渠道')
    await wrapper.get('#tab-setters').trigger('click')
    expect(wrapper.text()).toContain('添加处理模板')
    wrapper.unmount()
  })
})
