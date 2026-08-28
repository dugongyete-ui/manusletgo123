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
          <div class="flex items-center sm:gap-3"><button @click="handleCopyLink"
              class="p-2 flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer">
              <Link class="text-[var(--icon-secondary)]" :size="20" />
            </button><button @click="handleFileListShow"
              class="p-2 flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer">
              <FileSearch class="text-[var(--icon-secondary)]" :size="20" />
            </button>
          </div>
        </div>
      </header>
      <div class="mx-auto w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] flex flex-col flex-1">
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

          <!-- Loading indicator -->
          <LoadingIndicator v-if="isLoading" :text="$t('Thinking')" />
        </div>

        <div class="sticky bottom-0 max-w-[800px] mx-auto w-full pb-3 flex flex-col gap-2 px-3 pt-2.5 sm:pt-0">
          <button @click="handleFollow" v-if="!follow"
            class="flex items-center justify-center w-[36px] h-[36px] rounded-full bg-[var(--background-white-main)] hover:bg-[var(--background-gray-main)] clickable border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-S)] absolute -top-20 left-1/2 -translate-x-1/2">
            <ArrowDown class="text-[var(--icon-primary)]" :size="20" />
          </button>
          <PlanPanel v-if="plan && plan.steps.length > 0" :plan="plan" @close="plan = undefined" />
          <div
            class="bg-[var(--background-white-main)] rounded-xl border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-XS)] backdrop-blur-3xl flex items-center justify-between py-[9px] pr-3 pl-4 sm:flex-row flex-col max-sm:gap-3 max-sm:p-2">
            <div class="flex items-center gap-0.5 w-full sm:flex-1">
              <div class="w-6 h-6"><DzeckLogoMark :size="24" /></div>
              <div>
                <p class="text-sm text-[var(--text-primary)]">{{ replayCompleted ? $t('Dzeck task replay completed.') : $t('Dzeck is replaying the task...') }}</p>
              </div>
            </div>
            <div class="flex items-center flex-row gap-[8px] max-sm:w-full">
              <button @click="replayCompleted ? replay() : (jumpToEnd = true)"
                class="inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-brand)] text-[var(--text-white)] h-[36px] rounded-[10px] gap-[6px] text-sm min-w-16 px-[14px] py-[6px] max-sm:w-1/2"><span
                  class="text-sm">{{ replayCompleted ? $t('Replay') : $t('Jump to results') }}</span></button>
            </div>
          </div>
        </div>

      </div>
    </div>

    <div v-if="showReplayOverlay"
      class="fixed bottom-0 left-0 right-0 h-[calc(100vh - 156px)] z-50 flex items-center justify-center"
      style="height: calc(-156px + 100vh); background: linear-gradient(rgba(255, 255, 255, 0) 5.99%, rgb(255, 255, 255) 35.84%);">
      <div class="flex flex-col items-center gap-4 p-2.5">
        <button @click="startReplay"
          class="flex items-center justify-center rounded-full bg-[var(--Button-primary-black)] p-3 clickable animate-pulse hover:opacity-85">
          <svg height="24" width="24" fill="none" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M17.5 10C17.5 11.4834 17.0601 12.9334 16.236 14.1668C15.4119 15.4001 14.2406 16.3614 12.8701 16.9291C11.4997 17.4968 9.99168 17.6453 8.53683 17.3559C7.08197 17.0665 5.7456 16.3522 4.6967 15.3033C3.64781 14.2544 2.9335 12.918 2.64411 11.4632C2.35472 10.0083 2.50325 8.50032 3.07091 7.12987C3.63856 5.75943 4.59986 4.58809 5.83323 3.76398C7.0666 2.93987 8.51664 2.5 10 2.5C12.1 2.5 14.1083 3.33333 15.6167 4.78333L17.5 6.66667"
              stroke="var(--text-onblack)" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.66667"></path>
            <path d="M17.5007 2.5V6.66667H13.334" stroke="var(--text-onblack)" stroke-linecap="round"
              stroke-linejoin="round" stroke-width="1.66667"></path>
            <path
              d="M12.5419 9.37138C13.0259 9.65082 13.0259 10.3494 12.5419 10.6289L9.27486 12.5151C8.79086 12.7945 8.18586 12.4452 8.18586 11.8863L8.18586 8.11391C8.18586 7.55504 8.79086 7.20574 9.27486 7.48518L12.5419 9.37138Z"
              fill="var(--text-onblack)"></path>
          </svg>
        </button>
        <div class="text-center text-[var(--text-primary)] whitespace-pre-line"
          v-html="$t('You are viewing a completed Dzeck task. Replay will start automatically in {countdown} seconds.', { countdown: `<strong>${countdown}</strong>` })">
        </div>
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
import * as agentApi from '../api/agent';
import { Message, MessageContent, ToolContent, StepContent, AttachmentsContent } from '../types/message';
import {
  StepEventData,
  ToolEventData,
  MessageEventData,
  ErrorEventData,
  TitleEventData,
  PlanEventData,
  AgentSSEEvent,
} from '../types/event';
import ToolPanel from '../components/ToolPanel.vue'
import PlanPanel from '../components/PlanPanel.vue';
import { ArrowDown, FileSearch, Link } from 'lucide-vue-next';
import DzeckLogoTextIcon from '../components/icons/DzeckLogoTextIcon.vue';
import DzeckLogoMark from '../components/icons/DzeckLogoMark.vue';
import { showErrorToast, showSuccessToast } from '../utils/toast';
import type { FileInfo } from '../api/file';
import { useSessionFileList } from '../composables/useSessionFileList'
import { useFilePanel } from '../composables/useFilePanel'
import LoadingIndicator from '@/components/ui/LoadingIndicator.vue';
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
  showReplayOverlay: false,
  countdown: 3,
  jumpToEnd: false,
  replayCompleted: false,
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
  showReplayOverlay,
  countdown,
  jumpToEnd,
  replayCompleted,
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

// Non-state refs that don't need reset
const toolPanel = ref<InstanceType<typeof ToolPanel>>()
const simpleBarRef = ref<InstanceType<typeof SimpleBar>>();
let countdownTimer: number | null = null;

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
      // Every assistant message — ack, narration, question, summary — renders
      // as a standalone chat bubble (official chat flow). It ends the current
      // step group so the next step starts a fresh StepGroup shell.
      pushSingle(m, i);
      timeline = null;
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

const getLastStep = (): StepContent | undefined => {
  return messages.value.filter(message => message.type === 'step').pop()?.content as StepContent;
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
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const message = messages.value[i];
    if (message.type !== 'step') continue;
    const step = message.content as StepContent;
    if (step.id === id) return step;
  }
  return undefined;
};

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
  } else if (stepData.status === 'completed') {
    const matched = findStepById(stepData.id) ?? getLastStep();
    if (matched) {
      matched.status = stepData.status;
      if (stepData.description) matched.description = stepData.description;
      if (stepData.result) matched.result = stepData.result;
    }
  } else if (stepData.status === 'failed') {
    const matched = findStepById(stepData.id) ?? getLastStep();
    if (matched) {
      matched.status = stepData.status;
      if (stepData.description) matched.description = stepData.description;
      if (stepData.result) matched.result = stepData.result;
    }
    isLoading.value = false;
  }
}

// Handle error event
const handleErrorEvent = (errorData: ErrorEventData) => {
  isLoading.value = false;
  messages.value.push({
    type: 'assistant',
    content: {
      content: errorData.error,
      timestamp: errorData.timestamp
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
  }
  lastEventId.value = event.data.event_id;
}

// Reset all refs to their initial values
const resetState = () => {
  // Reset reactive state to initial values
  Object.assign(state, createInitialState());
};

const replay = async () => {
  if (!sessionId.value) {
    showErrorToast(t('Session not found'));
    return;
  }
  hideFilePanel();
  toolPanel.value?.hideToolPanel();
  resetState();
  sessionId.value = String(router.currentRoute.value.params.sessionId) as string;
  const session = await agentApi.getSharedSession(sessionId.value);
  realTime.value = true;
  isLoading.value = true;
  for (const event of session.events) {
    if (!jumpToEnd.value) {
      await new Promise(resolve => setTimeout(resolve, 300));
    }
    handleEvent(event);
  }
  isLoading.value = false;
  replayCompleted.value = true;
}

const restoreSession = async () => {
  if (!sessionId.value) {
    showErrorToast(t('Session not found'));
    return;
  }
  const session = await agentApi.getSharedSession(sessionId.value);
  realTime.value = false;
  follow.value = false; // Prevent auto-scrolling during restoration
  for (const event of session.events) {
    handleEvent(event);
  }
  realTime.value = true;
}

// Start countdown timer
const startCountdown = () => {
  if (countdownTimer) {
    clearInterval(countdownTimer);
  }

  countdown.value = 3;
  countdownTimer = window.setInterval(() => {
    countdown.value--;
    if (countdown.value <= 0) {
      startReplay();
    }
  }, 1000);
}

// Start replay (hide overlay and clear timer)
const startReplay = () => {
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
  showReplayOverlay.value = false;
  replay();
}

// Initialize active conversation
onMounted(() => {
  hideFilePanel();
  const routeParams = router.currentRoute.value.params;
  if (routeParams.sessionId) {
    // If sessionId is included in URL, use it directly
    sessionId.value = String(routeParams.sessionId) as string;
    restoreSession();

    // Show replay overlay and start countdown after session is restored
    showReplayOverlay.value = true;
    startCountdown();
  }
});

// Clean up timer on unmount
onUnmounted(() => {
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
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
