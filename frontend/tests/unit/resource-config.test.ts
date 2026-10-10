import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResourceEditor from './resources/ResourceEditorHarness.vue'
import { generatedResourceId } from '@/modules/resources/public'
import { resourcesApi } from '@/app/services'
import { systemApi } from '@/app/services'
import type { ChannelConfig } from '@/modules/resources/public'
import type { CapabilityDescription } from '@/modules/system/public'
import { credentialDraftSchema } from '@/modules/resources/model/credential'
import { createFieldRule } from '@/shared/schema/schemaValidation'

vi.mock('@/app/services', () => ({
  resourcesApi: {
    create: vi.fn(),
    replace: vi.fn(),
    protectCredential: vi.fn(),
    startChannelConnection: vi.fn(),
    channelConnection: vi.fn(),
    cancelChannelConnection: vi.fn(),
    get: vi.fn(),
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
      recipient: { type: 'string', description: '收件人', 'x-workflowweave-workflow': true },
      username: { type: ['string', 'null'], minLength: 1, default: null },
      password: {
        type: ['object', 'null'],
        title: '授权码',
        description: '认证凭据',
        'x-workflowweave-credential': true,
      },
    },
    required: ['host', 'port', 'sender', 'recipient'],
    allOf: [
      {
        if: { properties: { username: { type: 'string' } }, required: ['username'] },
        then: { required: ['password'], properties: { password: { type: 'object' } } },
      },
      {
        if: { properties: { password: { type: 'object' } }, required: ['password'] },
        then: { required: ['username'], properties: { username: { type: 'string' } } },
      },
    ],
    additionalProperties: false,
  },
}

const qqCapability: CapabilityDescription = {
  ...emailCapability,
  name: 'qq',
  id_prefix: 'qq',
  description: 'QQ Bot channel',
  options_schema: {
    type: 'object',
    properties: {
      app_id: { type: 'string', description: 'QQ Bot App ID' },
      client_secret: {
        anyOf: [{ type: 'object' }, { type: 'null' }],
        description: 'QQ Bot Client Secret',
        'x-workflowweave-credential': true,
      },
    },
    required: ['app_id', 'client_secret'],
    additionalProperties: false,
  },
}

afterEach(() => vi.clearAllMocks())

describe('resource IDs and capability changes', () => {
  it('generates a declared prefix but accepts an arbitrary user ID', () => {
    const prefixed = generatedResourceId('source')
    const plain = generatedResourceId()
    expect(prefixed).toMatch(/^source_[0-9a-f-]{36}$/)
    expect(plain).toMatch(/^[0-9a-f-]{36}$/)
  })
})

describe('channel credential parameters', () => {
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
    const editor = wrapper
    expect(editor.text()).toContain('授权码')
    editor
      .findAllComponents(ElSelect)
      .find((select) => select.props('ariaLabel') === 'password 类型')!
      .vm.$emit('update:modelValue', 'string')
    await flushPromises()
    const password = editor.get('input[type="password"]')
    await password.setValue('smtp-secret')
    expect(password.element.getAttribute('type')).toBe('password')
    await editor.get('.el-input__password').trigger('click')
    expect(editor.get('input[aria-label="password"]').element.getAttribute('type')).toBe('text')

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

  it('blocks a bot channel when only the App ID is configured', async () => {
    vi.mocked(systemApi.plugins).mockResolvedValue([qqCapability])
    vi.mocked(resourcesApi.create).mockResolvedValue({} as never)
    const wrapper = mount(ResourceEditor, { props: { kind: 'channels' }, global })
    await flushPromises()

    const channelSelect = wrapper.findComponent(ElSelect)
    channelSelect.vm.$emit('update:modelValue', 'qq')
    await flushPromises()
    await wrapper.get('[aria-label="设置 app_id"]').trigger('click')
    await wrapper.get('input[aria-label="app_id"]').setValue('app-123')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(resourcesApi.create).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('字符串不应少于 1 个字符')
    wrapper.unmount()
  })
})

it('shows and preserves existing credential references in JSON without substituting masks', async () => {
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
  expect((raw.element as HTMLTextAreaElement).value).toContain('ciphertext')
  expect((raw.element as HTMLTextAreaElement).value).toContain('password')
  expect((raw.element as HTMLTextAreaElement).value).not.toContain('********')
  await raw.setValue(
    JSON.stringify({
      host: 'new.example.test',
      port: 587,
      sender: 'from@example.test',
      username: 'smtp-user',
      password: encrypted,
    }),
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

it('accepts a plaintext credential in JSON mode and protects it before saving', async () => {
  vi.mocked(systemApi.plugins).mockResolvedValue([emailCapability])
  vi.mocked(resourcesApi.protectCredential).mockResolvedValue(encrypted)
  vi.mocked(resourcesApi.replace).mockResolvedValue({} as never)
  const initial: ChannelConfig = {
    id: 'json_secret_channel',
    channel: 'email',
    timeout: 30,
    enabled: true,
    options: {
      host: 'smtp.example.test',
      port: 587,
      sender: 'from@example.test',
      username: 'smtp-user',
      password: encrypted,
    },
  }
  const wrapper = mount(ResourceEditor, { props: { kind: 'channels', initial }, global })
  await flushPromises()
  await wrapper
    .findAll('button')
    .find((button) => button.text() === '编辑 JSON')!
    .trigger('click')
  const raw = wrapper.get('textarea[aria-label="插件参数 (options)"]')
  await raw.setValue(
    '{"host":"smtp.example.test","port":587,"sender":"from@example.test","username":"smtp-user","password":"new-secret"}',
  )
  await wrapper
    .findAll('button')
    .find((button) => button.text() === '填写参数')!
    .trigger('click')
  const password = wrapper.get('input[aria-label="password"]')
  expect(password.attributes('type')).toBe('password')
  expect((password.element as HTMLInputElement).value).toBe('new-secret')
  await password.setValue('edited-in-form')
  await wrapper
    .findAll('button')
    .find((button) => button.text() === '编辑 JSON')!
    .trigger('click')
  expect(
    (wrapper.get('textarea[aria-label="插件参数 (options)"]').element as HTMLTextAreaElement).value,
  ).toContain('edited-in-form')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(resourcesApi.protectCredential).toHaveBeenCalledWith('edited-in-form')
  expect(resourcesApi.replace).toHaveBeenCalledWith(
    'channels',
    'json_secret_channel',
    expect.objectContaining({ options: expect.objectContaining({ password: encrypted }) }),
  )
  wrapper.unmount()
})

it('rejects null bot secrets and preserves cross-field rules in JSON editing', async () => {
  vi.mocked(systemApi.plugins).mockResolvedValue([qqCapability])
  const initial: ChannelConfig = {
    id: 'missing-secret',
    channel: 'qq',
    options: { app_id: 'app', client_secret: null },
    timeout: 30,
    enabled: true,
  }
  const wrapper = mount(ResourceEditor, { props: { kind: 'channels', initial }, global })
  await flushPromises()
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(resourcesApi.replace).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('必填凭据')
  wrapper.unmount()

  vi.mocked(systemApi.plugins).mockResolvedValue([emailCapability])
  const mail = mount(ResourceEditor, {
    props: {
      kind: 'channels',
      initial: {
        ...initial,
        channel: 'email',
        options: {
          host: 'smtp.example.test',
          port: 587,
          sender: 'from@example.test',
          password: null,
        },
      },
    },
    global,
  })
  await flushPromises()
  await mail
    .findAll('button')
    .find((button) => button.text() === '编辑 JSON')!
    .trigger('click')
  await mail
    .get('textarea')
    .setValue(
      '{"host":"smtp.example.test","port":587,"sender":"from@example.test","password":"secret-without-username"}',
    )
  await flushPromises()
  await mail.get('form').trigger('submit')
  await flushPromises()
  expect(resourcesApi.replace).not.toHaveBeenCalled()
  expect(resourcesApi.protectCredential).not.toHaveBeenCalled()
  mail.unmount()
})

it('reports the missing SMTP username for a JSON draft with an authorization code', () => {
  const rule = createFieldRule(credentialDraftSchema(emailCapability.options_schema))
  const options = {
    host: 'smtp.example.test',
    port: 587,
    sender: 'from@example.test',
    recipient: 'to@example.test',
    password: 'smtp-secret',
  }
  expect(rule.validate(options)).toBe('请填写必填字段「username」')
  expect(rule.validate({ ...options, username: null })).toBe('username：请填写字符串。')
  expect(rule.validate({ ...options, username: 'from@example.test' })).toBe('')
})

it('requires an SMTP username for a draft password and saves after the username is supplied', async () => {
  vi.mocked(systemApi.plugins).mockResolvedValue([emailCapability])
  vi.mocked(resourcesApi.protectCredential).mockResolvedValue(encrypted)
  vi.mocked(resourcesApi.replace).mockResolvedValue({} as never)
  const wrapper = mount(ResourceEditor, {
    props: {
      kind: 'channels',
      initial: {
        id: 'smtp-pair',
        channel: 'email',
        timeout: 30,
        enabled: true,
        options: {
          host: 'smtp.example.test',
          port: 587,
          sender: 'from@example.test',
          username: null,
          password: null,
        },
      },
    },
    global,
  })
  await flushPromises()
  wrapper
    .findAllComponents(ElSelect)
    .find((select) => select.props('ariaLabel') === 'password 类型')!
    .vm.$emit('update:modelValue', 'string')
  await flushPromises()
  await wrapper.get('input[aria-label="password"]').setValue('smtp-secret')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(resourcesApi.replace).not.toHaveBeenCalled()
  expect(resourcesApi.protectCredential).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('username')
  expect(wrapper.text()).not.toContain('此字段只能为空值')

  wrapper
    .findAllComponents(ElSelect)
    .find((select) => select.props('ariaLabel') === 'username 类型')!
    .vm.$emit('update:modelValue', 'string')
  await flushPromises()
  await wrapper.get('input[aria-label="username"]').setValue('from@example.test')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(resourcesApi.protectCredential).toHaveBeenCalledWith('smtp-secret')
  expect(resourcesApi.replace).toHaveBeenCalledWith(
    'channels',
    'smtp-pair',
    expect.objectContaining({
      options: expect.objectContaining({
        username: 'from@example.test',
        password: encrypted,
      }),
    }),
  )
  wrapper.unmount()
})
