import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentSlashMenu, { type SlashCommand } from '@/components/agent/AgentSlashMenu.vue'
import { transcriptRows } from '@/components/agent/transcript'
import type { AgentEvent } from '@/api/agents'

describe('AgentSlashMenu', () => {
  const dummyCommands: SlashCommand[] = [
    {
      key: '/fork',
      label: '创建分支',
      description: '派生新分支',
      icon: 'fork',
      action: () => {},
    },
    {
      key: '/compact',
      label: '压缩上下文',
      description: '压缩消息历史',
      icon: 'zap',
      action: () => {},
    },
    {
      key: '/stop',
      label: '暂停/停止',
      description: '中断执行',
      icon: 'pause',
      action: () => {},
    },
  ]

  it('renders commands when visible and filters by query', async () => {
    const wrapper = mount(AgentSlashMenu, {
      props: {
        visible: true,
        query: '/co',
        commands: dummyCommands,
      },
    })

    expect(wrapper.find('.slash-palette').exists()).toBe(true)
    const items = wrapper.findAll('.palette-item')
    expect(items.length).toBe(1)
    expect(items[0].text()).toContain('/compact')
  })

  it('does not render when visible is false', () => {
    const wrapper = mount(AgentSlashMenu, {
      props: {
        visible: false,
        query: '',
        commands: dummyCommands,
      },
    })

    expect(wrapper.find('.slash-palette').exists()).toBe(false)
  })

  it('emits select event when an item is clicked', async () => {
    const wrapper = mount(AgentSlashMenu, {
      props: {
        visible: true,
        query: '',
        commands: dummyCommands,
      },
    })

    const items = wrapper.findAll('.palette-item')
    await items[0].trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0][0]).toEqual(dummyCommands[0])
  })
})

describe('transcriptRows for Agent events', () => {
  it('correctly maps user, assistant, and context compacted events', () => {
    const events: AgentEvent[] = [
      {
        id: 1,
        session_id: 's1',
        turn_id: 't1',
        type: 'message.user',
        at: '2026-09-23T10:00:00Z',
        data: { text: 'Hello Agent' },
      },
      {
        id: 2,
        session_id: 's1',
        turn_id: 't1',
        type: 'message.completed',
        at: '2026-09-23T10:00:05Z',
        data: { text: 'Hello User' },
      },
      {
        id: 3,
        session_id: 's1',
        turn_id: 't1',
        type: 'context.compacted',
        at: '2026-09-23T10:00:10Z',
        data: { summary: 'Context compacted summary' },
      },
    ]

    const rows = transcriptRows(events)
    expect(rows.length).toBe(3)
    expect(rows[0].role).toBe('user')
    expect(rows[0].text).toBe('Hello Agent')
    expect(rows[1].role).toBe('assistant')
    expect(rows[1].text).toBe('Hello User')
    expect(rows[2].role).toBe('summary')
    expect(rows[2].text).toBe('Context compacted summary')
  })
})
