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
          <div class="inline-flex items-center h-full rounded-full text-[14px] max-w-[100%]"
            :class="showShimmer ? '' : 'text-[var(--text-secondary)]'">
            <!-- Official Manus StandardToolUsed: prefer the model-supplied
                 ``brief`` (natural-language action) over path/args. -->
            <div v-if="briefText"
              class="max-w-[100%] text-ellipsis overflow-hidden whitespace-nowrap text-[13px]"
              :class="showShimmer ? 'shimmer-text-secondary' : ''"
              :title="briefText">
              {{ briefText }}
            </div>
            <div v-else class="max-w-[100%] text-ellipsis overflow-hidden whitespace-nowrap text-[13px]"
              :class="showShimmer ? 'shimmer-text-secondary' : ''"
              :title="`${toolInfo.function}${toolInfo.functionArg}`">
              <div class="flex items-center">
                {{ toolInfo.function
                }}<span
                  class="flex-1 min-w-0 rounded-[6px] px-1 ml-1 relative top-[0px] text-[12px] font-mono max-w-full text-ellipsis overflow-hidden whitespace-nowrap text-[var(--text-tertiary)]"><code>{{ toolInfo.functionArg }}</code></span>
              </div>
            </div>
          </div>
        </div>
        <!-- Status indicator: shimmer replaces the dot while calling -->
        <div class="flex items-center flex-shrink-0">
          <span v-if="tool.status === 'calling'" class="relative flex h-[6px] w-[6px]">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--icon-tertiary)] opacity-60" />
            <span class="relative inline-flex rounded-full h-[6px] w-[6px] bg-[var(--icon-tertiary)]" />
          </span>
          <svg v-else width="10" height="10" viewBox="0 0 10 10" fill="none">
            <circle cx="5" cy="5" r="4.5" fill="var(--fill-tsp-gray-dark)" />
            <path d="M2.8 5L4.2 6.4L7.2 3.6" stroke="var(--icon-tertiary)" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
    </div>
    <div class="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
      {{ relativeTime(tool.timestamp) }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, toRef } from "vue";
import { ToolContent } from "../types/message";
import { useToolInfo } from "../composables/useTool";
import { useToolShimmer } from "../composables/useToolShimmer";
import { useRelativeTime } from "../composables/useTime";
import { marked } from "marked";
import DOMPurify from "dompurify";

const props = defineProps<{
  tool: ToolContent;
  /** Keep shimmering while this row is the live tool of a running step. */
  active?: boolean;
}>();

const emit = defineEmits<{
  (e: "click"): void;
}>();

const { relativeTime } = useRelativeTime();
const toolRef = toRef(props, "tool");
const { toolInfo } = useToolInfo(toolRef);

const statusRef = computed(() => props.tool.status);
const activeRef = computed(() => !!props.active);
const { showShimmer } = useToolShimmer(statusRef, activeRef);

/** Official Manus StandardToolUsed prefers ``brief`` over path/args. */
const briefText = computed(() => (props.tool.brief || "").trim());

const cleanLinkText = (href: string, text: string): string => {
  const isRawUrl = text === href || text.startsWith('http://') || text.startsWith('https://');
  if (isRawUrl) {
    try { return new URL(href).hostname; } catch { /* fall through */ }
  }
  return text;
};

const renderer = new marked.Renderer();
renderer.link = ({ href, text }: { href: string; title?: string | null; text: string }) => {
  return `<a href="${href}" target="_blank" rel="noopener noreferrer" title="${href}">${cleanLinkText(href, text)}</a>`;
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
