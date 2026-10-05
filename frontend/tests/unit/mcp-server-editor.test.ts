import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MCPServerEditor from '@/modules/resources/ui/MCPServerEditor.vue'
import { resourcesApiKey } from '@/modules/resources/public'

const api = {
  create: vi.fn(),
  replace: vi.fn(),
  importMcpServers: vi.fn().mockResolvedValue([]),
}

afterEach(() => vi.clearAllMocks())

function editor() {
  return mount(MCPServerEditor, {
    global: {
      plugins: [ElementPlus],
      provide: { [resourcesApiKey as symbol]: api },
    },
  })
}

describe('MCP server JSON editor', () => {
  it('keeps the field form as the default mode', () => {
    const wrapper = editor()
    expect(wrapper.text()).toContain('服务名称')
    expect(wrapper.text()).not.toContain('MCP 配置 JSON')
    wrapper.unmount()
  })

  it('imports the named envelope and preserves a hyphenated server name', async () => {
    const wrapper = editor()
    await wrapper.get('button').trigger('click')
    await wrapper.find('textarea').setValue(
      JSON.stringify({
        servers: {
          'qqmusic-mcp': { type: 'stdio', command: 'qqmusic-mcp', args: ['stdio'] },
        },
      }),
    )
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.importMcpServers).toHaveBeenCalledWith({
      servers: {
        'qqmusic-mcp': { type: 'stdio', command: 'qqmusic-mcp', args: ['stdio'] },
      },
    })
    expect(api.create).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows a syntax error without submitting malformed JSON', async () => {
    const wrapper = editor()
    await wrapper.get('button').trigger('click')
    await wrapper.find('textarea').setValue('{"servers":')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('JSON 格式不正确')
    expect(api.importMcpServers).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('allows switching an empty envelope back to fields', async () => {
    const wrapper = editor()
    await wrapper.get('button').trigger('click')
    await wrapper.get('button').trigger('click')
    expect(wrapper.text()).toContain('服务名称')
    expect(wrapper.text()).not.toContain('MCP 配置 JSON')
    wrapper.unmount()
  })

  it('keeps automatic probing disabled by default and exposes minute interval when enabled', async () => {
    const wrapper = editor()
    expect(wrapper.text()).toContain('关闭')
    const switches = wrapper.findAllComponents({ name: 'ElSwitch' })
    expect(switches).toHaveLength(2)
    await switches[0].vm.$emit('update:modelValue', true)
    expect(wrapper.text()).toContain('探测间隔 / 分钟')
    expect(wrapper.find('input[aria-label="探测间隔 / 分钟"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
