<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
const props = defineProps<{ text: string }>()
// Plugin and AI text is untrusted. MarkdownIt escapes HTML and rejects unsafe link protocols.
const markdown = new MarkdownIt({ html: false, linkify: false, breaks: true })
const content = computed(() => markdown.render(props.text))
</script>
<template><div class="report-prose" v-html="content" /></template>
<style scoped>
.report-prose {
  line-height: 1.8;
  overflow-wrap: anywhere;
}
.report-prose :deep(p),
.report-prose :deep(ul),
.report-prose :deep(ol) {
  margin: 0.6em 0;
}
.report-prose :deep(h1),
.report-prose :deep(h2),
.report-prose :deep(h3) {
  font-weight: 700;
  margin: 1em 0 0.5em;
}
.report-prose :deep(h1) {
  font-size: 1.4em;
}
.report-prose :deep(h2) {
  font-size: 1.2em;
}
.report-prose :deep(ul) {
  list-style: disc;
  padding-left: 1.5em;
}
.report-prose :deep(ol) {
  list-style: decimal;
  padding-left: 1.5em;
}
.report-prose :deep(a) {
  color: #2563eb;
  text-decoration: underline;
}
.report-prose :deep(pre) {
  white-space: pre-wrap;
  background: #f1f5f9;
  padding: 1em;
  border-radius: 0.5em;
}
.report-prose :deep(code) {
  background: #f1f5f9;
  color: #0f172a;
  padding: 0.1em 0.3em;
  border-radius: 0.25em;
}
.report-prose :deep(blockquote) {
  border-left: 3px solid #cbd5e1;
  padding-left: 1em;
  color: #475569;
}
.report-prose :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
}
.report-prose :deep(th),
.report-prose :deep(td) {
  border: 1px solid #cbd5e1;
  padding: 0.4em 0.7em;
}
:global(.dark) .report-prose :deep(pre) {
  background: #0f172a;
  color: #e2e8f0;
}
:global(.dark) .report-prose :deep(code) {
  background: #0f172a;
  color: #e2e8f0;
}
:global(.dark) .report-prose :deep(blockquote) {
  color: #cbd5e1;
}
:global(.dark) .report-prose :deep(th),
:global(.dark) .report-prose :deep(td) {
  border-color: #475569;
}
</style>
