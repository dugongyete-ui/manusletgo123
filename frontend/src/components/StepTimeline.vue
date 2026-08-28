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
          <!-- Official Manus LiveStatusLoading: lottie spinner while running -->
          <div v-else class="w-4 h-4 flex-shrink-0 flex items-center justify-center rounded-[15px] bg-[var(--background-gray-main)]">
            <LiveStatusCanvas :size="14" :active="entry.step.status === 'running'" />
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
           user-notification style of the Manus work loop.

           Official Manus StepGroup collapse behaviour:
           - while a step RUNS it stays expanded (live tools shimmer);
           - when the step COMPLETES it auto-collapses to the header line
             (narrations stay visible beside the rail);
           - the user can always re-expand via the chevron. -->
      <div class="flex" v-if="entry.items.length">
        <div class="w-[24px] flex-shrink-0"></div>
        <div
          class="flex flex-col gap-[10px] flex-1 min-w-0 overflow-hidden pt-[6px] transition-[max-height,opacity] duration-150 ease-in-out"
          :class="{ 'max-h-[100000px] opacity-100': isExpanded(i) || visibleItems(entry, i).length > 0, 'max-h-0 opacity-0': !isExpanded(i) && visibleItems(entry, i).length === 0 }">
          <template v-for="item in visibleItems(entry, i)" :key="item.seq">
            <ToolUse v-if="item.kind === 'tool' && item.tool" :tool="item.tool" :active="isActiveTool(entry, item)"
              @click="handleToolClick(item.tool)" />
            <!-- Narration: plain text line beside the rail — no bullet dot,
                 Manus-style. The text itself says what is happening. -->
            <div v-else
              class="text-[13px] leading-[1.55] text-[var(--text-secondary)] max-w-full">
              <span class="min-w-0 break-words" v-html="renderMarkdown(item.text || '')"></span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { CheckIcon, X as XIcon } from 'lucide-vue-next';
import ToolUse from './ToolUse.vue';
import LiveStatusCanvas from './LiveStatusCanvas.vue';
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
  return visibleItems(last, lastIdx).length && isExpanded(lastIdx) ? '0px' : '10px';
});

// ── Per-step collapse state (official Manus StepGroup) ─────────────────────
// 'auto': derived from status — running/failed steps expand, completed steps
// collapse to their header line (narrations stay). The user can override any
// step explicitly; the override survives later status changes.
type CollapseState = boolean | null; // null = auto
const expanded = reactive<Record<string, CollapseState>>({});

const stepKey = (i: number) => {
  const entry = stepEntries.value[i];
  return entry?.step.id || String(i);
};

const isExpanded = (i: number) => {
  const key = stepKey(i);
  const override = expanded[key];
  if (override !== null && override !== undefined) return override;
  const status = stepEntries.value[i]?.step.status;
  // Running (and failed, so the error context stays visible) steps expand;
  // completed steps auto-collapse — the classic Manus compact timeline.
  return status === 'running' || status === 'failed' || status === 'pending';
};

const toggle = (i: number) => {
  const key = stepKey(i);
  expanded[key] = !isExpanded(i);
};

// When a step finishes, drop any stale auto state so the collapse looks
// immediate (the computed already derives it, this just cleans up).
watch(() => stepEntries.value.map(e => e.step.status).join(','), () => {
  for (const key of Object.keys(expanded)) {
    if (expanded[key] === null) delete expanded[key];
  }
});

// Items rendered for an entry. Collapsed completed steps still show their
// narration lines beside the rail (the Manus work-loop notifications) and
// hide the tool pills; expanded shows everything.
const visibleItems = (entry: StepEntry, i: number): TimelineItem[] => {
  if (isExpanded(i)) return entry.items;
  return entry.items.filter(item => item.kind === 'narration');
};

// ── Live tool shimmer ───────────────────────────────────────────────────────
// The LAST tool row of a RUNNING step keeps its label shimmering for the whole
// live window (official Manus keeps the current action glowing while work
// continues, even between tool calls).
const isActiveTool = (entry: StepEntry, item: TimelineItem): boolean => {
  if (entry.step.status !== 'running') return false;
  const tools = entry.items.filter(it => it.kind === 'tool' && it.tool);
  const lastTool = tools[tools.length - 1];
  return lastTool === item;
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
