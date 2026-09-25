import { mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import AgentComposer from '@/modules/agents/ui/AgentComposer.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))
function setup(draft = '') {
  const wrapper = mount(AgentComposer, {
    props: {
      draft,
      running: false,
      commands: [
        { key: '/append', label: '追加', description: '排队', icon: 'enter', action: vi.fn() },
      ],
      'onUpdate:draft': (value: string) => {
        void wrapper.setProps({ draft: value })
      },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}
it('sends command arguments and unknown commands instead of trapping Enter in an empty menu', async () => {
  const wrapper = setup()
  await wrapper.setProps({ draft: '/append extra', running: true })
  await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('send')).toHaveLength(1)
  await wrapper.setProps({ draft: '/unknown' })
  await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('send')).toHaveLength(2)
})
it('supports queue submissions while running, IME composition, pending and disabled states', async () => {
  const wrapper = setup('补充说明')
  await wrapper.setProps({ running: true })
  await wrapper.get('textarea').trigger('keydown', { key: 'Enter', isComposing: true })
  expect(wrapper.emitted('send')).toBeUndefined()
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('send')).toHaveLength(1)
  await wrapper.setProps({ pending: true })
  await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('send')).toHaveLength(1)
  await wrapper.get('textarea').trigger('keydown', { key: 'Escape' })
  expect(wrapper.emitted('stop')).toHaveLength(1)
  await wrapper.setProps({ pending: false, disabled: true })
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('send')).toHaveLength(1)
})
it('clears the selected command before the parent inserts its argument prefix', async () => {
  const wrapper = setup()
  await wrapper.setProps({ draft: '/app' })
  await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('update:draft')?.[0]).toEqual([''])
  expect(wrapper.emitted('executeCommand')?.[0][0]).toMatchObject({ key: '/append' })
  expect(wrapper.emitted('send')).toBeUndefined()
})
it('blocks an uncertain session-creation retry when the API has no request deduplication', async () => {
  const wrapper = setup('/workflow run-1')
  await wrapper.setProps({ sendUncertain: true, sendRetrySafe: false })
  expect(wrapper.text()).toContain('请先检查会话列表')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('send')).toBeUndefined()
})
