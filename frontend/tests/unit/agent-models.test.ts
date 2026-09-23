import { afterEach, expect, it } from 'vitest'
import {
  groupAgentModels,
  readDefaultAgentModel,
  saveDefaultAgentModel,
} from '@/domain/agentModels'

afterEach(() => localStorage.clear())
it('persists only the selected channel reference and explicitly clears the default', () => {
  saveDefaultAgentModel('backup:shared')
  expect(readDefaultAgentModel()).toBe('backup:shared')
  saveDefaultAgentModel('')
  expect(readDefaultAgentModel()).toBe('')
})
it('sorts by channel then model without merging identical model names across channels', () => {
  const models = [
    { reference: 'b:shared', ai: 'b', model: 'shared', provider: 'provider' },
    { reference: 'a:z', ai: 'a', model: 'z', provider: 'provider' },
    { reference: 'a:shared', ai: 'a', model: 'shared', provider: 'provider' },
  ]
  expect(
    groupAgentModels(models).map((group) => [
      group.channel,
      group.models.map((item) => item.reference),
    ]),
  ).toEqual([
    ['a', ['a:shared', 'a:z']],
    ['b', ['b:shared']],
  ])
  expect(models[0].reference).toBe('b:shared')
})
