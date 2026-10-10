import { defineComponent, h, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SourceFileFields from '@/modules/resources/ui/SourceFileFields.vue'
import { referenceFilename } from '@/modules/resources/model/source/file'
import { resourcesApiKey } from '@/modules/resources/api/dependencies'
import { createResourcesApi } from '@/modules/resources/api/resourcesApi'
import type { FileCall } from '@/modules/resources/model/public'

afterEach(() => vi.unstubAllEnvs())

function setup(existing = false) {
  const call = ref<FileCall>({ kind: 'file', file_type: 'text', path: 'notes/example.txt' })
  const api = {
    createTextReference: vi
      .fn()
      .mockImplementation(async (path: string) => ({ ...call.value, path })),
    importTextReference: vi
      .fn()
      .mockImplementation(async (path: string) => ({ ...call.value, path })),
  }
  const wrapper = mount(
    defineComponent({
      setup: () => () =>
        h(SourceFileFields, {
          call: call.value,
          existing,
          onChange: (next: FileCall) => {
            call.value = next
          },
        }),
    }),
    { global: { plugins: [ElementPlus], provide: { [resourcesApiKey as symbol]: api } } },
  )
  const fields = wrapper.getComponent(SourceFileFields)
  const selectText = async () => {
    fields.getComponent(ElSelect).vm.$emit('update:modelValue', 'text')
    await flushPromises()
  }
  return { wrapper, fields, call, api, selectText }
}

describe('file reference form', () => {
  it('defaults to import, requires explicit type, and preserves paths when toggling', async () => {
    const { wrapper, fields, call, selectText } = setup()
    expect(fields.find('input[type="file"]').exists()).toBe(true)
    expect(fields.find('textarea').exists()).toBe(false)
    await expect(fields.vm.prepare()).rejects.toThrow('请选择文件类型')
    await selectText()
    await fields.get('input[aria-label="相对保存位置"]').setValue('team/custom.md')
    await fields.get('input[type="checkbox"]').setValue(true)
    expect(call.value.path).toBe('team/custom.md')
    expect(fields.find('textarea').exists()).toBe(true)
    await fields.get('input[type="checkbox"]').setValue(false)
    expect(call.value.path).toBe('team/custom.md')
    expect(await fields.vm.prepare()).toEqual(call.value)
    wrapper.unmount()
  })

  it('creates online text once when only source saving is retried', async () => {
    const { wrapper, fields, api, selectText } = setup()
    await selectText()
    await fields.get('input[type="checkbox"]').setValue(true)
    await fields.get('textarea').setValue('  正文\n\n尾部  ')
    await fields.vm.prepare()
    await fields.vm.prepare()
    expect(api.createTextReference).toHaveBeenCalledTimes(1)
    expect(api.createTextReference).toHaveBeenCalledWith('notes/example.txt', '  正文\n\n尾部  ')
    expect(api.importTextReference).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('retries a failed creation and supports intentionally empty text', async () => {
    const { wrapper, fields, api, selectText } = setup()
    await selectText()
    await fields.get('input[type="checkbox"]').setValue(true)
    api.createTextReference.mockRejectedValueOnce(new Error('磁盘不可写'))
    await expect(fields.vm.prepare()).rejects.toThrow('磁盘不可写')
    await fields.vm.prepare()
    expect(api.createTextReference).toHaveBeenCalledTimes(2)
    expect(api.createTextReference).toHaveBeenLastCalledWith('notes/example.txt', '')
    wrapper.unmount()
  })

  it('uploads original File objects without decoding and retains successful import for retry', async () => {
    const { wrapper, fields, api, selectText } = setup()
    await selectText()
    const file = new File([new Uint8Array([255, 13, 10])], 'test.txt')
    const input = fields.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await fields.vm.prepare()
    await fields.vm.prepare()
    expect(api.importTextReference).toHaveBeenCalledTimes(1)
    expect(api.importTextReference).toHaveBeenCalledWith('notes/example.txt', file)
    wrapper.unmount()
  })

  it('edits existing references without loading or recreating their text', async () => {
    const { wrapper, fields, call, api } = setup(true)
    expect(await fields.vm.prepare()).toEqual(call.value)
    expect(api.createTextReference).not.toHaveBeenCalled()
    expect(api.importTextReference).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('browser-local reference names', () => {
  it.each([
    ['Asia/Shanghai', '2026-10-10T06:30:05Z', '2026-10-10_14-30-05_UTC+08-00'],
    ['America/New_York', '2026-01-10T19:30:05Z', '2026-01-10_14-30-05_UTC-05-00'],
    ['America/New_York', '2026-07-10T18:30:05Z', '2026-07-10_14-30-05_UTC-04-00'],
    ['Asia/Kathmandu', '2026-10-10T08:45:05Z', '2026-10-10_14-30-05_UTC+05-45'],
  ])('includes seconds and the offset at that instant in %s', (timezone, instant, expected) => {
    vi.stubEnv('TZ', timezone)
    expect(referenceFilename(new Date(instant), 'a1b2c3d4-1234-4000-8000-123456789012')).toBe(
      `${expected}_a1b2c3d4.txt`,
    )
  })

  it('uses distinct random suffixes within one second', () => {
    const now = new Date()
    expect(referenceFilename(now)).not.toBe(referenceFilename(now))
    expect(referenceFilename(now)).not.toMatch(/[:/]/)
  })
})

it('sends file bytes and explicit type through the API transport', async () => {
  const request = vi.fn().mockResolvedValue({})
  const api = createResourcesApi({ request })
  const file = new File(['正文\r\n'], 'note.txt')
  await api.importTextReference('notes/import.txt', file)
  expect(request).toHaveBeenLastCalledWith({
    url: '/collection/files/import',
    method: 'POST',
    params: { path: 'notes/import.txt', file_type: 'text' },
    headers: { 'Content-Type': 'application/octet-stream' },
    data: file,
  })
  await api.createTextReference('notes/online.txt', '正文')
  expect(request).toHaveBeenLastCalledWith({
    url: '/collection/files/text',
    method: 'POST',
    data: { path: 'notes/online.txt', file_type: 'text', text: '正文' },
  })
})
