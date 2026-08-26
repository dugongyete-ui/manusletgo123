<template>
  <div class="step-timeline flex flex-col w-full">
    <div v-for="(entry, i) in stepEntries" :key="entry.step.id || i" class="relative flex flex-col"
      :class="i < stepEntries.length - 1 ? 'pb-[12px]' : ''">
      <!-- Continuous timeline rail: connects every step icon into ONE line.
           Each step owns the segment from its icon down to the next step. -->
      <div class="absolute left-[7px] top-[16px] bottom-0 border-l border-dashed border-[var(--border-dark)]"
        :class="i === stepEntries.length - 1 && !entry.items.length ? 'hidden' : ''"></div>

      <!-- Step header: status node + description + chevron -->
      <div
        class="text-sm w-full clickable flex gap-2 justify-between group/header truncate text-[var(--text-primary)]">
        <div class="flex flex-row gap-2 justify-center items-center truncate" @click="toggle(i)">
          <!-- status node -->
          <div v-if="entry.step.status === 'completed'"
            class="w-4 h-4 flex-shrink-0 flex items-center justify-center border-[var(--border-dark)] rounded-[15px] bg-[var(--text-disable)] dark:bg-[var(--fill-tsp-white-dark)] border-0">
            <CheckIcon class="text-[var(--icon-white)] dark:text-[var(--icon-white-tsp)]" :size="10" />
          </div>
          <div v-else-if="entry.step.status === 'failed'"
            class="w-4 h-4 flex-shrink-0 flex items-center justify-center rounded-[15px] border-0"
            style="background:#d92d20;">
            <XIcon class="text-white" :size="10" />
          </div>
          <div v-else
            class="w-4 h-4 flex-shrink-0 flex items-center justify-center border border-[var(--border-dark)] rounded-[15px]">
            <span v-if="entry.step.status === 'running'"
              class="block w-[6px] h-[6px] rounded-full bg-[var(--text-secondary)] animate-pulse"></span>
          </div>
          <div class="truncate font-medium markdown-content"
            v-html="renderMarkdown(entry.step.description || '')">
          </div>
          <span class="flex-shrink-0 flex" @click.stop="toggle(i)">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              class="lucide lucide-chevron-down transition-transform duration-300 w-4 h-4"
              :class="{ 'rotate-180': isExpanded(i) }">
              <path d="m6 9 6 6 6-6"></path>
            </svg>
          </span>
        </div>
        <div class="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover/header:visible">
          {{ relativeTime(entry.step.timestamp) }}
        </div>
      </div>

      <!-- Step items: tool pills + progress narrations, chronologically ordered -->
      <div class="flex" v-if="entry.items.length">
        <div class="w-[24px] flex-shrink-0"></div>
        <div
          class="flex flex-col gap-[10px] flex-1 min-w-0 overflow-hidden pt-[6px] transition-[max-height,opacity] duration-150 ease-in-out"
          :class="{ 'max-h-[100000px] opacity-100': isExpanded(i), 'max-h-0 opacity-0': !isExpanded(i) }">
          <template v-for="item in entry.items" :key="item.seq">
            <ToolUse v-if="item.kind === 'tool' && item.tool" :tool="item.tool" @click="handleToolClick(item.tool)" />
            <div v-else
              class="flex items-start gap-[8px] text-[13px] leading-[1.5] text-[var(--text-secondary)] max-w-full">
              <span
                class="w-[5px] h-[5px] rounded-full bg-[var(--icon-tertiary)] mt-[7px] flex-shrink-0"></span>
              <span class="min-w-0 break-words" v-html="renderMarkdown(item.text || '')"></span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { CheckIcon, X as XIcon } from 'lucide-vue-next';
import ToolUse from './ToolUse.vue';
import { Message, MessageContent, ToolContent, StepContent } from '../types/message';
import { useRelativeTime } from '../composables/useTime';

const props = defineProps<{
  messages: Message[];
}>();

const emit = defineEmits<{
  (e: 'toolClick', tool: ToolContent): void;
}>();

const { relativeTime } = useRelativeTime();

// ── Chronological entries per step ──────────────────────────────────────────
// Tools live inside each step message (appended while the step runs); progress
// narrations arrive as interleaved assistant messages. Merge them into a single
// ordered item list per step so the timeline reads like one continuous story.
interface TimelineItem {
  kind: 'tool' | 'narration';
  timestamp: number;
  seq: number;
  tool?: ToolContent;
  text?: string;
}
interface StepEntry {
  step: StepContent;
  items: TimelineItem[];
}

const stepEntries = computed<StepEntry[]>(() => {
  const entries: StepEntry[] = [];
  let current: StepEntry | null = null;
  let seq = 0;
  for (const msg of props.messages) {
    if (msg.type === 'step') {
      current = { step: msg.content as StepContent, items: [] };
      entries.push(current);
    } else if (msg.type === 'assistant' && current) {
      const mc = msg.content as MessageContent;
      current.items.push({
        kind: 'narration',
        timestamp: mc.timestamp,
        seq: seq++,
        text: mc.content,
      });
    }
  }
  for (const entry of entries) {
    for (const tool of entry.step.tools || []) {
      entry.items.push({
        kind: 'tool',
        timestamp: tool.timestamp,
        seq: seq++,
        tool,
      });
    }
    // Stable sort: timestamp first, insertion order breaks ties.
    entry.items.sort((a, b) => a.timestamp - b.timestamp || a.seq - b.seq);
  }
  return entries;
});

// ── Per-step collapse state (default expanded) ──────────────────────────────
const expanded = reactive<Record<number, boolean>>({});
const isExpanded = (i: number) => expanded[i] !== false;
const toggle = (i: number) => {
  expanded[i] = !isExpanded(i);
};

const handleToolClick = (tool: ToolContent) => {
  emit('toolClick', tool);
};

// Minimal markdown render for step descriptions and narration lines.
const renderMarkdown = (text: string) => {
  if (typeof text !== 'string') return '';
  const html = marked.parseInline(text, { gfm: true }) as string;
  return DOMPurify.sanitize(html);
};
</script>
