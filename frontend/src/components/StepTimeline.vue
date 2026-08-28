<template>
  <!-- Official Manus StepGroup shells, stacked with pb-0 when the next block is
       also a step (isStepConnectedToNext). Each step is its own collapsible
       group:

       • default state  → COLLAPSED (ChevronRight)
       • collapsed LIVE (running) → still shows lastToolItems (the current tool)
       • collapsed DONE (completed/failed) → header only — no body, no line
       • expanded       → precedingItems + lastToolItems (everything)

       Progress narrations (message_notify_user) are NOT part of the step body —
       they render as standalone chat messages BETWEEN the step groups, exactly
       like the official chat timeline. -->
  <div v-for="(entry, i) in stepEntries" :key="entry.step.id || i"
    class="flex flex-col empty:pb-0"
    :class="i < stepEntries.length - 1 ? 'pb-0' : 'pb-2'">
    <div class="flex flex-col">
      <!-- Step header — official: h-[28px] single line, text-secondary,
           hover:text-primary, toggle only when rows are hidden while collapsed -->
      <component
        :is="entry.canToggle ? 'button' : 'div'"
        :type="entry.canToggle ? 'button' : undefined"
        class="relative flex h-[28px] w-full min-w-0 items-center overflow-hidden whitespace-nowrap text-[14px] font-normal text-[var(--text-secondary)]"
        :class="entry.canToggle
          ? 'group/header clickable hover:text-[var(--text-primary)] border-0 bg-transparent p-0 text-start'
          : undefined"
        @click="entry.canToggle ? toggleStep(entry) : undefined"
      >
        <div class="flex min-w-0 flex-1 flex-nowrap items-center gap-[4px] overflow-hidden">
          <div class="flex size-[20px] flex-shrink-0 items-center justify-center rounded-[100px]">
            <div
              v-if="entry.completed"
              class="bg-[var(--fill-tsp-white-dark)] rounded-full size-[17px] flex items-center justify-center"
            >
              <StepCheckIcon :size="9" class="text-[var(--icon-tertiary)]" />
            </div>
            <LiveStatusCanvas v-else :size="16" :active="entry.step.status === 'running'" />
          </div>
          <div class="flex min-w-0 flex-1 items-center justify-start gap-[4px] overflow-hidden py-[4px]">
            <span class="min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap leading-[20px]">
              {{ entry.step.description }}
            </span>
            <span
              v-if="entry.canToggle"
              class="hidden size-[16px] flex-shrink-0 items-center justify-center group-hover/header:flex"
              :class="(!entry.completed || entry.expanded) ? 'flex' : undefined"
            >
              <ChevronDown v-if="entry.expanded" :size="16" color="currentColor" />
              <ChevronRight v-else :size="16" color="currentColor" />
            </span>
          </div>
        </div>
        <div
          class="float-right transition text-[12px] leading-[16px] text-[var(--text-tertiary)] ms-auto flex-shrink-0"
          :class="entry.canToggle ? 'invisible group-hover/header:visible' : undefined"
        >
          {{ relativeTime(entry.step.timestamp) }}
        </div>
      </component>

      <!-- Step body — official: solid 1px rail in a w-[20px] column, content
           indented ps-[20px]. Only rendered when rows are visible. The body
           animates in with a short fade/slide so expand–collapse feels smooth
           instead of snapping. -->
      <div v-if="entry.hasBody" class="flex min-w-0 flex-col step-body-in">
        <div class="relative min-w-0">
          <div class="pointer-events-none absolute inset-y-0 start-0 flex w-[20px] justify-center py-2">
            <div class="h-full w-px flex-none bg-[var(--border-main)]"></div>
          </div>
          <div class="flex min-w-0 flex-col ps-[20px]">
            <div class="min-w-0 overflow-hidden" style="height: auto; opacity: 1">
              <div class="min-w-0">
                <div class="flex min-w-0 flex-col">
                  <div
                    v-for="item in entry.visiblePreceding"
                    :key="item.id"
                    class="min-w-0 [&:has(>[data-timeline-content]:empty)]:hidden"
                    style="opacity: 1; transform: none"
                  >
                    <div data-timeline-content="true" class="min-w-0 flex-1 py-1 ps-[4px]">
                      <ToolUse
                        v-if="item.kind === 'tool'"
                        :tool="item.tool"
                        :active="entry.liveToolId === item.id"
                        @click="handleToolClick(item.tool)"
                      />
                    </div>
                  </div>
                  <div
                    v-for="item in entry.visibleLast"
                    :key="item.id"
                    class="min-w-0 [&:has(>[data-timeline-content]:empty)]:hidden"
                    style="opacity: 1; transform: none"
                  >
                    <div data-timeline-content="true" class="min-w-0 flex-1 py-1 ps-[4px]">
                      <ToolUse
                        v-if="item.kind === 'tool'"
                        :tool="item.tool"
                        :active="entry.liveToolId === item.id"
                        @click="handleToolClick(item.tool)"
                      />
                      <!-- Step result — official shows a short outcome line under
                           the StepGroup. Long results (older sessions, verbose
                           models) are clamped to ~300 chars with a Show more /
                           Show less toggle so an expanded step never becomes a
                           wall of text. -->
                      <div v-else class="flex flex-col gap-1 w-full">
                        <p class="text-[var(--text-secondary)] text-[14px] u-break-words whitespace-pre-wrap m-0">
                          {{ clampedResult(item) }}
                        </p>
                        <button
                          v-if="item.text.length > RESULT_CLAMP"
                          type="button"
                          class="self-start text-[13px] font-medium text-[var(--text-brand)] hover:underline clickable bg-transparent border-0 p-0"
                          @click="toggleResult(item.id)"
                        >
                          {{ resultExpanded[item.id] ? t('Show less') : t('Show more') }}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue';
import { useI18n } from 'vue-i18n';
import { ChevronDown, ChevronRight } from 'lucide-vue-next';
import ToolUse from './ToolUse.vue';
import LiveStatusCanvas from './LiveStatusCanvas.vue';
import StepCheckIcon from './icons/StepCheckIcon.vue';
import { Message, ToolContent, StepContent, StepTimelineItem, resolveStepTimelineVisibility } from '../types/message';
import { useRelativeTime } from '../composables/useTime';

const props = defineProps<{
  messages: Message[];
}>();

const emit = defineEmits<{
  (e: 'toolClick', tool: ToolContent): void;
}>();

const { t } = useI18n();
const { relativeTime } = useRelativeTime();

// ── Per-step reactive expansion state (official: default collapsed) ─────────
// The user's toggle wins; the key survives status changes of the same step.
const expandedOverrides = reactive<Record<string, boolean>>({});

// ── Step result clamp ────────────────────────────────────────────────────────
// The result is a short outcome line; anything past ~300 characters collapses
// with an ellipsis + Show more toggle (same pattern as the narration clamp in
// ChatMessage) so an expanded step stays compact and scannable.
const RESULT_CLAMP = 300;
const resultExpanded = reactive<Record<string, boolean>>({});
const clampedResult = (item: StepTimelineItem & { text: string }): string => {
  if (item.kind !== 'result') return '';
  const text = item.text || '';
  if (resultExpanded[item.id] || text.length <= RESULT_CLAMP) return text;
  return `${text.slice(0, RESULT_CLAMP).trimEnd()}…`;
};
const toggleResult = (id: string) => {
  resultExpanded[id] = !resultExpanded[id];
};

interface StepEntry {
  step: StepContent;
  completed: boolean;
  canToggle: boolean;
  expanded: boolean;
  hasBody: boolean;
  visiblePreceding: StepTimelineItem[];
  visibleLast: StepTimelineItem[];
  liveToolId: string | null;
}

// Consecutive step messages render as stacked StepGroup shells. Narrations and
// other chat messages never enter here — they break the group in ChatPage.
const stepEntries = computed<StepEntry[]>(() => {
  const entries: StepEntry[] = [];
  for (const msg of props.messages) {
    if (msg.type !== 'step') continue;
    const step = msg.content as StepContent;
    const visibility = resolveStepTimelineVisibility(step);
    const completed = step.status === 'completed' || step.status === 'failed';
    const key = step.id;
    const override = expandedOverrides[key];
    const expanded = override !== undefined ? override : false;

    const visiblePreceding = expanded ? visibility.precedingItems : [];
    const visibleLast = visibility.lastToolItems.length === 0
      ? []
      : (expanded ? visibility.lastToolItems : visibility.collapsedVisibleItems);

    // Current (last) tool of a running step keeps its label shimmering.
    let liveToolId: string | null = null;
    if (!completed) {
      for (let i = visibility.lastToolItems.length - 1; i >= 0; i -= 1) {
        const item = visibility.lastToolItems[i];
        if (item.kind === 'tool') { liveToolId = item.id; break; }
      }
    }

    entries.push({
      step,
      completed,
      canToggle: visibility.canToggle,
      expanded,
      hasBody: visiblePreceding.length > 0 || visibleLast.length > 0,
      visiblePreceding,
      visibleLast,
      liveToolId,
    });
  }
  return entries;
});

// Toggle via the reactive override map (mutating entry objects from the
// computed would be discarded on re-evaluation).
const toggleStep = (entry: StepEntry) => {
  const key = entry.step.id;
  expandedOverrides[key] = !entry.expanded;
};

const handleToolClick = (tool: ToolContent) => {
  emit('toolClick', tool);
};
</script>

<style scoped>
/* Smooth expand/collapse: the step body fades and slides in shortly instead
   of popping into place. Runs once when the body mounts (v-if toggling). */
.step-body-in {
  animation: step-body-in 160ms ease-out;
}
@keyframes step-body-in {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@media (prefers-reduced-motion: reduce) {
  .step-body-in {
    animation: none;
  }
}
</style>
