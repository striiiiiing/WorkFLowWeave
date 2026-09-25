import { sourceName } from './resources'
import type { SourceConfig, SourceUsageView } from './types'
export type SourceFilter = 'all' | 'shared' | 'independent' | 'unused'
export function filterSources(
  sources: readonly SourceConfig[],
  search: string,
  filter: SourceFilter,
  references: (id: string) => readonly SourceUsageView[] | undefined,
) {
  const query = search.trim().toLocaleLowerCase()
  return sources.filter((source) => {
    if (
      query &&
      ![sourceName(source), source.id, source.description ?? '', source.collector]
        .join(' ')
        .toLocaleLowerCase()
        .includes(query)
    )
      return false
    if (filter === 'all') return true
    const usage = references(source.id)
    if (usage === undefined) return false
    if (filter === 'unused') return usage.length === 0
    return usage.some((item) => (filter === 'independent' ? item.detached : !item.detached))
  })
}
