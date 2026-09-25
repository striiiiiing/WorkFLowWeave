<script setup lang="ts">
import type { ReportSection } from '../model/types'
import ReportText from '@/shared/ui/ReportText.vue'
defineProps<{ sections: ReportSection[] }>()
</script>
<template>
  <section v-for="(section, index) in sections" :key="index" class="mt-4">
    <h4 class="font-semibold mb-2">{{ section.title }}</h4>
    <ReportText v-if="section.kind === 'text'" :text="section.text" />
    <dl v-else-if="section.kind === 'metrics'" class="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div
        v-for="(item, position) in section.items"
        :key="position"
        class="rounded-lg bg-slate-50 dark:bg-slate-800 p-3"
      >
        <dt class="muted text-sm">{{ item.label }}</dt>
        <dd class="text-lg font-semibold break-words">
          {{ item.value }}
          <span class="text-sm font-normal">{{ item.unit }}</span>
        </dd>
      </div>
    </dl>
    <div v-else class="overflow-x-auto" tabindex="0" :aria-label="section.title">
      <table class="w-full text-sm border-collapse">
        <caption class="sr-only">{{ section.title }}</caption>
        <thead>
          <tr>
            <th
              v-for="(column, col) in section.columns"
              :key="col"
              scope="col"
              class="border-b p-2 text-left"
            >
              {{ column }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, position) in section.rows" :key="position">
            <td v-for="(cell, col) in row" :key="col" class="border-b p-2">
              {{ cell === null ? '—' : cell === true ? '是' : cell === false ? '否' : cell }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
