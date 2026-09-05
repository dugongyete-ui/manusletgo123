<template>
  <SimpleBar ref="simpleBarRef" @scroll="handleScroll">
    <div ref="chatContainerRef" class="relative flex flex-col h-full flex-1 min-w-0 px-5">
      <div ref="observerRef"
        class="sm:min-w-[390px] flex flex-row items-center justify-between pt-3 pb-1 gap-1 sticky top-0 z-10 bg-[var(--background-gray-main)] flex-shrink-0">
        <div class="flex items-center flex-1">
          <div class="relative flex items-center">
            <div @click="toggleLeftPanel" v-if="!isLeftPanelShow"
              class="flex h-7 w-7 items-center justify-center cursor-pointer rounded-md hover:bg-[var(--fill-tsp-gray-main)]">
              <PanelLeft class="size-5 text-[var(--icon-secondary)]" />
            </div>
          </div>
        </div>
        <div class="max-w-full sm:max-w-[768px] sm:min-w-[390px] flex w-full flex-col gap-[4px] overflow-hidden">
          <div
            class="text-[var(--text-primary)] text-lg font-medium w-full flex flex-row items-center justify-between flex-1 min-w-0 gap-2">
            <div class="flex flex-row items-center gap-[6px] flex-1 min-w-0">
              <span class="whitespace-nowrap text-ellipsis overflow-hidden">
                {{ title }}
              </span>
            </div>
            <div class="flex items-center gap-2 flex-shrink-0">
              <!-- Recurring runs (Manus scheduleTask): let the agent run this
                   chat's work automatically on a schedule. -->
              <ScheduleDialog :sessionId="sessionId" />
              <span class="relative flex-shrink-0" aria-expanded="false" aria-haspopup="dialog">
                <Popover>
                  <PopoverTrigger>
                    <button
                      class="h-8 px-3 rounded-[100px] inline-flex items-center gap-1 clickable outline outline-1 outline-offset-[-1px] outline-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)] me-1.5">
                      <ShareIcon color="var(--icon-secondary)" />
                      <span class="text-[var(--text-secondary)] text-sm font-medium">{{ t('Share') }}</span>
                    </button>
                  </PopoverTrigger>
                  <PopoverContent>
                    <div
                      class="w-[400px] flex flex-col rounded-2xl bg-[var(--background-menu-white)] shadow-[0px_8px_32px_0px_var(--shadow-S),0px_0px_0px_1px_var(--border-light)]"
                      style="max-width: calc(-16px + 100vw);">
                      <div class="flex flex-col pt-[12px] px-[16px] pb-[16px]">
                        <!-- Private mode option -->
                        <div @click="handleShareModeChange('private')"
                          :class="{'pointer-events-none opacity-50': sharingLoading}"
                          class="flex items-center gap-[10px] px-[8px] -mx-[8px] py-[8px] rounded-[8px] clickable hover:bg-[var(--fill-tsp-white-main)]">
                          <div
                            :class="shareMode === 'private' ? 'bg-[var(--Button-primary-black)]' : 'bg-[var(--fill-tsp-white-dark)]'"
                            class="w-[32px] h-[32px] rounded-[8px] flex items-center justify-center">
                            <Lock :size="16" :stroke="shareMode === 'private' ? 'var(--text-onblack)' : 'var(--icon-primary)'" :stroke-width="2" /></div>
                          <div class="flex flex-col flex-1 min-w-0">
                            <div class="text-sm font-medium text-[var(--text-primary)]">{{ t('Private Only') }}</div>
                            <div class="text-[13px] text-[var(--text-tertiary)]">{{ t('Only visible to you') }}</div>
                          </div><Check :size="20" :class="shareMode === 'private' ? 'ml-auto' : 'ml-auto invisible'" :color="shareMode === 'private' ? 'var(--icon-primary)' : 'var(--icon-tertiary)'" />
                        </div>
                        <!-- Public mode option -->
                        <div @click="handleShareModeChange('public')"
                          :class="{'pointer-events-none opacity-50': sharingLoading}"
                          class="flex items-center gap-[10px] px-[8px] -mx-[8px] py-[8px] rounded-[8px] clickable hover:bg-[var(--fill-tsp-white-main)]">
                          <div
                            :class="shareMode === 'public' ? 'bg-[var(--Button-primary-black)]' : 'bg-[var(--fill-tsp-white-dark)]'"
                            class="w-[32px] h-[32px] rounded-[8px] flex items-center justify-center">
                            <Globe :size="16" :stroke="shareMode === 'public' ? 'var(--text-onblack)' : 'var(--icon-primary)'" :stroke-width="2" /></div>
                          <div class="flex flex-col flex-1 min-w-0">
                            <div class="text-sm font-medium text-[var(--text-primary)]">{{ t('Public Access') }}</div>
                            <div class="text-[13px] text-[var(--text-tertiary)]">{{ t('Anyone with the link can view') }}</div>
                          </div><Check :size="20" :class="shareMode === 'public' ? 'ml-auto' : 'ml-auto invisible'" :color="shareMode === 'public' ? 'var(--icon-primary)' : 'var(--icon-tertiary)'" />
                        </div>
                        <div class="border-t border-[var(--border-main)] mt-[4px]"></div>
                        
                        <!-- Show instant share button when in private mode -->
                        <div v-if="shareMode === 'private'">
                          <button @click.stop="handleInstantShare"
                            :disabled="sharingLoading"
                            class="inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-black)] text-[var(--text-onblack)] h-[36px] px-[12px] rounded-[10px] gap-[6px] text-sm min-w-16 mt-[16px] w-full disabled:opacity-50 disabled:cursor-not-allowed"
                            data-tabindex="" tabindex="-1">
                            <div v-if="sharingLoading" class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                            <Link v-else :size="16" stroke="currentColor" :stroke-width="2" />
                            {{ sharingLoading ? t('Sharing...') : t('Share Instantly') }}
                          </button>
                        </div>
                        
                        <!-- Show copy link button when in public mode -->
                        <div v-else>
                          <button @click.stop="handleCopyLink"
                            :class="linkCopied ? 'inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors active:opacity-80 bg-[var(--Button-primary-white)] text-[var(--text-primary)] hover:opacity-70 active:hover-60 h-[36px] px-[12px] rounded-[10px] gap-[6px] text-sm min-w-16 mt-[16px] w-full border border-[var(--border-btn-main)] shadow-none' : 'inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-black)] text-[var(--text-onblack)] h-[36px] px-[12px] rounded-[10px] gap-[6px] text-sm min-w-16 mt-[16px] w-full'"
                            data-tabindex="" tabindex="-1">
                            <Link v-if="!linkCopied" :size="16" stroke="currentColor" :stroke-width="2" />
                            <Check v-else :size="16" color="var(--text-primary)" />
                            {{ linkCopied ? t('Link Copied') : t('Copy Link') }}
                          </button>
                        </div>
                      </div>
                    </div>
                  </PopoverContent>
                </Popover>
              </span>
              <button @click="handleFileListShow"
                class="p-[5px] flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer">
                <FileSearch class="text-[var(--icon-secondary)]" :size="18" />
              </button>
            </div>
          </div>
          <div class="w-full flex justify-between items-center">
          </div>
        </div>
        <div class="flex-1"></div>
      </div>
      <div class="mx-auto w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] flex flex-col flex-1">
        <div class="flex flex-col w-full gap-[12px] pb-[80px] pt-[12px] flex-1 overflow-y-auto">
          <!-- Unified step timeline: consecutive step messages (plus their progress
               narrations) render as ONE connected block with a continuous rail,
               instead of one detached collapsible block per step. -->
          <template v-for="group in messageGroups" :key="group.startIndex">
            <StepTimeline v-if="group.kind === 'timeline'" :messages="group.messages"
              @toolClick="handleToolClick" />
            <ChatMessage v-else :message="group.messages[0]" :hideHeader="isGroupHideHeader(group)"
              @toolClick="handleToolClick" />
          </template>

          <!-- Validation card hidden per product decision (T38): the raw
               gate log (file paths, mechanical check details) read as
               unprofessional to end users. Component kept at
               src/components/ValidationCard.vue for easy re-enable. -->

          <!-- Post-task learning proposals (Manus knowledge loop): HIDDEN
               per product decision — the accept/reject card read as
               unprofessional to end users. Learnings are auto-accepted
               silently in the backend now. Component kept at
               src/components/KnowledgeCard.vue for easy re-enable. -->

          <!-- Loading indicator — hidden while streaming acknowledgment chunks -->
          <LoadingIndicator v-if="isLoading && !streamingMessageContent" :text="currentThinkingText || $t('Thinking')" />
          <!-- Wait indicator — agent is expecting user input -->
          <div v-if="isWaitingForInput && !isLoading"
            class="flex items-center gap-2 px-4 py-2 mx-auto rounded-xl text-sm text-[var(--text-secondary)] bg-[var(--fill-tsp-white-main)] border border-[var(--border-main)] w-fit">
            <span class="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
            {{ $t('Agent is waiting for your response') }}
          </div>
        </div>

        <div class="flex flex-col bg-[var(--background-gray-main)] sticky bottom-0">
          <button @click="handleFollow" v-if="!follow"
            class="flex items-center justify-center w-[36px] h-[36px] rounded-full bg-[var(--background-white-main)] hover:bg-[var(--background-gray-main)] clickable border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-S)] absolute -top-20 left-1/2 -translate-x-1/2">
            <ArrowDown class="text-[var(--icon-primary)]" :size="20" />
          </button>
          <PlanPanel v-if="plan && plan.steps.length > 0" :plan="plan" @close="plan = undefined" />
          <ChatBox v-model="inputMessage" :rows="1" @submit="handleSubmit" :isRunning="isLoading" @stop="handleStop"
            :attachments="attachments" />
        </div>
      </div>
    </div>
    <ToolPanel ref="toolPanel" :allTools="allTools" :sessionId="sessionId" :realTime="realTime"
      :isShare="false"
      @jumpToRealTime="jumpToRealTime" />
  </SimpleBar>
</template>

<script setup lang="ts">
import SimpleBar from '../components/SimpleBar.vue';
import { ref, onMounted, watch, nextTick, onUnmounted, reactive, toRefs, computed } from 'vue';
import { useRouter, onBeforeRouteUpdate } from 'vue-router';
import { useI18n } from 'vue-i18n';
import ChatBox from '../components/ChatBox.vue';
import ChatMessage from '../components/ChatMessage.vue';
import ScheduleDialog from '../components/ScheduleDialog.vue';
import StepTimeline from '../components/StepTimeline.vue';
import * as agentApi from '../api/agent';
import { Message, MessageContent, ToolContent, StepContent, AttachmentsContent } from '../types/message';
import {
  StepEventData,
  ToolEventData,
  MessageEventData,
  MessageChunkEventData,
  ErrorEventData,
  TitleEventData,
  PlanEventData,
  AgentSSEEvent,
} from '../types/event';
import ToolPanel from '../components/ToolPanel.vue'
import { TOOL_FUNCTION_MAP } from '../constants/tool'
import PlanPanel from '../components/PlanPanel.vue';
import { ArrowDown, FileSearch, PanelLeft, Lock, Globe, Link, Check } from 'lucide-vue-next';
import ShareIcon from '@/components/icons/ShareIcon.vue';
import { showErrorToast, showSuccessToast } from '../utils/toast';
import type { FileInfo } from '../api/file';
import { useLeftPanel } from '../composables/useLeftPanel'
import { useSessionFileList } from '../composables/useSessionFileList'
import { useFilePanel } from '../composables/useFilePanel'
import { copyToClipboard } from '../utils/dom'
import { SessionStatus } from '../types/response';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import LoadingIndicator from '@/components/ui/LoadingIndicator.vue';

const router = useRouter()
const { t } = useI18n()
const { toggleLeftPanel, isLeftPanelShow } = useLeftPanel()
const { showSessionFileList } = useSessionFileList()
const { hideFilePanel } = useFilePanel()

// Create initial state factory
const createInitialState = () => ({
  inputMessage: '',
  isLoading: false,
  isWaitingForInput: false,
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
  cancelCurrentChat: null as (() => void) | null,
  streamingMessageContent: null as MessageContent | null,
  currentThinkingText: null as string | null,
  attachments: [] as FileInfo[],
  shareMode: 'private' as 'private' | 'public', // Default to private mode
  linkCopied: false,
  sharingLoading: false, // Loading state for share operations
});

// Create reactive state
const state = reactive(createInitialState());

// Destructure refs from reactive state
const {
  inputMessage,
  isLoading,
  isWaitingForInput,
  sessionId,
  messages,
  realTime,
  follow,
  title,
  plan,
  lastNoMessageTool,
  lastTool,
  lastEventId,
  cancelCurrentChat,
  streamingMessageContent,
  currentThinkingText,
  attachments,
  shareMode,
  linkCopied,
  sharingLoading,
} = toRefs(state);

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

// ── Message grouping ────────────────────────────────────────────────────────────
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
  const groups: MessageGroup[] = []
  const msgs = messages.value
  let timeline: MessageGroup | null = null
  // A message renders as an assistant bubble (with the Dzeck avatar header)
  // when it stands alone — narrations absorbed into a timeline do NOT count:
  // they render inside the timeline rail, invisible to header suppression.
  const isAssistantBubble = (m: Message) =>
    m.type === 'assistant' ||
    (m.type === 'attachments' && (m.content as AttachmentsContent).role === 'assistant')
  const pushSingle = (m: Message, i: number) => {
    const prev = groups.length ? groups[groups.length - 1] : null
    const prevIsAssistantBubble = !!(
      prev && prev.kind === 'single' && isAssistantBubble(prev.messages[0])
    )
    groups.push({
      kind: 'single',
      messages: [m],
      startIndex: i,
      hideHeader: isAssistantBubble(m) && prevIsAssistantBubble,
    })
  }
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i]
    if (m.type === 'step') {
      if (timeline) {
        timeline.messages.push(m)
      } else {
        timeline = { kind: 'timeline', messages: [m], startIndex: i }
        groups.push(timeline)
      }
      continue
    }
    if (m.type === 'assistant') {
      const mc = m.content as MessageContent
      if (mc.is_final || mc.is_question) {
        // Summary / question — standalone, ends the timeline. It always gets
        // its own avatar header (Manus-style): the narration lines before it
        // rendered INSIDE the timeline, not as an assistant bubble.
        pushSingle(m, i)
        timeline = null
      } else if (timeline) {
        // Mid-task narration → inside the timeline, beside the rail.
        timeline.messages.push(m)
      } else {
        // Ack / pre-plan text — standalone (no timeline started yet).
        pushSingle(m, i)
      }
      continue
    }
    // user / tool / attachments — standalone, timeline ends.
    pushSingle(m, i)
    timeline = null
  }
  return groups
})

// Consecutive-assistant header suppression, evaluated on RENDERED groups:
// the header is hidden only when the previous rendered group is itself a
// standalone assistant bubble (message + attachments pair, back-to-back
// standalone texts). A summary following the tool timeline always keeps
// its Dzeck avatar header — exactly like Manus.
const isGroupHideHeader = (group: MessageGroup): boolean => {
  if (group.kind !== 'single') return false
  return !!group.hideHeader
}

// Non-state refs that don't need reset
const toolPanel = ref<InstanceType<typeof ToolPanel>>()
const simpleBarRef = ref<InstanceType<typeof SimpleBar>>();
const observerRef = ref<HTMLDivElement>();
const chatContainerRef = ref<HTMLDivElement>();

// Reset all refs to their initial values
const resetState = () => {
  // Cancel any existing chat connection
  if (cancelCurrentChat.value) {
    cancelCurrentChat.value();
  }
  // Drop any pending streaming chunk buffer from the previous session
  _cancelChunkTimer();
  _chunkBuffer = '';
  _lastFlushAt = 0;

  // Reset reactive state to initial values
  Object.assign(state, createInitialState());
};

// RAF-debounced scroll — called after chunk flushes, not on every token
let scrollRafId: number | null = null;
const scheduleScroll = () => {
  if (scrollRafId !== null) return;
  scrollRafId = requestAnimationFrame(() => {
    scrollRafId = null;
    if (follow.value) simpleBarRef.value?.scrollToBottom();
  });
};

// Watch only for structural message array changes (new messages added),
// not deep mutations. Streaming content changes are handled by scheduleScroll.
watch(() => messages.value.length, async () => {
  await nextTick();
  if (follow.value) simpleBarRef.value?.scrollToBottom();
});



// Index of the last user message — steps of the CURRENT run only exist after
// it. Step ids restart at "1" for every new task in the same session, so a
// global id lookup would morph the previous task's step rows instead of
// stacking a new step group (seen live: second task reused old steps).
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

// Chunk buffer — accumulates tokens between throttled flushes.
// Previously flushed on EVERY animation frame (~60/s): each flush re-parsed
// the FULL accumulated markdown (measured 23.8ms/flush at 10KB on desktop —
// already over the 16.7ms frame budget, ~4-6× that on phone) and rebuilt the
// whole v-html DOM subtree, making long streaming replies freeze the page.
// Flushing at most every ~180ms (≈5.5 fps) cuts that CPU by ~12× while the
// text still appears to type smoothly.
const CHUNK_FLUSH_MS = 180;
let _chunkBuffer = '';
let _chunkTimer: ReturnType<typeof setTimeout> | null = null;
let _lastFlushAt = 0;

const _flushChunkBuffer = () => {
  _chunkTimer = null;
  _lastFlushAt = Date.now();
  if (_chunkBuffer && streamingMessageContent.value) {
    streamingMessageContent.value.content += _chunkBuffer;
    _chunkBuffer = '';
    scheduleScroll();
  }
};

const _cancelChunkTimer = () => {
  if (_chunkTimer !== null) {
    clearTimeout(_chunkTimer);
    _chunkTimer = null;
  }
};

// Handle streaming message chunk event
const handleMessageChunkEvent = (chunkData: MessageChunkEventData) => {
  if (!streamingMessageContent.value) {
    // First chunk — push a new assistant message and hold a reference to its content
    const content: MessageContent = {
      content: chunkData.content,
      timestamp: chunkData.timestamp,
      isStreaming: true,
    };
    messages.value.push({
      type: 'assistant',
      content,
    });
    streamingMessageContent.value = content;
    scheduleScroll();
    return;
  }

  if (chunkData.done) {
    // Flush any remaining buffered text immediately
    _cancelChunkTimer();
    if (_chunkBuffer && streamingMessageContent.value) {
      streamingMessageContent.value.content += _chunkBuffer;
      _chunkBuffer = '';
    }
    // Mark streaming done so ChatMessage switches to full markdown render
    if (streamingMessageContent.value) {
      (streamingMessageContent.value as any).isStreaming = false;
    }
    streamingMessageContent.value = null;
    scheduleScroll();
    return;
  }

  // Buffer the incoming token and flush on the next throttle window
  _chunkBuffer += chunkData.content;
  if (_chunkTimer === null) {
    const wait = Math.max(0, CHUNK_FLUSH_MS - (Date.now() - _lastFlushAt));
    _chunkTimer = setTimeout(_flushChunkBuffer, wait);
  }
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
  // (beside the rail) no matter whether a step is currently running. This is
  // what keeps the Manus-style work loop continuous — a notify fired between
  // two steps can never break the timeline apart again. The CALLED event
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
      scheduleScroll()
    }
    return
  }

  // Update thinking text: show current action while calling, reset to null when done
  // Official Manus: the model-supplied ``brief`` (natural-language action)
  // takes priority over the generic function label.
  if (toolData.status === 'calling') {
    currentThinkingText.value = (toolData as any).brief?.trim()
      || t(TOOL_FUNCTION_MAP[toolData.function] || toolData.function);
  } else {
    currentThinkingText.value = null;
  }

  const lastStep = getLastStep();
  let toolContent: ToolContent = {
    ...toolData
  }
  if (lastTool.value && lastTool.value.tool_call_id === toolContent.tool_call_id) {
    Object.assign(lastTool.value, toolContent);
  } else {
    if (lastStep) {
      // Attach to the last step EVEN WHEN COMPLETED — tools that arrive after
      // a step's final JSON (late file writes, delivery syncs fired at step
      // completion) still belong to that step's work. Rendering them as
      // detached tool messages would break the continuous timeline rail.
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
    // Do NOT auto-open the tool panel — user opens it manually by clicking a tool
  }
}

// Sync a step's status into plan.value.steps so PlanPanel stays up-to-date.
// Uses positional matching (first-pending / first-running) instead of ID matching
// because the planner LLM may regenerate step IDs after each plan update.
const syncStepToPlan = (status: string) => {
  if (!plan.value) return;
  if (status === 'running') {
    // Mark the first pending step as running
    const pendingStep = plan.value.steps.find(s => s.status === 'pending');
    if (pendingStep) pendingStep.status = 'running';
  } else if (status === 'completed') {
    // Mark the first running step as completed
    const runningStep = plan.value.steps.find(s => s.status === 'running');
    if (runningStep) runningStep.status = 'completed';
  } else if (status === 'failed') {
    // Mark the first running step as failed
    const runningStep = plan.value.steps.find(s => s.status === 'running');
    if (runningStep) runningStep.status = 'failed';
  }
}

// Handle step event — official semantics (useAgentEvents):
// • running/pending → ensure the step message exists (pending renders running)
// • completed/failed → update the MATCHED step (by id, fallback last) with
//   status + description + result (the outcome text shown under the StepGroup)
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

const ensureStepMessage = (stepData: StepEventData) => {
  const existing = findStepById(stepData.id);
  if (existing) {
    existing.status = stepData.status;
    existing.description = stepData.description || existing.description;
    if (stepData.result) existing.result = stepData.result;
    return existing;
  }
  if (stepData.status !== 'running' && stepData.status !== 'pending') {
    return undefined;
  }
  const content = {
    ...stepData,
    status: stepData.status === 'pending' ? 'running' : stepData.status,
    tools: [],
  } as StepContent;
  messages.value.push({ type: 'step', content });
  return content;
};

const handleStepEvent = (stepData: StepEventData) => {
  if (stepData.status === 'running' || stepData.status === 'pending') {
    ensureStepMessage(stepData);
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

// ── Post-task learning proposals (Manus knowledge loop) ─────────────
// Product decision: lessons are auto-accepted silently in the backend
// (status ACTIVE, no KnowledgeEvent emitted) — the chat never renders an
// accept/reject card. Incoming 'knowledge' events (only possible from
// sessions recorded BEFORE this change) are ignored on purpose.

// Main event handler function
const handleEvent = (event: AgentSSEEvent) => {
  if (event.event === 'message') {
    // The MessageEvent is the authoritative, persisted form of this response.
    // Remove any streaming bubble that preceded it — whether still in progress
    // or just completed (done=true already received) — to prevent double-bubble.
    if (streamingMessageContent.value) {
      // Stream still active — drop the partial bubble before replacing.
      const lastIdx = messages.value.length - 1;
      if (lastIdx >= 0 && messages.value[lastIdx].type === 'assistant') {
        messages.value.splice(lastIdx, 1);
      }
      streamingMessageContent.value = null;
    } else if (messages.value.length > 0) {
      // Stream already completed (done=true received). The bubble is still in
      // messages with isStreaming=false; remove it so MessageEvent takes its place.
      const last = messages.value[messages.value.length - 1];
      if (last.type === 'assistant' && 'isStreaming' in (last.content as any)) {
        messages.value.splice(messages.value.length - 1, 1);
      }
    }
    handleMessageEvent(event.data as MessageEventData);
  } else if (event.event === 'message_chunk') {
    handleMessageChunkEvent(event.data as MessageChunkEventData);
  } else if (event.event === 'tool') {
    handleToolEvent(event.data as ToolEventData);
  } else if (event.event === 'step') {
    handleStepEvent(event.data as StepEventData);
  } else if (event.event === 'done') {
    //isLoading.value = false;
  } else if (event.event === 'wait') {
    isLoading.value = false;
    isWaitingForInput.value = true;
  } else if (event.event === 'error') {
    handleErrorEvent(event.data as ErrorEventData);
  } else if (event.event === 'title') {
    handleTitleEvent(event.data as TitleEventData);
  } else if (event.event === 'plan') {
    handlePlanEvent(event.data as PlanEventData);
  }
  // 'knowledge' events are intentionally ignored — lessons are
  // auto-accepted in the backend and never shown in the chat.
  lastEventId.value = event.data.event_id;
}

const handleSubmit = () => {
  chat(inputMessage.value, attachments.value);
}

const chat = async (message: string = '', files: FileInfo[] = []) => {
  if (!sessionId.value) return;

  // Cancel any existing chat connection before starting a new one
  if (cancelCurrentChat.value) {
    cancelCurrentChat.value();
    cancelCurrentChat.value = null;
  }

  if (message.trim()) {
    // Add user message to conversation list
    messages.value.push({
      type: 'user',
      content: {
        content: message,
        timestamp: Math.floor(Date.now() / 1000)
      } as MessageContent,
    });
  }

  if (files.length > 0) {
    messages.value.push({
      type: 'attachments',
      content: {
        role: 'user',
        attachments: files
      } as AttachmentsContent,
    });
  }

  // Automatically enable follow mode when sending message
  follow.value = true;

  // Clear input field and attachments
  inputMessage.value = '';
  attachments.value = [];
  isLoading.value = true;
  isWaitingForInput.value = false;

  try {
    // Use the split event handler function and store the cancel function
    cancelCurrentChat.value = await agentApi.chatWithSession(
      sessionId.value,
      message,
      lastEventId.value,
      files.map((file: FileInfo) => ({
        file_id: file.file_id,
        filename: file.filename,
        content_type: file.content_type,
        size: file.size,
      })),
      {
        onOpen: () => {
          console.log('Chat opened');
          isLoading.value = true;
        },
        onMessage: ({ event, data }) => {
          handleEvent({
            event: event as AgentSSEEvent['event'],
            data: data as AgentSSEEvent['data']
          });
        },
        onClose: () => {
          console.log('Chat closed');
          isLoading.value = false;
          // Clear the cancel function when connection is closed normally
          if (cancelCurrentChat.value) {
            cancelCurrentChat.value = null;
          }
        },
        onError: (error) => {
          console.error('Chat error:', error);
          isLoading.value = false;
          // Clear the cancel function when there's an error
          if (cancelCurrentChat.value) {
            cancelCurrentChat.value = null;
          }
        }
      }
    );
  } catch (error) {
    console.error('Chat error:', error);
    isLoading.value = false;
    cancelCurrentChat.value = null;
  }
}

const restoreSession = async () => {
  if (!sessionId.value) {
    showErrorToast(t('Session not found'));
    return;
  }
  const session = await agentApi.getSession(sessionId.value);
  // Initialize share mode based on session state
  shareMode.value = session.is_shared ? 'public' : 'private';
  realTime.value = false;
  for (const event of session.events) {
    handleEvent(event);
  }
  realTime.value = true;
  if (
    session.status === SessionStatus.RUNNING ||
    session.status === SessionStatus.PENDING ||
    session.status === SessionStatus.IN_QUEUE
  ) {
    await chat();
  }
  agentApi.clearUnreadMessageCount(sessionId.value);
}



onBeforeRouteUpdate((to, _, next) => {
  toolPanel.value?.hideToolPanel();
  hideFilePanel();
  resetState();
  if (to.params.sessionId) {
    messages.value = [];
    sessionId.value = String(to.params.sessionId) as string;
    restoreSession();
  }
  next();
})

// Initialize active conversation
onMounted(() => {
  hideFilePanel();
  const routeParams = router.currentRoute.value.params;
  if (routeParams.sessionId) {
    // If sessionId is included in URL, use it directly
    sessionId.value = String(routeParams.sessionId) as string;
    // Get initial message from history.state
    const message = history.state?.message;
    const files: FileInfo[] = history.state?.files;
    history.replaceState({}, document.title);
    if (message) {
      chat(message, files);
    } else {
      restoreSession();
    }
  }


});

onUnmounted(() => {
  _cancelChunkTimer();
  if (scrollRafId !== null) {
    cancelAnimationFrame(scrollRafId);
    scrollRafId = null;
  }
  if (cancelCurrentChat.value) {
    cancelCurrentChat.value();
    cancelCurrentChat.value = null;
  }
})

const isLastNoMessageTool = (tool: ToolContent) => {
  return tool.tool_call_id === lastNoMessageTool.value?.tool_call_id;
}

const isLiveTool = (tool: ToolContent) => {
  if (tool.status === 'calling') {
    return true;
  }
  if (!isLastNoMessageTool(tool)) {
    return false;
  }
  if (tool.timestamp > Date.now() - 5 * 60 * 1000) {
    return true;
  }
  return false;
}

const handleToolClick = (tool: ToolContent) => {
  realTime.value = false;
  if (sessionId.value) {
    toolPanel.value?.showToolPanel(tool, isLiveTool(tool));
  }
}

const jumpToRealTime = () => {
  realTime.value = true;
  if (lastNoMessageTool.value) {
    toolPanel.value?.showToolPanel(lastNoMessageTool.value, isLiveTool(lastNoMessageTool.value));
  }
}

const handleFollow = () => {
  follow.value = true;
  simpleBarRef.value?.scrollToBottom();
}

const handleScroll = (_: Event) => {
  follow.value = simpleBarRef.value?.isScrolledToBottom() ?? false;
}

const handleStop = () => {
  if (sessionId.value) {
    agentApi.stopSession(sessionId.value);
  }
}

const handleFileListShow = () => {
  showSessionFileList()
}

// Share functionality handlers
const handleShareModeChange = async (mode: 'private' | 'public') => {
  if (!sessionId.value || sharingLoading.value) return;
  
  // If mode is same as current, no need to call API
  if (shareMode.value === mode) {
    linkCopied.value = false;
    return;
  }
  
  try {
    sharingLoading.value = true;
    
    if (mode === 'public') {
      await agentApi.shareSession(sessionId.value);
    } else {
      await agentApi.unshareSession(sessionId.value);
    }
    
    shareMode.value = mode;
    linkCopied.value = false;
  } catch (error) {
    console.error('Error changing share mode:', error);
    showErrorToast(t('Failed to change sharing settings'));
  } finally {
    sharingLoading.value = false;
  }
}

const handleInstantShare = async () => {
  if (!sessionId.value) return;
  
  try {
    sharingLoading.value = true;
    await agentApi.shareSession(sessionId.value);
    shareMode.value = 'public';
    linkCopied.value = false;
  } catch (error) {
    console.error('Error sharing session:', error);
    showErrorToast(t('Failed to share session'));
  } finally {
    sharingLoading.value = false;
  }
}

const handleCopyLink = async () => {
  if (!sessionId.value) return;
  
  const shareUrl = `${window.location.origin}/share/${sessionId.value}`;
  
  try {
    const success = await copyToClipboard(shareUrl);
    
    if (success) {
      linkCopied.value = true;
      setTimeout(() => {
        linkCopied.value = false;
      }, 3000);
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

<style scoped>
</style>
