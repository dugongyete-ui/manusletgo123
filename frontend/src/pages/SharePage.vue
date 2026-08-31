<template>
  <SimpleBar ref="simpleBarRef" @scroll="handleScroll">
    <div class="relative flex flex-col h-full flex-1 min-w-0 px-5">
      <header class="sm:h-auto sticky top-0 left-0 right-0 z-10" style="background: var(--background-share-header);">
        <div
          class="min-h-[52px] px-[16px] py-[10px] sm:px-5 sm:py-3 items-center flex justify-between bg-[var(--background-gray-main)]">
          <div class="flex items-center gap-2 sm:gap-3 flex-1 min-w-0 sm:flex-none"><a href="/" class="hidden sm:flex">
              <div class="flex items-center gap-[3px]">
                <DzeckLogoMark :size="24" class="w-6 h-6" />
                <DzeckLogoTextIcon :height="30" :width="65" />
              </div>
            </a>
            <div
              class="text-[var(--text-primary)] text-lg font-[600] leading-[24px] flex-1 min-w-0 text-left sm:text-center sm:hidden overflow-hidden text-ellipsis whitespace-nowrap">
              {{ title }}</div>
          </div>
          <div
            class="text-lg font-medium text-[var(--text-primary)] flex-1 min-w-0 text-center hidden sm:block overflow-hidden text-ellipsis whitespace-nowrap">
            {{ title }}</div>
          <div class="flex items-center sm:gap-3"><button @click="handleCopyLink" :aria-label="t('Copy Link')"
              :title="t('Copy Link')"
              class="p-2 flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer">
              <Link class="text-[var(--icon-secondary)]" :size="20" />
            </button><button @click="handleFileListShow" :aria-label="t('File list')" :title="t('File list')"
              class="p-2 flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer">
              <FileSearch class="text-[var(--icon-secondary)]" :size="20" />
            </button>
          </div>
        </div>
      </header>
      <div class="mx-auto w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] flex flex-col flex-1">

        <!-- ── Loading state ─────────────────────────────────────── -->
        <div v-if="pageState === 'loading'" class="flex flex-col items-center justify-center gap-4 py-24 px-4">
          <div class="flex items-center gap-3 text-[var(--text-secondary)]">
            <LoaderCircle class="animate-spin" :size="20" />
            <span class="text-sm font-medium">{{ t('Loading shared task') }}…</span>
          </div>
          <div class="text-xs text-[var(--text-tertiary)]">{{ t('Preparing the conversation') }}</div>
          <!-- skeleton -->
          <div class="w-full max-w-[560px] flex flex-col gap-3 mt-4" aria-hidden="true">
            <div class="h-10 rounded-lg bg-[var(--fill-tsp-gray-main)] animate-pulse"></div>
            <div class="h-16 rounded-lg bg-[var(--fill-tsp-gray-main)] animate-pulse"></div>
            <div class="h-16 rounded-lg bg-[var(--fill-tsp-gray-main)] animate-pulse w-[90%] self-end"></div>
            <div class="h-10 rounded-lg bg-[var(--fill-tsp-gray-main)] animate-pulse w-[80%]"></div>
          </div>
        </div>

        <!-- ── Error state ───────────────────────────────────────── -->
        <div v-else-if="pageState === 'error'" class="flex flex-col items-center justify-center gap-4 py-20 px-4">
          <div class="flex items-center justify-center w-12 h-12 rounded-full bg-[var(--fill-tsp-gray-main)]">
            <AlertCircle class="text-[var(--icon-secondary)]" :size="24" />
          </div>
          <div class="text-base font-medium text-[var(--text-primary)] text-center max-w-[420px]">
            {{ t('This share link is not available') }}</div>
          <div class="text-sm text-[var(--text-secondary)] text-center max-w-[460px] leading-relaxed">
            {{ t('The link may be incorrect, the task may have been unshared, or the server could not be reached. Double-check the link, or ask the person who shared it with you.') }}
          </div>
          <div class="flex flex-col sm:flex-row items-center gap-2 w-full max-w-[420px] sm:justify-center">
            <button @click="retryLoad" :disabled="reloading"
              class="inline-flex items-center justify-center font-medium transition-colors hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-brand)] text-[var(--text-white)] h-[36px] rounded-[10px] gap-[6px] text-sm px-[16px] w-full sm:w-auto disabled:opacity-60">
              <LoaderCircle v-if="reloading" class="animate-spin" :size="16" />
              <span>{{ reloading ? t('Retrying') : t('Retry') }}</span>
            </button>
            <a href="/"
              class="inline-flex items-center justify-center font-medium transition-colors hover:opacity-90 active:opacity-80 border border-[var(--border-main)] text-[var(--text-primary)] h-[36px] rounded-[10px] gap-[6px] text-sm px-[16px] w-full sm:w-auto">
              {{ t('Back to home') }}</a>
          </div>
          <button v-if="loadError" @click="showTechnical = !showTechnical"
            class="text-xs text-[var(--text-tertiary)] underline underline-offset-2 cursor-pointer mt-2">
            {{ t('Technical details') }}
          </button>
          <pre v-if="loadError && showTechnical"
            class="text-xs text-[var(--text-tertiary)] bg-[var(--fill-tsp-gray-main)] rounded-lg p-3 max-w-[520px] w-full overflow-auto whitespace-pre-wrap font-mono">{{ loadError.technical }}</pre>
        </div>

        <!-- ── Empty state ───────────────────────────────────────── -->
        <div v-else-if="pageState === 'empty'" class="flex flex-col items-center justify-center gap-4 py-20 px-4">
          <div class="flex items-center justify-center w-12 h-12 rounded-full bg-[var(--fill-tsp-gray-main)]">
            <Inbox class="text-[var(--icon-secondary)]" :size="24" />
          </div>
          <div class="text-base font-medium text-[var(--text-primary)] text-center max-w-[420px]">
            {{ t('This task has no messages yet') }}</div>
          <div class="text-sm text-[var(--text-secondary)] text-center max-w-[460px] leading-relaxed">
            {{ t('The task exists, but it does not contain any messages to display. It may have been stopped before anything was produced.') }}
          </div>
          <a href="/"
            class="inline-flex items-center justify-center font-medium transition-colors hover:opacity-90 active:opacity-80 border border-[var(--border-main)] text-[var(--text-primary)] h-[36px] rounded-[10px] gap-[6px] text-sm px-[16px]">
            {{ t('Back to home') }}</a>
        </div>

        <!-- ── Success state: conversation ───────────────────────── -->
        <template v-else>
          <div class="flex flex-col w-full gap-[12px] pb-[80px] pt-[12px] flex-1 overflow-y-auto">
            <!-- Unified step timeline (SYNCED with production ChatPage): consecutive
                 step messages plus their progress narrations render as ONE connected
                 block with a continuous rail — not one detached block per step. -->
            <template v-for="group in messageGroups" :key="group.startIndex">
              <StepTimeline v-if="group.kind === 'timeline'" :messages="group.messages"
                @toolClick="handleToolClick" />
              <ChatMessage v-else :message="group.messages[0]" :hideHeader="isGroupHideHeader(group)"
                @toolClick="handleToolClick" />
            </template>

            <!-- Final validation gate card (P0) — rendered when the task
                 finished with a gate result. -->
            <ValidationCard v-if="validationResult" :result="validationResult" />
          </div>

          <div
            class="sticky bottom-0 max-w-[800px] mx-auto w-full pb-3 flex flex-col gap-2 px-3 pt-2.5 sm:pt-0">
            <button @click="handleFollow" v-if="!follow" :aria-label="t('Jump to live')" :title="t('Jump to live')"
              class="flex items-center justify-center w-[36px] h-[36px] rounded-full bg-[var(--background-white-main)] hover:bg-[var(--background-gray-main)] clickable border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-S)] absolute -top-20 left-1/2 -translate-x-1/2">
              <ArrowDown class="text-[var(--icon-primary)]" :size="20" />
            </button>
            <PlanPanel v-if="plan && plan.steps.length > 0" :plan="plan" @close="plan = undefined" />
            <div
              class="bg-[var(--background-white-main)] rounded-xl border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-XS)] backdrop-blur-3xl flex items-center justify-between py-[9px] pr-3 pl-4 sm:flex-row flex-col max-sm:gap-3 max-sm:p-2">
              <!-- left: mode description -->
              <div class="flex items-center gap-0.5 w-full sm:flex-1 min-w-0">
                <div class="w-6 h-6 shrink-0"><DzeckLogoMark :size="24" /></div>
                <div class="min-w-0">
                  <p class="text-sm text-[var(--text-primary)] truncate">
                    <template v-if="replayPhase === 'idle'">{{ t('You are viewing the results of a completed Dzeck task.') }}</template>
                    <template v-else-if="replayPhase === 'done'">{{ t('Replay completed') }}</template>
                    <template v-else>{{ replayPhase === 'paused' ? t('Paused') : t('Dzeck is replaying the task...') }}
                      <span class="text-[var(--text-tertiary)]">&nbsp;·&nbsp;{{ t('Event {current} of {total}', { current: replayCurrent, total: replayTotal }) }}</span>
                    </template>
                  </p>
                  <p v-if="activeStage && replayPhase !== 'idle' && replayPhase !== 'done'"
                    class="text-xs text-[var(--text-tertiary)] truncate">{{ t('Replaying step') }}: {{ activeStage }}</p>
                </div>
              </div>
              <!-- right: controls -->
              <div class="flex items-center flex-row gap-[8px] max-sm:w-full max-sm:justify-center flex-wrap">
                <!-- replay not started / done: (re)start replay -->
                <button v-if="replayPhase === 'idle' || replayPhase === 'done'" @click="startReplay"
                  class="inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-brand)] text-[var(--text-white)] h-[36px] rounded-[10px] gap-[6px] text-sm min-w-16 px-[14px] py-[6px] max-sm:flex-1">
                  <RotateCcw :size="16" />
                  <span class="text-sm">{{ replayPhase === 'done' ? t('Replay again') : t('Replay Workflow') }}</span>
                </button>
                <!-- replay running: pause / resume -->
                <template v-else>
                  <button @click="togglePause" :aria-label="replayPhase === 'paused' ? t('Resume') : t('Pause')"
                    class="inline-flex items-center justify-center font-medium transition-colors hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-brand)] text-[var(--text-white)] h-[36px] rounded-[10px] gap-[6px] text-sm px-[14px] py-[6px] max-sm:flex-1">
                    <Play v-if="replayPhase === 'paused'" :size="16" />
                    <Pause v-else :size="16" />
                    <span class="text-sm">{{ replayPhase === 'paused' ? t('Resume') : t('Pause') }}</span>
                  </button>
                  <!-- speed selector -->
                  <div class="flex items-center rounded-[10px] border border-[var(--border-main)] overflow-hidden h-[36px]"
                    role="group" :aria-label="t('Speed')">
                    <button v-for="s in [0.5, 1, 2]" :key="s" @click="replaySpeed = s"
                      :aria-pressed="replaySpeed === s"
                      class="px-[10px] h-full text-xs font-medium transition-colors min-w-[38px]"
                      :class="replaySpeed === s ? 'bg-[var(--fill-tsp-gray-main)] text-[var(--text-primary)]' : 'text-[var(--text-tertiary)] hover:bg-[var(--fill-tsp-gray-main)]'">
                      {{ s }}x</button>
                  </div>
                  <!-- restart -->
                  <button @click="startReplay" :aria-label="t('Restart')" :title="t('Restart')"
                    class="inline-flex items-center justify-center font-medium transition-colors hover:bg-[var(--fill-tsp-gray-main)] text-[var(--text-primary)] h-[36px] rounded-[10px] px-[10px]">
                    <RotateCcw :size="16" />
                  </button>
                  <!-- jump to results -->
                  <button @click="jumpToResults"
                    class="inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-brand)] text-[var(--text-white)] h-[36px] rounded-[10px] gap-[6px] text-sm min-w-16 px-[14px] py-[6px] max-sm:flex-1">
                    <span class="text-sm">{{ t('Jump to results') }}</span>
                  </button>
                </template>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <ToolPanel ref="toolPanel" :allTools="allTools" :sessionId="sessionId" :realTime="realTime"
      :isShare="true"
      @jumpToRealTime="jumpToRealTime" />
  </SimpleBar>
</template>

<script setup lang="ts">
import SimpleBar from '../components/SimpleBar.vue';
import { ref, onMounted, onUnmounted, watch, nextTick, reactive, toRefs, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import ChatMessage from '../components/ChatMessage.vue';
import StepTimeline from '../components/StepTimeline.vue';
import ValidationCard from '../components/ValidationCard.vue';
import * as agentApi from '../api/agent';
import { Message, MessageContent, ToolContent, StepContent, AttachmentsContent } from '../types/message';
import {
  StepEventData,
  ToolEventData,
  MessageEventData,
  ErrorEventData,
  TitleEventData,
  PlanEventData,
  ValidationEventData,
  ValidationResultData,
  AgentSSEEvent,
} from '../types/event';
import ToolPanel from '../components/ToolPanel.vue'
import PlanPanel from '../components/PlanPanel.vue';
import { ArrowDown, FileSearch, Link, AlertCircle, Inbox, Play, Pause, RotateCcw, LoaderCircle } from 'lucide-vue-next';
import DzeckLogoTextIcon from '../components/icons/DzeckLogoTextIcon.vue';
import DzeckLogoMark from '../components/icons/DzeckLogoMark.vue';
import { showErrorToast, showSuccessToast } from '../utils/toast';
import type { FileInfo } from '../api/file';
import { useSessionFileList } from '../composables/useSessionFileList'
import { useFilePanel } from '../composables/useFilePanel'
import { copyToClipboard } from '../utils/dom'

const router = useRouter()
const { t } = useI18n()
const { showSessionFileList } = useSessionFileList()
const { hideFilePanel } = useFilePanel()

// Create initial state factory
const createInitialState = () => ({
  inputMessage: '',
  isLoading: false,
  sessionId: undefined as string | undefined,
  messages: [] as Message[],
  toolPanelSize: 0,
  realTime: true,
  follow: true,
  title: t('New Chat'),
  plan: undefined as PlanEventData | undefined,
  lastNoMessageTool: undefined as ToolContent | undefined,
  lastMessageTool: undefined as ToolContent | undefined,
  lastTool: undefined as ToolContent | undefined,
  lastEventId: undefined as string | undefined,
  attachments: [] as FileInfo[],
  replayCompleted: false,
  validationResult: undefined as ValidationResultData | undefined,
});

// Create reactive state
const state = reactive(createInitialState());

// Destructure refs from reactive state
const {
  isLoading,
  sessionId,
  messages,
  realTime,
  follow,
  title,
  plan,
  lastNoMessageTool,
  lastTool,
  lastEventId,
  replayCompleted,
  validationResult,
} = toRefs(state);

// ── Page-level state machine (P0: share page never shows a blank screen) ──
type PageState = 'loading' | 'success' | 'empty' | 'error';
const pageState = ref<PageState>('loading');
const loadError = ref<{ code: number; message: string; technical: string } | null>(null);
const showTechnical = ref(false);
const reloading = ref(false);

// Structured logging for share lookups — shareId, lookup status, response
// status, load duration. NEVER logs tokens, message content, or attachments.
const shareLog = (fields: Record<string, unknown>) => {
  console.info('[share-page]', JSON.stringify(fields));
};

// Map an API failure into a user-facing + technical error object. The axios
// interceptor already normalizes to { code, message, details }.
const normalizeLoadError = (err: any) => {
  const code = Number(err?.code ?? 0);
  const rawMessage = String(err?.message ?? 'Unknown error');
  const details = err?.details ? JSON.stringify(err.details) : undefined;
  let friendly: string;
  if (code === 404) {
    friendly = 'The shared task was not found (it may have been unshared or the link is wrong).';
  } else if (code === 0 || code === 503 || /network/i.test(rawMessage)) {
    friendly = 'Could not reach the server (network error or the API is still starting).';
  } else if (code >= 500) {
    friendly = 'The server returned an error while loading the shared task.';
  } else {
    friendly = rawMessage;
  }
  return {
    code,
    message: friendly,
    technical: JSON.stringify(
      { share_id: sessionId.value, http_status: code, error: rawMessage, details },
      null, 2
    ),
  };
};

// ── Replay engine (P1: deterministic playback of historical events only) ──
// Replay NEVER re-sends messages, files, or any external action: it iterates
// the session's persisted event log and feeds it to the same render handlers.
type ReplayPhase = 'idle' | 'playing' | 'paused' | 'done';
const replayPhase = ref<ReplayPhase>('idle');
const replaySpeed = ref<0.5 | 1 | 2>(1);
const replayCurrent = ref(0);
const replayTotal = ref(0);
const activeStage = ref('');
// Non-reactive cache of the fetched events — the replay loop reads it, it
// never triggers Vue reactivity.
let sharedEvents: AgentSSEEvent[] = [];
let replayToken = 0;

const REPLAY_BASE_DELAY_MS = 300;

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Human label of the event currently being replayed (progress narration).
const describeEvent = (event: AgentSSEEvent): string => {
  const d = event.data as any;
  switch (event.event) {
    case 'step':
      return d?.description || t('Stages');
    case 'tool':
      return d?.brief || d?.name || d?.function || 'tool';
    case 'message':
      return d?.role === 'user' ? t('User message') : d?.is_final ? t('Final summary') : t('Message');
    case 'title':
      return t('Title');
    case 'plan':
      return t('Plan');
    case 'error':
      return t('Error');
    default:
      return t('Message');
  }
};

// Flat ordered list of all non-message tools — used for panel navigation
const allTools = computed<ToolContent[]>(() => {
  const tools: ToolContent[] = []
  for (const msg of messages.value) {
    if (msg.type === 'tool') {
      const tool = msg.content as ToolContent
      if (tool.name !== 'message') tools.push(tool)
    } else if (msg.type === 'step') {
      const step = msg.content as StepContent
      for (const tool of step.tools) {
        if (tool.name !== 'message') tools.push(tool)
      }
    }
  }
  return tools
})

// Non-state refs that don't need reset
const toolPanel = ref<InstanceType<typeof ToolPanel>>()
const simpleBarRef = ref<InstanceType<typeof SimpleBar>>();

// Watch message changes and automatically scroll to bottom
watch(messages, async () => {
  await nextTick();
  if (follow.value) {
    simpleBarRef.value?.scrollToBottom();
  }
}, { deep: true });



// ── Message grouping (SYNCED with production ChatPage) ─────────────────────
// Manus-style: ONE task run = ONE connected timeline. From the first step
// message, every mid-task element — subsequent steps, progress narrations
// (is_progress), the model's own inline narration text — renders INSIDE the
// timeline, beside the continuous rail. Only these break the timeline back
// into standalone chat bubbles:
//   • the final summary (is_final)      • agent questions (is_question)
//   • user / error / attachment messages
// The ack (before the first step) naturally stays standalone.
interface MessageGroup {
  kind: 'single' | 'timeline';
  messages: Message[];
  startIndex: number;
  /** True when the previous RENDERED element is also an assistant bubble, so
   *  this group continues it and skips its own avatar header. */
  hideHeader?: boolean;
}
const messageGroups = computed<MessageGroup[]>(() => {
  const groups: MessageGroup[] = [];
  const msgs = messages.value;
  let timeline: MessageGroup | null = null;
  // A message renders as an assistant bubble (with the Dzeck avatar header)
  // when it stands alone — narrations absorbed into a timeline do NOT count:
  // they render inside the timeline rail, invisible to header suppression.
  const isAssistantBubble = (m: Message) =>
    m.type === 'assistant' ||
    (m.type === 'attachments' && (m.content as AttachmentsContent).role === 'assistant');
  const pushSingle = (m: Message, i: number) => {
    const prev = groups.length ? groups[groups.length - 1] : null;
    const prevIsAssistantBubble = !!(
      prev && prev.kind === 'single' && isAssistantBubble(prev.messages[0])
    );
    groups.push({
      kind: 'single',
      messages: [m],
      startIndex: i,
      hideHeader: isAssistantBubble(m) && prevIsAssistantBubble,
    });
  };
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i];
    if (m.type === 'step') {
      if (timeline) {
        timeline.messages.push(m);
      } else {
        timeline = { kind: 'timeline', messages: [m], startIndex: i };
        groups.push(timeline);
      }
      continue;
    }
    if (m.type === 'assistant') {
      const mc = m.content as MessageContent;
      if (mc.is_final || mc.is_question) {
        // Summary / question — standalone, ends the timeline. It always gets
        // its own avatar header (Manus-style): the narration lines before it
        // rendered INSIDE the timeline, not as an assistant bubble.
        pushSingle(m, i);
        timeline = null;
      } else if (timeline) {
        // Mid-task narration → inside the timeline, beside the rail.
        timeline.messages.push(m);
      } else {
        // Ack / pre-plan text — standalone (no timeline started yet).
        pushSingle(m, i);
      }
      continue;
    }
    // user / tool / attachments — standalone, timeline ends.
    pushSingle(m, i);
    timeline = null;
  }
  return groups;
});

// Consecutive-assistant header suppression, evaluated on RENDERED groups
// (SYNCED with production ChatPage): the header is hidden only when the
// previous rendered group is itself a standalone assistant bubble. A summary
// following the tool timeline always keeps its Dzeck avatar header.
const isGroupHideHeader = (group: MessageGroup): boolean => {
  if (group.kind !== 'single') return false;
  return !!group.hideHeader;
};

// Index of the last user message — steps of the CURRENT run only exist after
// it. Step ids restart at "1" for every new task in the same session, so a
// global id lookup would morph the previous task's step rows instead of
// stacking a new step group.
const lastUserMessageIndex = (): number => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].type === 'user') return i;
  }
  return -1;
}

const getLastStep = (): StepContent | undefined => {
  const from = lastUserMessageIndex();
  for (let i = messages.value.length - 1; i > from; i--) {
    if (messages.value[i].type === 'step')
      return messages.value[i].content as StepContent;
  }
  return undefined;
}

// Handle message event
const handleMessageEvent = (messageData: MessageEventData) => {
  messages.value.push({
    type: messageData.role,
    content: {
      ...messageData
    } as MessageContent,
  });

  if (messageData.attachments?.length > 0) {
    messages.value.push({
      type: 'attachments',
      content: {
        ...messageData
      } as AttachmentsContent,
    });
  }
}

// Handle tool event
const handleToolEvent = (toolData: ToolEventData) => {
  // Message-tool events (message_notify_user) are progress narrations, not
  // tool pills: render them as narration text INSIDE the unified timeline
  // (beside the rail) — SYNCED with production ChatPage. The CALLED event
  // carries the same text and is skipped to avoid duplicates.
  if (toolData.name === 'message') {
    const text = (toolData.args as any)?.text
    if (toolData.status === 'calling' && text) {
      messages.value.push({
        type: 'assistant',
        content: {
          content: text,
          timestamp: toolData.timestamp,
          is_progress: true,
        } as MessageContent,
      })
    }
    return
  }

  const lastStep = getLastStep();
  let toolContent: ToolContent = {
    ...toolData
  }
  if (lastTool.value && lastTool.value.tool_call_id === toolContent.tool_call_id) {
    Object.assign(lastTool.value, toolContent);
  } else {
    if (lastStep) {
      // Attach to the last step EVEN WHEN COMPLETED — SYNCED with ChatPage.
      // Tools arriving after a step's final JSON still belong inside the
      // timeline; detached tool messages would break the continuous rail.
      lastStep.tools.push(toolContent);
    } else {
      messages.value.push({
        type: 'tool',
        content: toolContent,
      });
    }
    lastTool.value = toolContent;
  }
  if (toolContent.name !== 'message') {
    lastNoMessageTool.value = toolContent;
    // Do NOT auto-open the tool panel — SYNCED with production ChatPage.
    // During replay the visitor stays in the chat view (timeline); the panel
    // opens only when a tool pill is clicked manually, so at the end of the
    // replay the timeline is fully visible instead of being covered.
  }
}

// Handle step event
// Official semantics (SYNCED with production ChatPage): completed/failed
// updates the MATCHED step (by id, fallback last) with status + description +
// result (the outcome text shown under the StepGroup).
const findStepById = (id: string): StepContent | undefined => {
  // Only match steps from the CURRENT run (after the last user message) —
  // step ids restart per task, so ids collide across runs in one session.
  const from = lastUserMessageIndex();
  for (let i = messages.value.length - 1; i > from; i--) {
    const message = messages.value[i];
    if (message.type !== 'step') continue;
    const step = message.content as StepContent;
    if (step.id === id) return step;
  }
  return undefined;
};

// Sync a step's status into plan.value.steps so PlanPanel stays up-to-date
// during replay — SYNCED with production ChatPage (positional matching:
// first-pending / first-running, because the planner may regenerate ids).
const syncStepToPlan = (status: string) => {
  if (!plan.value) return;
  if (status === 'running') {
    const pendingStep = plan.value.steps.find(s => s.status === 'pending');
    if (pendingStep) pendingStep.status = 'running';
  } else if (status === 'completed') {
    const runningStep = plan.value.steps.find(s => s.status === 'running');
    if (runningStep) runningStep.status = 'completed';
  } else if (status === 'failed') {
    const runningStep = plan.value.steps.find(s => s.status === 'running');
    if (runningStep) runningStep.status = 'failed';
  }
}

const handleStepEvent = (stepData: StepEventData) => {
  if (stepData.status === 'running' || stepData.status === 'pending') {
    const existing = findStepById(stepData.id);
    if (existing) {
      existing.status = stepData.status === 'pending' ? 'running' : stepData.status;
      existing.description = stepData.description || existing.description;
      return;
    }
    messages.value.push({
      type: 'step',
      content: {
        ...stepData,
        status: stepData.status === 'pending' ? 'running' : stepData.status,
        tools: []
      } as StepContent,
    });
    syncStepToPlan('running');
  } else if (stepData.status === 'completed') {
    const matched = findStepById(stepData.id) ?? getLastStep();
    if (matched) {
      matched.status = stepData.status;
      if (stepData.description) matched.description = stepData.description;
      if (stepData.result) matched.result = stepData.result;
    }
    syncStepToPlan('completed');
  } else if (stepData.status === 'failed') {
    const matched = findStepById(stepData.id) ?? getLastStep();
    if (matched) {
      matched.status = stepData.status;
      if (stepData.description) matched.description = stepData.description;
      if (stepData.result) matched.result = stepData.result;
    }
    isLoading.value = false;
    syncStepToPlan('failed');
  }
}

// Handle error event
const handleErrorEvent = (errorData: ErrorEventData) => {
  isLoading.value = false;
  messages.value.push({
    type: 'assistant',
    content: {
      content: errorData.error,
      timestamp: errorData.timestamp,
      // Terminal message — always standalone, never swallowed by a timeline.
      is_final: true,
    } as MessageContent,
  });
}

// Handle title event
const handleTitleEvent = (titleData: TitleEventData) => {
  title.value = titleData.title;
}

// Handle plan event
const handlePlanEvent = (planData: PlanEventData) => {
  plan.value = planData;
}

// Handle validation event — the final gate result (P0). Kept as state and
// rendered as a card below the timeline (never a chat bubble: it is a task
// artifact, not a message).
const handleValidationEvent = (validationData: ValidationEventData) => {
  validationResult.value = validationData.result;
}

// Main event handler function
const handleEvent = (event: AgentSSEEvent) => {
  if (event.event === 'message') {
    handleMessageEvent(event.data as MessageEventData);
  } else if (event.event === 'tool') {
    handleToolEvent(event.data as ToolEventData);
  } else if (event.event === 'step') {
    handleStepEvent(event.data as StepEventData);
  } else if (event.event === 'done') {
    //isLoading.value = false;
  } else if (event.event === 'wait') {
    // TODO: handle wait event
  } else if (event.event === 'error') {
    handleErrorEvent(event.data as ErrorEventData);
  } else if (event.event === 'title') {
    handleTitleEvent(event.data as TitleEventData);
  } else if (event.event === 'plan') {
    handlePlanEvent(event.data as PlanEventData);
  } else if (event.event === 'validation') {
    handleValidationEvent(event.data as ValidationEventData);
  }
  lastEventId.value = event.data.event_id;
}

// Reset all refs to their initial values
const resetState = () => {
  // Reset reactive state to initial values
  Object.assign(state, createInitialState());
};

// ── Replay control actions ─────────────────────────────────────────────────
// All of them operate on sharedEvents (persisted history) only.

const startReplay = async () => {
  if (!sharedEvents.length) return;
  hideFilePanel();
  toolPanel.value?.hideToolPanel();
  const token = ++replayToken;
  resetState();
  realTime.value = true;
  follow.value = true;
  replayTotal.value = sharedEvents.length;
  replayCurrent.value = 0;
  replayPhase.value = 'playing';
  replayCompleted.value = false;
  shareLog({ phase: 'replay_start', share_id: sessionId.value, events: sharedEvents.length, speed: replaySpeed.value });
  for (let i = 0; i < sharedEvents.length; i++) {
    if (token !== replayToken) return; // aborted by restart / jump
    // Pause-aware wait: stays here while paused, exits immediately on abort.
    while (replayPhase.value === 'paused' && token === replayToken) {
      await sleep(150);
    }
    if (token !== replayToken) return;
    replayCurrent.value = i + 1;
    activeStage.value = describeEvent(sharedEvents[i]);
    handleEvent(sharedEvents[i]);
    await sleep(REPLAY_BASE_DELAY_MS / replaySpeed.value);
  }
  if (token !== replayToken) return;
  replayPhase.value = 'done';
  replayCompleted.value = true;
  activeStage.value = '';
  shareLog({ phase: 'replay_done', share_id: sessionId.value, events: sharedEvents.length });
};

const togglePause = () => {
  if (replayPhase.value === 'playing') {
    replayPhase.value = 'paused';
    shareLog({ phase: 'replay_pause', share_id: sessionId.value, at: replayCurrent.value });
  } else if (replayPhase.value === 'paused') {
    replayPhase.value = 'playing';
    shareLog({ phase: 'replay_resume', share_id: sessionId.value, at: replayCurrent.value });
  }
};

// Abort any running replay and render the full history instantly.
const jumpToResults = async () => {
  replayToken++; // abort the loop
  hideFilePanel();
  toolPanel.value?.hideToolPanel();
  resetState();
  realTime.value = false;
  follow.value = false;
  for (const event of sharedEvents) {
    handleEvent(event);
  }
  realTime.value = true;
  replayPhase.value = 'done';
  replayCompleted.value = true;
  replayCurrent.value = replayTotal.value;
  activeStage.value = '';
  await nextTick();
  simpleBarRef.value?.scrollToBottom();
  shareLog({ phase: 'jump_to_results', share_id: sessionId.value });
};

// ── Load / restore ─────────────────────────────────────────────────────────

const retryLoad = async () => {
  if (reloading.value) return;
  reloading.value = true;
  await loadSession();
  reloading.value = false;
};

const loadSession = async () => {
  if (!sessionId.value) {
    pageState.value = 'error';
    loadError.value = { code: 0, message: 'No session id in the URL.', technical: 'route param sessionId is missing' };
    return;
  }
  const startedAt = performance.now();
  pageState.value = 'loading';
  loadError.value = null;
  try {
    const session = await agentApi.getSharedSession(sessionId.value);
    const loadMs = Math.round(performance.now() - startedAt);
    const events = session.events || [];
    sharedEvents = events;
    if (!events.length) {
      // Valid share id, no conversation content.
      pageState.value = 'empty';
      shareLog({ phase: 'lookup', share_id: sessionId.value, status: 200, found: true, events: 0, load_ms: loadMs });
      return;
    }
    realTime.value = false;
    follow.value = false; // Prevent auto-scrolling during restoration
    for (const event of events) {
      handleEvent(event);
    }
    realTime.value = true;
    pageState.value = 'success';
    shareLog({ phase: 'lookup', share_id: sessionId.value, status: 200, found: true, events: events.length, load_ms: loadMs });
  } catch (err: any) {
    const loadMs = Math.round(performance.now() - startedAt);
    pageState.value = 'error';
    loadError.value = normalizeLoadError(err);
    shareLog({ phase: 'lookup', share_id: sessionId.value, status: err?.code || 'network', found: false, load_ms: loadMs });
  }
};

// Initialize: View Results is the default mode — the conversation renders
// immediately; Replay Workflow is an explicit user action.
onMounted(async () => {
  hideFilePanel();
  const routeParams = router.currentRoute.value.params;
  if (routeParams.sessionId) {
    sessionId.value = String(routeParams.sessionId) as string;
  }
  await loadSession();
});

onUnmounted(() => {
  // Abort any in-flight replay loop when leaving the page.
  replayToken++;
});

const handleToolClick = (tool: ToolContent) => {
  realTime.value = false;
  if (sessionId.value) {
    toolPanel.value?.showToolPanel(tool, false);
  }
}

const jumpToRealTime = () => {
  realTime.value = true;
  if (lastNoMessageTool.value) {
    toolPanel.value?.showToolPanel(lastNoMessageTool.value, false);
  }
}

const handleFollow = () => {
  follow.value = true;
  simpleBarRef.value?.scrollToBottom();
}

const handleScroll = (_: Event) => {
  follow.value = simpleBarRef.value?.isScrolledToBottom() ?? false;
}

const handleFileListShow = () => {
  showSessionFileList(true)
}

const handleCopyLink = async () => {
  if (!sessionId.value) return;
  const shareUrl = `${window.location.origin}/share/${sessionId.value}`;

  try {
    const success = await copyToClipboard(shareUrl);

    if (success) {
      showSuccessToast(t('Link copied to clipboard'));
    } else {
      showErrorToast(t('Failed to copy link'));
    }
  } catch (error) {
    console.error('Error copying share link:', error);
    showErrorToast(t('Failed to copy link'));
  }
}
</script>

<style scoped></style>
