import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CredentialEditor from '@/modules/resources/ui/CredentialEditor.vue'
import ResourceEditor from './resources/ResourceEditorHarness.vue'
import { generatedResourceId } from '@/modules/resources/public'
import { resourcesApi } from '@/app/services'
import { systemApi } from '@/app/services'
import type { ChannelConfig } from '@/modules/resources/public'
import type { CapabilityDescription } from '@/modules/system/public'

vi.mock('@/app/services', () => ({
  resourcesApi: {
    create: vi.fn(),
    replace: vi.fn(),
    protectCredential: vi.fn(),
  },
  systemApi: { plugins: vi.fn() },
}))

const global = { plugins: [ElementPlus] }
const encrypted = {
  kind: 'encrypted' as const,
  format_version: 1,
  key_id: 'test-key',
  ciphertext: 'ciphertext',
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

it('hides encrypted channel values in JSON while preserving their root-schema validation and save value', async () => {
  vi.mocked(systemApi.plugins).mockResolvedValue([emailCapability])
  const initial: ChannelConfig = {
    id: 'protected_channel',
    channel: 'email',
    timeout: 30,
    enabled: false,
    options: {
      host: 'smtp.example.test',
      port: 587,
      sender: 'from@example.test',
      username: 'smtp-user',
      password: encrypted,
    },
  }
  vi.mocked(resourcesApi.replace).mockResolvedValue(initial)
  const wrapper = mount(ResourceEditor, { props: { kind: 'channels', initial }, global })
  await flushPromises()
  await wrapper
    .findAll('button')
    .find((button) => button.text() === '编辑 JSON')!
    .trigger('click')
  const raw = wrapper.get('textarea[aria-label="插件参数 (options)"]')
  expect((raw.element as HTMLTextAreaElement).value).not.toContain('ciphertext')
  expect((raw.element as HTMLTextAreaElement).value).not.toContain('password')
  await raw.setValue(
    '{"host":"new.example.test","port":587,"sender":"from@example.test","username":"smtp-user"}',
  )
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(resourcesApi.replace).toHaveBeenCalledWith(
    'channels',
    'protected_channel',
    expect.objectContaining({
      options: expect.objectContaining({ host: 'new.example.test', password: encrypted }),
    }),
  )
  expect(resourcesApi.protectCredential).not.toHaveBeenCalled()
  wrapper.unmount()
})
