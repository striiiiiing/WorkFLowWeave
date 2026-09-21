import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CredentialEditor from '@/components/resources/CredentialEditor.vue'
import ResourceEditor from '@/components/resources/ResourceEditor.vue'
import { generatedResourceId } from '@/domain/resources'
import { resourcesApi } from '@/api/resources'
import { systemApi } from '@/api/system'
import type { CapabilityDescription, ChannelConfig } from '@/types'

vi.mock('@/api/resources', () => ({
  resourcesApi: {
    create: vi.fn(),
    replace: vi.fn(),
    protectCredential: vi.fn(),
  },
}))
vi.mock('@/api/system', () => ({ systemApi: { plugins: vi.fn() } }))

const global = { plugins: [ElementPlus] }
const encrypted = {
  kind: 'encrypted' as const,
  format_version: 1,
  key_id: 'test-key',
  ciphertext: 'ciphertext',
}

function collector(name: string, idPrefix: string, optionName: string): CapabilityDescription {
  return {
    kind: 'collector',
    name,
    id_prefix: idPrefix,
    description: `${name} collector`,
    plugin: 'test',
    capabilities: ['collection'],
    options_schema: {
      type: 'object',
      properties: {
        [optionName]: { type: 'integer', description: optionName },
      },
      additionalProperties: false,
    },
    setters_schema: {
      type: 'object',
      properties: {
        order: { type: 'string', description: 'order' },
      },
      additionalProperties: false,
    },
    fields: [],
    count_unit: 'records',
  }
}

const emailCapability: CapabilityDescription = {
  kind: 'channel',
  name: 'email',
  id_prefix: 'email',
  description: 'email channel',
  plugin: 'builtin',
  capabilities: ['notification'],
  options_schema: {
    type: 'object',
    properties: {
      host: { type: 'string', description: 'SMTP 主机' },
      port: { type: 'integer', description: 'SMTP 端口' },
      sender: { type: 'string', description: '发件人' },
      recipient: { type: 'string', description: '收件人', 'x-logagent-workflow': true },
      username: { type: ['string', 'null'] },
      password: {
        type: ['object', 'null'],
        description: '认证凭据',
        'x-logagent-credential': true,
      },
    },
    required: ['host', 'port', 'sender', 'recipient'],
    allOf: [
      {
        if: { properties: { username: { type: 'string' } }, required: ['username'] },
        then: { required: ['password'], properties: { password: { type: 'object' } } },
        else: { properties: { password: { type: 'null' } } },
      },
    ],
    additionalProperties: false,
  },
  setters_schema: null,
  fields: [],
  count_unit: null,
}

afterEach(() => vi.clearAllMocks())

describe('resource IDs and capability changes', () => {
  it('generates a declared prefix but accepts an arbitrary user ID', () => {
    const prefixed = generatedResourceId('collector')
    const plain = generatedResourceId()
    expect(prefixed).toMatch(/^collector_[0-9a-f-]{36}$/)
    expect(plain).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('keeps a hand-written ID and clears old option, setter, and template drafts', async () => {
    vi.mocked(systemApi.plugins).mockResolvedValue([
      collector('first', 'first', 'limit'),
      collector('second', 'second', 'limit'),
    ])
    vi.mocked(resourcesApi.create).mockResolvedValue({} as never)
    const wrapper = mount(ResourceEditor, { props: { kind: 'sources' }, global })
    await flushPromises()

    const selects = wrapper.findAllComponents(ElSelect)
    selects[0].vm.$emit('update:modelValue', 'first')
    await flushPromises()
    await wrapper.get('[aria-label="设置 limit"]').setValue(true)
    await wrapper.get('input[aria-label="limit"]').setValue('3')
    await wrapper.get('[aria-label="设置 order"]').setValue(true)
    await wrapper.get('input[aria-label="order"]').setValue('old')
    await wrapper.get('input[placeholder="可自行填写；留空则自动生成"]').setValue('manual_source')

    selects[0].vm.$emit('update:modelValue', 'second')
    await flushPromises()
    expect(wrapper.get('input[placeholder="可自行填写；留空则自动生成"]').element).toHaveProperty(
      'value',
      'manual_source',
    )
    expect(wrapper.find('input[aria-label="limit"]').exists()).toBe(false)
    expect(wrapper.find('input[aria-label="order"]').exists()).toBe(false)

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(resourcesApi.create).toHaveBeenCalledWith(
      'sources',
      expect.objectContaining({
        id: 'manual_source',
        collector: 'second',
        options: {},
        setters: {},
        template: null,
      }),
    )
    wrapper.unmount()
  })

  it('does not clear saved fields while the initial plugin list is loading', async () => {
    let resolve!: (value: CapabilityDescription[]) => void
    vi.mocked(systemApi.plugins).mockReturnValue(
      new Promise((next) => {
        resolve = next
      }),
    )
    const initial = {
      id: 'saved_source',
      collector: 'first',
      enabled: true,
      options: { limit: 3 },
      setters: { order: 'saved' },
      template: 'saved_template',
      timeout: 60,
      on_error: 'notice' as const,
      on_missing: 'notice' as const,
      on_empty: 'notice' as const,
      on_filtered_empty: 'notice' as const,
    }
    const wrapper = mount(ResourceEditor, { props: { kind: 'sources', initial }, global })
    expect(
      (wrapper.get('input[placeholder="可自行填写；留空则自动生成"]').element as HTMLInputElement)
        .value,
    ).toBe('saved_source')
    resolve([collector('first', 'first', 'limit')])
    await flushPromises()
    expect(
      (wrapper.get('input[placeholder="可自行填写；留空则自动生成"]').element as HTMLInputElement)
        .value,
    ).toBe('saved_source')
    wrapper.unmount()
  })
})

describe('generic credential editor', () => {
  it('protects a channel credential and retries after protection failure', async () => {
    vi.mocked(systemApi.plugins).mockResolvedValue([emailCapability])
    vi.mocked(resourcesApi.protectCredential)
      .mockRejectedValueOnce(new Error('master key missing'))
      .mockResolvedValueOnce(encrypted)
    vi.mocked(resourcesApi.replace).mockResolvedValue({} as never)
    const initial: ChannelConfig = {
      id: 'mail_channel',
      channel: 'email',
      options: {
        host: 'smtp.example.test',
        port: 587,
        sender: 'sender@example.test',
        recipient: 'recipient@example.test',
        username: 'smtp-user',
        password: null,
      },
      timeout: 30,
      enabled: true,
    }
    const wrapper = mount(ResourceEditor, { props: { kind: 'channels', initial }, global })
    await flushPromises()
    const editor = wrapper.findComponent(CredentialEditor)
    editor.findComponent(ElSelect).vm.$emit('update:modelValue', 'input')
    await flushPromises()
    await editor.get('input[type="password"]').setValue('smtp-secret')

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(resourcesApi.replace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('master key missing')

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(resourcesApi.protectCredential).toHaveBeenCalledTimes(2)
    expect(resourcesApi.replace).toHaveBeenCalledWith(
      'channels',
      'mail_channel',
      expect.objectContaining({ options: expect.objectContaining({ password: encrypted }) }),
    )
    expect(wrapper.find('textarea[aria-label="插件参数 (options)"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
