<template>
  <div v-if="tool.name === 'message' && tool.args?.text"
    class="prose prose-sm dark:prose-invert max-w-none text-[var(--text-secondary)] text-[14px] leading-relaxed
           [&_a]:text-[var(--text-brand)] [&_a]:underline [&_a]:break-all
           [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5"
    v-html="renderMarkdown(tool.args.text)"
  />
  <div v-else-if="toolInfo" class="flex items-center group gap-2">
    <div class="flex-1 min-w-0">
      <div @click="handleClick"
        class="rounded-[10px] items-center gap-2 px-[10px] py-[5px] border border-[var(--border-light)] bg-[var(--fill-tsp-gray-main)] dark:bg-[var(--background-card)] dark:border-[var(--border-main)] inline-flex max-w-full clickable hover:bg-[var(--fill-tsp-gray-dark)] dark:hover:brightness-110">
        <div class="w-[16px] inline-flex items-center text-[var(--icon-tertiary)]">
          <component :is="toolInfo.icon" :size="21" />
        </div>
        <div class="flex-1 h-full min-w-0 flex">
          <div
            class="inline-flex items-center h-full rounded-full text-[14px] text-[var(--text-secondary)] max-w-[100%]">
            <div class="max-w-[100%] text-ellipsis overflow-hidden whitespace-nowrap text-[13px]"
              :title="`${toolInfo.function}${toolInfo.functionArg}`">
              <div class="flex items-center">
                {{ toolInfo.function
                }}<span
                  class="flex-1 min-w-0 rounded-[6px] px-1 ml-1 relative top-[0px] text-[12px] font-mono max-w-full text-ellipsis overflow-hidden whitespace-nowrap text-[var(--text-tertiary)]"><code>{{ toolInfo.functionArg }}</code></span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
      {{ relativeTime(tool.timestamp) }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ToolContent } from "../types/message";
import { useToolInfo } from "../composables/useTool";
import { useRelativeTime } from "../composables/useTime";
import { marked } from "marked";
import DOMPurify from "dompurify";

const props = defineProps<{
  tool: ToolContent;
}>();

const emit = defineEmits<{
  (e: "click"): void;
}>();

const { relativeTime } = useRelativeTime();
const { toolInfo } = useToolInfo(ref(props.tool));

const renderer = new marked.Renderer();
renderer.link = ({ href, title, text }: { href: string; title?: string | null; text: string }) => {
  const titleAttr = title ? ` title="${title}"` : '';
  return `<a href="${href}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`;
};

const renderMarkdown = (text: string) => {
  if (typeof text !== 'string') return '';
  const html = marked(text, { renderer }) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target', 'rel'] });
};

const handleClick = () => {
  emit("click");
};
</script>
