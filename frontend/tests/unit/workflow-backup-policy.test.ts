import { effectScope, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import ElementPlus, { ElInputNumber } from 'element-plus'
import { expect, it } from 'vitest'
import BackupMatrix from '@/modules/workflows/ui/BackupMatrix.vue'
import {
  createWorkflow,
  useWorkflowEditor,
  validateBackupPolicy,
} from '@/modules/workflows/public'

it('keeps the four retention limits independent', () => {
  const policy = {
    ...createWorkflow().backup,
    checkpoint_retention_days: 2,
    collection_retention_days: 20,
    analysis_retention_days: 1,
    final_retention_days: null,
  }
  expect(validateBackupPolicy(policy)).toEqual([])
  expect(validateBackupPolicy({ ...policy, collection_retention_days: 0 })).toContain(
    '采集正文保留天数必须是大于 0 的整数或留空',
  )
})

it('keeps checkpoint retention editable when long-term backup is disabled', async () => {
  const scope = effectScope()
  const editor = scope.run(() => useWorkflowEditor({ identity: undefined }))!
  editor.updateBackup({ enabled: false, checkpoint_retention_days: 30 })
  const wrapper = mount(BackupMatrix, {
    props: { editor },
    global: { plugins: [ElementPlus] },
  })
  const limits = wrapper.findAllComponents(ElInputNumber)
  expect(limits).toHaveLength(4)
  expect(limits[0].props('disabled')).toBe(false)
  expect(limits.slice(1).every((field) => field.props('disabled'))).toBe(true)
  limits[0].vm.$emit('update:modelValue', 7)
  await nextTick()
  expect(editor.draft.value?.backup.checkpoint_retention_days).toBe(7)
  expect(wrapper.text()).not.toContain('确认分类保留设置')
  wrapper.unmount()
  scope.stop()
})
