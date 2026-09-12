<template>
  <div class="step-timeline relative flex flex-col w-full">
    <!-- ONE continuous rail: a single unbroken dashed line from the first
         step's node down through EVERY following step, narration and tool
         row. The whole timeline shares ONE rail element, so the line can
         never be cut between steps — no segment stitching, no gaps, no
         restarts (Manus-style work loop). Status icons sit ON the line as
         nodes (solid backgrounds) and all progress text renders BESIDE the
         rail, indented right of it. -->
    <div v-if="stepEntries.length"
      class="absolute left-[7px] top-[10px] border-l border-dashed border-[var(--border-dark)] pointer-events-none"
      :style="{ bottom: railBottom }"></div>

    <div v-for="(entry, i) in stepEntries" :key="entry.step.id || i" class="relative flex flex-col"
      :class="i < stepEntries.length - 1 ? 'pb-[12px]' : ''">
      <!-- Step header: status node + description + chevron -->
      <div
        class="text-sm w-full clickable flex gap-2 justify-between group/header truncate text-[var(--text-primary)]">
        <div class="flex flex-row gap-2 justify-center items-center truncate" @click="toggle(i)">
          <!-- status node — solid background so the rail passes BEHIND it -->
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
            class="w-4 h-4 flex-shrink-0 flex items-center justify-center border border-[var(--border-dark)] rounded-[15px] bg-[var(--background-gray-main)]">
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

      <!-- Step items: tool pills + progress narrations, chronologically ordered.
           Narration text renders BESIDE the rail (indented right of it) — the
           user-notification style of the Manus work loop. Long narrations
           (300+ chars) clamp with a Show more toggle so the timeline stays
           compact and scannable. -->
      <div class="flex" v-if="entry.items.length">
        <div class="w-[24px] flex-shrink-0"></div>
        <div
          class="flex flex-col gap-[10px] flex-1 min-w-0 overflow-hidden pt-[6px] transition-[max-height,opacity] duration-150 ease-in-out"
          :class="{ 'max-h-[100000px] opacity-100': isExpanded(i), 'max-h-0 opacity-0': !isExpanded(i) }">
          <template v-for="item in entry.items" :key="item.seq">
            <ToolUse v-if="item.kind === 'tool' && item.tool" :tool="item.tool" @click="handleToolClick(item.tool)" />
            <!-- Narration: plain text line beside the rail — no bullet dot,
                 Manus-style. The text itself says what is happening. -->
            <div v-else
              class="text-[13px] leading-[1.55] text-[var(--text-secondary)] max-w-full">
              <span class="min-w-0 break-words" v-html="renderMarkdown(clampedNarration(item))"></span>
              <button v-if="(item.text || '').length > NARRATION_CLAMP" type="button"
                class="block mt-[2px] text-[13px] font-medium text-[var(--text-brand)] hover:underline clickable bg-transparent border-0 p-0"
                @click="toggleNarration(item.seq)">
                {{ narrationExpanded[item.seq] ? t('Show less') : t('Show more') }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue';
import { useI18n } from 'vue-i18n';
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

const { t } = useI18n();
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
      if (!mc.content) continue;
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
      // Message-tool events are converted to narration messages by
      // handleToolEvent — if one still rides along inside a step (legacy
      // session state), skip it so its text never renders twice.
      if (tool.name === 'message') continue;
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

// Where the single rail ends. With visible items under the last step (tool
// pills / narrations), the line runs beside them to the bottom of the block.
// Otherwise it stops exactly at the last node's center (header height 20px,
// icon center at 10px) — the line never dangles past the final node.
const railBottom = computed(() => {
  const entries = stepEntries.value;
  const last = entries[entries.length - 1];
  if (!last) return '0px';
  const lastIdx = entries.length - 1;
  return last.items.length && isExpanded(lastIdx) ? '0px' : '10px';
});

// ── Per-step collapse state (default expanded) ──────────────────────────────
const expanded = reactive<Record<number, boolean>>({});
const isExpanded = (i: number) => expanded[i] !== false;
const toggle = (i: number) => {
  expanded[i] = !isExpanded(i);
};

// ── Narration clamp ──────────────────────────────────────────────────────────
// Progress narrations render beside the rail; anything past ~300 characters
// collapses to an ellipsis with a Show more toggle, so one verbose narration
// can never turn the timeline into a wall of text (user requirement: keep
// narrations around ~300 chars, clear and readable).
const NARRATION_CLAMP = 300;
const narrationExpanded = reactive<Record<number, boolean>>({});
const clampedNarration = (item: TimelineItem): string => {
  const text = item.text || '';
  if (narrationExpanded[item.seq] || text.length <= NARRATION_CLAMP) return text;
  return `${text.slice(0, NARRATION_CLAMP).trimEnd()}…`;
};
const toggleNarration = (seq: number) => {
  narrationExpanded[seq] = !narrationExpanded[seq];
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
