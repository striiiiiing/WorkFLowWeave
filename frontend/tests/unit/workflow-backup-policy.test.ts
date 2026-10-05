import { effectScope, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import ElementPlus, { ElInputNumber } from 'element-plus'
import { expect, it } from 'vitest'
import BackupMatrix from '@/modules/workflows/ui/BackupMatrix.vue'
import {
  classifyLegacyRetention,
  createWorkflow,
  hasLegacyRetention,
  useWorkflowEditor,
  validateBackupPolicy,
} from '@/modules/workflows/public'

it('requires an explicit choice for old retention and keeps the four limits independent', () => {
  const policy = { ...createWorkflow().backup, retention_days: 30 }
  expect(validateBackupPolicy(policy)).toContain('旧保留天数需要重新选择分类保留策略')
  const classified = classifyLegacyRetention({
    ...policy,
    checkpoint_retention_days: 2,
    collection_retention_days: 20,
    analysis_retention_days: 1,
    final_retention_days: null,
  })
  expect(hasLegacyRetention(classified)).toBe(false)
  expect(classified).toMatchObject({
    checkpoint_retention_days: 2,
    collection_retention_days: 20,
    analysis_retention_days: 1,
    final_retention_days: null,
  })
  expect(validateBackupPolicy(classified)).toEqual([])
  expect(validateBackupPolicy({ ...classified, collection_retention_days: 0 })).toContain(
    '采集正文保留天数必须是大于 0 的整数或留空',
  )
})

it('keeps checkpoint retention editable when long-term backup is disabled', async () => {
  const scope = effectScope()
  const editor = scope.run(() => useWorkflowEditor({ identity: undefined }))!
  editor.updateBackup({ enabled: false, retention_days: 30 })
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
  expect(wrapper.text()).toContain('确认分类保留设置')
  await wrapper.get('button.el-button').trigger('click')
  expect(hasLegacyRetention(editor.draft.value!.backup)).toBe(false)
  wrapper.unmount()
  scope.stop()
})
