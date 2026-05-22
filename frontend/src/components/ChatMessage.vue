<template>
  <div v-if="message.type === 'user'" class="flex w-full flex-col items-end justify-end gap-1 group mt-3">
    <div class="flex items-end">
      <div class="flex items-center justify-end gap-[2px] invisible group-hover:visible">
        <div class="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
          {{ relativeTime(message.content.timestamp) }}
        </div>
      </div>
    </div>
    <div class="flex max-w-[90%] relative flex-col gap-2 items-end">
      <div
        class="relative flex items-center rounded-[12px] overflow-hidden bg-[var(--fill-white)] dark:bg-[var(--fill-tsp-white-main)] p-3 ltr:rounded-br-none rtl:rounded-bl-none border border-[var(--border-main)] dark:border-0"
        v-html="renderMarkdown(messageContent.content)">
      </div>
    </div>
  </div>
  <div v-else-if="message.type === 'assistant'" class="flex flex-col gap-2 w-full group" :class="hideAssistantHeader ? 'mt-0' : 'mt-3'">
    <div v-if="!hideAssistantHeader" class="flex items-center justify-between h-7 group">
      <div class="flex items-center gap-[3px]">
        <component v-if="assistantIcon" :is="assistantIcon" :size="24" class="w-6 h-6" />
        <Bot v-else :size="24" class="w-6 h-6" />
        <span v-if="assistantName" class="text-base text-[var(--text-primary)] tracking-tight leading-none ml-0.5">{{ assistantName }}</span>
        <ManusTextIcon v-else-if="!assistantIcon" />
      </div>
      <div class="flex items-center gap-[2px] invisible group-hover:visible">
        <div class="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
          {{ relativeTime(message.content.timestamp) }}
        </div>
      </div>
    </div>
    <div
      class="max-w-none p-0 m-0 prose prose-sm sm:prose-base dark:prose-invert [&_pre:not(.shiki)]:!bg-[var(--fill-tsp-white-light)] [&_pre:not(.shiki)]:text-[var(--text-primary)] text-base text-[var(--text-primary)]"
      v-html="renderMarkdown(messageContent.content)"
      @click="handleMarkdownClick"></div>
  </div>
  <ToolUse v-else-if="message.type === 'tool'" :tool="toolContent" @click="handleToolClick(toolContent)" />
  <div v-else-if="message.type === 'step'" class="flex flex-col">
    <div class="text-sm w-full clickable flex gap-2 justify-between group/header truncate text-[var(--text-primary)]"
      data-event-id="HNtP7XOMUOhPemItd2EkK2">
      <div class="flex flex-row gap-2 justify-center items-center truncate">
        <div v-if="stepContent.status !== 'completed'"
          class="w-4 h-4 flex-shrink-0 flex items-center justify-center border border-[var(--border-dark)] rounded-[15px]">
        </div>
        <div v-else
          class="w-4 h-4 flex-shrink-0 flex items-center justify-center border-[var(--border-dark)] rounded-[15px] bg-[var(--text-disable)] dark:bg-[var(--fill-tsp-white-dark)] border-0">
          <CheckIcon class="text-[var(--icon-white)] dark:text-[var(--icon-white-tsp)]" :size="10" />
        </div>
        <div class="truncate font-medium markdown-content"
          v-html="stepContent.description ? renderMarkdown(stepContent.description) : ''">
        </div>
        <span class="flex-shrink-0 flex" @click="isExpanded = !isExpanded;">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            class="lucide lucide-chevron-down transition-transform duration-300 w-4 h-4"
            :class="{ 'rotate-180': isExpanded }">
            <path d="m6 9 6 6 6-6"></path>
          </svg>
        </span>
      </div>
      <div class="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover/header:visible">
        {{ relativeTime(message.content.timestamp) }}
      </div>
    </div>
    <div class="flex">
      <div class="w-[24px] relative">
        <div class="border-l border-dashed border-[var(--border-dark)] absolute start-[8px] top-0 bottom-0"
          style="height: calc(100% + 14px);"></div>
      </div>
      <div
        class="flex flex-col gap-3 flex-1 min-w-0 overflow-hidden pt-2 transition-[max-height,opacity] duration-150 ease-in-out"
        :class="{ 'max-h-[100000px] opacity-100': isExpanded, 'max-h-0 opacity-0': !isExpanded }">
        <ToolUse v-for="(tool, index) in stepContent.tools" :key="index" :tool="tool" @click="handleToolClick(tool)" />
      </div>
    </div>
  </div>
  <div v-else-if="message.type === 'attachments' && attachmentsContent.role === 'assistant'" class="flex flex-col gap-2 w-full group" :class="hideAssistantHeader ? 'mt-0' : 'mt-3'">
    <div v-if="!hideAssistantHeader" class="flex items-center justify-between h-7 group">
      <div class="flex items-center gap-[3px]">
        <component v-if="assistantIcon" :is="assistantIcon" :size="24" class="w-6 h-6" />
        <Bot v-else :size="24" class="w-6 h-6" />
        <span v-if="assistantName" class="text-base text-[var(--text-primary)] tracking-tight leading-none ml-0.5">{{ assistantName }}</span>
        <ManusTextIcon v-else-if="!assistantIcon" />
      </div>
      <div class="flex items-center gap-[2px] invisible group-hover:visible">
        <div class="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
          {{ relativeTime(attachmentsContent.timestamp) }}
        </div>
      </div>
    </div>
    <AttachmentsMessage :content="attachmentsContent" :hideAllFilesButton="hideAllFilesButton"/>
  </div>
  <AttachmentsMessage v-else-if="message.type === 'attachments'" :content="attachmentsContent" :hideAllFilesButton="hideAllFilesButton"/>
</template>

<script setup lang="ts">
import ManusTextIcon from './icons/ManusTextIcon.vue';
import { Message, MessageContent, AttachmentsContent } from '../types/message';
import ToolUse from './ToolUse.vue';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { CheckIcon } from 'lucide-vue-next';
import { computed, ref, type Component } from 'vue';
import { ToolContent, StepContent } from '../types/message';
import { useRelativeTime } from '../composables/useTime';
import { Bot } from 'lucide-vue-next';
import AttachmentsMessage from './AttachmentsMessage.vue';
import { viewFile } from '../api/agent';


const props = defineProps<{
  message: Message;
  sessionId?: string;
  assistantIcon?: Component;
  assistantName?: string;
  hideAllFilesButton?: boolean;
  hideHeader?: boolean;
}>();

const hideAssistantHeader = computed(() => props.hideHeader ?? false);

const emit = defineEmits<{
  (e: 'toolClick', tool: ToolContent): void;
}>();

const handleToolClick = (tool: ToolContent) => {
  emit('toolClick', tool);
};

// For backward compatibility, provide the original computed properties
const stepContent = computed(() => props.message.content as StepContent);
const messageContent = computed(() => props.message.content as MessageContent);
const toolContent = computed(() => props.message.content as ToolContent);
const attachmentsContent = computed(() => props.message.content as AttachmentsContent);

// Control content expand/collapse state
const isExpanded = ref(true);

const { relativeTime } = useRelativeTime();

const isSandboxPath = (href: string) =>
  href.startsWith('/home/') || href.startsWith('/root/') || href.startsWith('/tmp/');

const renderer = new marked.Renderer();
renderer.link = ({ href, title, text }: { href: string; title?: string | null; text: string }) => {
  const titleAttr = title ? ` title="${title}"` : '';
  if (href && isSandboxPath(href)) {
    return `<a href="#" data-sandbox-file="${href}"${titleAttr} class="sandbox-file-link">${text}</a>`;
  }
  return `<a href="${href}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`;
};

const renderMarkdown = (text: string) => {
  if (typeof text !== 'string') return '';
  const html = marked(text, { renderer }) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target', 'data-sandbox-file'] });
};

const handleMarkdownClick = async (event: MouseEvent) => {
  const target = event.target as HTMLElement;
  const anchor = target.closest('a[data-sandbox-file]') as HTMLAnchorElement | null;
  if (!anchor) return;
  event.preventDefault();
  const filePath = anchor.getAttribute('data-sandbox-file');
  if (!filePath || !props.sessionId) return;
  try {
    const result = await viewFile(props.sessionId, filePath);
    const filename = filePath.split('/').pop() || 'file';
    const blob = new Blob([result.content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error('Failed to download sandbox file:', e);
  }
};
</script>

<style>
.duration-300 {
  animation-duration: .3s;
}

.duration-300 {
  transition-duration: .3s;
}

.sandbox-file-link {
  color: var(--text-brand);
  text-decoration: underline;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.sandbox-file-link::before {
  content: "⬇";
  font-size: 0.75em;
  opacity: 0.7;
}
</style>
