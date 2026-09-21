<script setup lang="ts">
import type { ParameterInput, ValueDraft, ValueType } from '@/domain/parameters'

const props = defineProps<{ modelValue: ValueDraft; field: ParameterInput; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: ValueDraft] }>()
function update(value: ValueDraft) {
  emit('update:modelValue', value)
}
function setType(type: ValueType) {
  update(props.field.setType(props.modelValue, type))
}
</script>

<template>
  <div class="min-w-0 w-full">
    <el-button
      v-if="field.types.length === 1 && modelValue.type !== field.types[0]"
      size="small"
      class="mb-2"
      @click="setType(field.types[0])"
    >
      按声明类型重新填写
    </el-button>
    <el-select
      v-if="field.types.length > 1 && !field.choices"
      :model-value="modelValue.type"
      :aria-label="`${label} 类型`"
      class="mb-2"
      @update:model-value="setType"
    >
      <el-option
        v-for="type in field.typeOptions"
        :key="type.value"
        :value="type.value"
        :label="type.label"
      />
    </el-select>
    <el-select
      v-if="field.choices"
      :model-value="field.selected(modelValue)"
      :aria-label="label"
      @update:model-value="update(field.select(modelValue, $event))"
    >
      <el-option
        v-for="choice in field.choices"
        :key="choice.value"
        :value="choice.value"
        :label="choice.label"
      />
    </el-select>
    <section v-else-if="modelValue.type === 'array'" :aria-label="`${label} 列表`">
      <p class="muted text-sm mb-2">
        {{
          !field.repeatable
            ? '逐项添加，可调整顺序，不允许重复。'
            : '逐项添加，可重复选择并调整顺序。'
        }}
      </p>
      <p v-if="!modelValue.items.length" class="muted text-sm mb-2">暂无项目</p>
      <div
        v-for="(item, index) in modelValue.items"
        :key="item.id"
        class="border rounded p-3 mb-2 min-w-0"
      >
        <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
          <span>{{ field.item(index).label(`第 ${index + 1} 项`) }}</span>
          <div class="flex flex-wrap gap-1">
            <el-button
              size="small"
              :aria-label="`上移 ${label} 第 ${index + 1} 项`"
              :disabled="index === 0"
              @click="update(field.move(modelValue, index, -1))"
            >
              上移
            </el-button>
            <el-button
              size="small"
              :aria-label="`下移 ${label} 第 ${index + 1} 项`"
              :disabled="index === modelValue.items.length - 1"
              @click="update(field.move(modelValue, index, 1))"
            >
              下移
            </el-button>
            <el-button
              v-if="field.repeatable"
              size="small"
              :aria-label="`重复添加 ${label} 第 ${index + 1} 项`"
              :disabled="field.atLimit(modelValue) || !!field.item(index).error(item)"
              @click="update(field.duplicate(modelValue, index))"
            >
              重复添加
            </el-button>
            <el-button
              size="small"
              :aria-label="`删除 ${label} 第 ${index + 1} 项`"
              @click="update(field.remove(modelValue, index))"
            >
              删除
            </el-button>
          </div>
        </div>
        <ParameterValue
          :model-value="item"
          :field="field.item(index)"
          :label="`${label} 第 ${index + 1} 项`"
          @update:model-value="update(field.replace(modelValue, index, $event))"
        />
      </div>
      <el-button
        :aria-label="`添加 ${label} 项目`"
        :disabled="!field.canAdd(modelValue)"
        @click="update(field.add(modelValue))"
      >
        添加项目
      </el-button>
    </section>
    <el-switch
      v-else-if="modelValue.type === 'boolean'"
      :model-value="modelValue.boolean"
      :aria-label="label"
      @update:model-value="update({ ...modelValue, boolean: $event === true })"
    />
    <span v-else-if="modelValue.type === 'null'">null</span>
    <el-input
      v-else
      :model-value="modelValue.text"
      :type="modelValue.type === 'object' ? 'textarea' : 'text'"
      :placeholder="
        field.schema.format === 'date'
          ? 'YYYY-MM-DD'
          : field.schema.format === 'uri' || field.schema.format === 'url'
            ? 'https://…'
            : modelValue.type === 'object'
              ? '仅此字段的 JSON 值'
              : ''
      "
      :rows="3"
      :aria-label="label"
      @update:model-value="update({ ...modelValue, text: $event })"
    />
  </div>
</template>
