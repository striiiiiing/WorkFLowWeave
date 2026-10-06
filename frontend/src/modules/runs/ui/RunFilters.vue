<script setup lang="ts">
import { computed } from 'vue'
import { fields, type FilterField } from '@/modules/workflows/model/public'
import { sessionStates } from '@/modules/workflows/model/public'
import type { SessionStatus } from '@/modules/workflows/model/public'
const filterField = defineModel<FilterField>('field', { required: true })
const filterValue = defineModel<string>('value', { required: true })
const filterStatus = defineModel<SessionStatus | ''>('status', { required: true })
const filterAfter = defineModel<string>('after', { required: true })
const filterBefore = defineModel<string>('before', { required: true })
const selectedField = computed(() => fields.find((field) => field.value === filterField.value)!)
const emit = defineEmits<{ search: []; reset: [] }>()
</script>
<template>
  <form
    class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mb-5"
    @submit.prevent="emit('search')"
  >
    <el-select v-model="filterField" aria-label="筛选字段" class="w-full">
      <el-option
        v-for="field in fields"
        :key="field.value"
        :label="field.label"
        :value="field.value"
      />
    </el-select>
    <el-select
      v-if="filterField === 'status'"
      v-model="filterStatus"
      aria-label="运行状态"
      placeholder="选择状态"
      clearable
      class="min-w-0"
    >
      <el-option
        v-for="(state, value) in sessionStates"
        :key="value"
        :label="state.label"
        :value="value"
      />
    </el-select>
    <el-input
      v-else
      v-model="filterValue"
      :aria-label="selectedField.label"
      :placeholder="selectedField.placeholder"
      clearable
    />
    <label class="flex items-center gap-2 min-w-0">
      <span class="muted whitespace-nowrap">开始时间</span>
      <input
        v-model="filterAfter"
        type="datetime-local"
        aria-label="开始时间"
        class="el-input__wrapper w-full min-w-0"
      />
    </label>
    <label class="flex items-center gap-2 min-w-0">
      <span class="muted whitespace-nowrap">结束时间</span>
      <input
        v-model="filterBefore"
        type="datetime-local"
        aria-label="结束时间"
        class="el-input__wrapper w-full min-w-0"
      />
    </label>
    <div class="flex shrink-0">
      <el-button native-type="submit" type="primary">筛选</el-button>
      <el-button @click="emit('reset')">重置</el-button>
    </div>
  </form>
</template>
