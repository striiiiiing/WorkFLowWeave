import { computed, ref, watch } from 'vue'
import { useQuery } from '@/shared/async/useQuery'
import { useRunsApi } from '../api/dependencies'
import type { RunsApi, SessionQuery } from '../api/runsApi'
import type { SessionStatus } from '../model/types'
import { fields, type FilterField } from '../model/filters'
export const RUN_PAGE_SIZE = 20
export function useRunList(api: Pick<RunsApi, 'list'> = useRunsApi()) {
  const filterField = ref<FilterField>('workflow_name')
  const filterValue = ref('')
  const filterStatus = ref<SessionStatus | ''>('')
  const filterAfter = ref('')
  const filterBefore = ref('')
  const selectedField = computed(() => fields.find((field) => field.value === filterField.value)!)
  const filter = ref<SessionQuery>({})
  const page = ref(0)
  const { data, pending, error, refresh } = useQuery(
    (signal) =>
      api.list(
        { ...filter.value, offset: page.value * RUN_PAGE_SIZE, limit: RUN_PAGE_SIZE },
        signal,
      ),
    [page, filter],
  )
  watch(filterField, resetDraft)
  function resetDraft() {
    filterValue.value = ''
    filterStatus.value = ''
  }
  function search() {
    page.value = 0
    const fieldFilter =
      filterField.value === 'status'
        ? { status: filterStatus.value || undefined }
        : { [filterField.value]: filterValue.value.trim() || undefined }
    const nextFilter: SessionQuery = { ...fieldFilter }
    const after = toIsoDate(filterAfter.value)
    const before = toIsoDate(filterBefore.value)
    if (after) nextFilter.after = after
    if (before) nextFilter.before = before
    filter.value = nextFilter
  }
  function clearSearch() {
    resetDraft()
    filterAfter.value = ''
    filterBefore.value = ''
    page.value = 0
    filter.value = {}
  }

  function toIsoDate(value: string) {
    if (!value) return undefined
    const date = new Date(value)
    return date.toISOString()
  }
  return {
    filterField,
    filterValue,
    filterStatus,
    filterAfter,
    filterBefore,
    selectedField,
    page,
    data,
    pending,
    error,
    refresh,
    search,
    clearSearch,
  }
}
export function useRecentRuns(api: Pick<RunsApi, 'list'> = useRunsApi()) {
  return useQuery((signal) => api.list({ limit: 5 }, signal))
}
