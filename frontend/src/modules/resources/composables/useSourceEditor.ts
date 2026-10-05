import { computed, shallowRef, toRaw } from 'vue'
import { useQuery } from '@/shared/async/useQuery'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { createResource, generatedResourceId } from '../model/resources'
import type {
  SourceConfig,
  SourceBasicChanges,
  SourceAdvancedChanges,
  SourceConfigEditorGateway,
  SourceOverride,
  SourceSaveTarget,
} from '../model/types'

export interface SourceEditorInput {
  readonly initial?: SourceConfig
  readonly override?: SourceOverride
  readonly target: SourceSaveTarget
}
export function useSourceEditor(input: SourceEditorInput, gateway: SourceConfigEditorGateway) {
  // One editor owns one immutable identity, even if a caller replaces its props.
  const { initial, override, target: saveTarget } = input
  const draft = shallowRef<SourceConfig>()
  const save = useAsyncTask()
  let generatedId = !initial
  // Resolve is the backend-owned merge of saved and workflow-local call values.
  const load = useQuery(async (signal) => {
    const value = initial
      ? await gateway.resolve(initial.id, override, signal)
      : (createResource('sources') as SourceConfig)
    if (!signal.aborted) draft.value = structuredClone(toRaw(value))
    return value
  })
  function update(fields: Partial<SourceConfig>) {
    if (!draft.value) throw new Error('数据源尚未加载')
    draft.value = { ...draft.value, ...fields }
  }
  function updateId(id: string) {
    generatedId = false
    update({ id })
  }
  function updateCall(call: SourceConfig['call']) {
    update({ call, ...(!initial && generatedId ? { id: generatedResourceId() } : {}) })
  }
  async function submit(validate: () => Promise<boolean>) {
    return save.run(async () => {
      if (!(await validate())) throw new Error('请检查表单中的错误')
      if (!draft.value) throw new Error('数据源尚未加载')
      const value = structuredClone(toRaw(draft.value))
      value.id ||= generatedResourceId()
      const target =
        saveTarget.kind === 'shared-resource' && !initial
          ? { ...saveTarget, resourceId: value.id }
          : saveTarget
      await gateway.save(target, value)
      return value
    })
  }
  return {
    value: computed<Readonly<SourceConfig> | undefined>(() => draft.value),
    load,
    save,
    updateBasic: (fields: SourceBasicChanges) => update(fields),
    updateId,
    updateCall,
    updateOptions: (options: NonNullable<SourceConfig['options']>) => update({ options }),
    updateAdvanced: (fields: SourceAdvancedChanges) => update(fields),
    submit,
  }
}
export type SourceEditorController = ReturnType<typeof useSourceEditor>
