<template>
  <div v-if="tool.name === 'message' && tool.args?.text"
    class="prose prose-sm dark:prose-invert max-w-none text-[var(--text-secondary)] text-[14px] leading-relaxed
           [&_a]:text-[var(--text-brand)] [&_a]:underline [&_a]:break-all
           [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5"
    v-html="renderMarkdown(tool.args.text)"
  />

  <div v-else-if="toolInfo" class="flex items-center group gap-2 my-[2px]">
    <div class="flex-1 min-w-0">
      <div
        @click="handleClick"
        class="inline-flex items-center gap-0 max-w-full clickable rounded-[10px] border overflow-hidden transition-all duration-150"
        :class="chipStyle.border"
        :style="chipStyle.bg"
      >
        <!-- Left accent strip + icon -->
        <div
          class="flex items-center justify-center w-[30px] h-[28px] flex-shrink-0 self-stretch"
          :style="chipStyle.iconBg"
        >
          <component :is="toolInfo.icon" :size="15" />
        </div>

        <!-- Action label -->
        <span
          class="text-[12.5px] font-medium pl-[8px] whitespace-nowrap flex-shrink-0"
          :style="chipStyle.label"
        >{{ toolInfo.function }}</span>

        <!-- Argument pill -->
        <span
          v-if="displayArg"
          class="text-[11px] font-mono ml-[5px] mr-[8px] px-[6px] py-[1px] rounded-[5px] truncate max-w-[200px] flex-shrink min-w-0"
          :style="chipStyle.arg"
          :title="toolInfo.functionArg"
        >{{ displayArg }}</span>
        <span v-else class="mr-[8px]" />

        <!-- Status indicator -->
        <div class="flex items-center justify-center w-[20px] h-[28px] flex-shrink-0 self-stretch mr-[2px]">
          <span v-if="tool.status === 'calling'" class="relative flex h-[7px] w-[7px]">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" :style="chipStyle.pingBg" />
            <span class="relative inline-flex rounded-full h-[7px] w-[7px]" :style="chipStyle.dotBg" />
          </span>
          <svg v-else width="11" height="11" viewBox="0 0 11 11" fill="none">
            <circle cx="5.5" cy="5.5" r="5" :fill="chipStyle.checkCircle" />
            <path d="M3.2 5.5L4.8 7.1L7.8 4" :stroke="chipStyle.checkMark" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
    </div>

    <div class="flex-shrink-0 transition text-[11px] text-[var(--text-tertiary)] invisible group-hover:visible">
      {{ relativeTime(tool.timestamp) }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
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

// Color palette per tool category
const PALETTES: Record<string, {
  border: string;
  bg: string;
  iconBg: string;
  iconFilter: string;
  label: string;
  arg: string;
  pingBg: string;
  dotBg: string;
  checkCircle: string;
  checkMark: string;
}> = {
  browser: {
    border: "border-blue-200/70 dark:border-blue-900/60",
    bg: "background: linear-gradient(90deg, rgba(59,130,246,0.06) 0%, rgba(59,130,246,0.02) 100%); backdrop-filter: none;",
    iconBg: "background: rgba(59,130,246,0.12);",
    iconFilter: "",
    label: "color: #2563EB;",
    arg: "color: #3b82f6; background: rgba(59,130,246,0.08);",
    pingBg: "background-color: #93c5fd;",
    dotBg: "background-color: #3b82f6;",
    checkCircle: "rgba(59,130,246,0.15)",
    checkMark: "#2563EB",
  },
  file: {
    border: "border-amber-200/70 dark:border-amber-900/60",
    bg: "background: linear-gradient(90deg, rgba(245,158,11,0.06) 0%, rgba(245,158,11,0.02) 100%);",
    iconBg: "background: rgba(245,158,11,0.12);",
    iconFilter: "",
    label: "color: #D97706;",
    arg: "color: #b45309; background: rgba(245,158,11,0.08);",
    pingBg: "background-color: #fcd34d;",
    dotBg: "background-color: #f59e0b;",
    checkCircle: "rgba(245,158,11,0.15)",
    checkMark: "#D97706",
  },
  shell: {
    border: "border-emerald-200/70 dark:border-emerald-900/60",
    bg: "background: linear-gradient(90deg, rgba(16,185,129,0.06) 0%, rgba(16,185,129,0.02) 100%);",
    iconBg: "background: rgba(16,185,129,0.12);",
    iconFilter: "",
    label: "color: #059669;",
    arg: "color: #065f46; background: rgba(16,185,129,0.08);",
    pingBg: "background-color: #6ee7b7;",
    dotBg: "background-color: #10b981;",
    checkCircle: "rgba(16,185,129,0.15)",
    checkMark: "#059669",
  },
  info: {
    border: "border-violet-200/70 dark:border-violet-900/60",
    bg: "background: linear-gradient(90deg, rgba(139,92,246,0.06) 0%, rgba(139,92,246,0.02) 100%);",
    iconBg: "background: rgba(139,92,246,0.12);",
    iconFilter: "",
    label: "color: #7C3AED;",
    arg: "color: #5b21b6; background: rgba(139,92,246,0.08);",
    pingBg: "background-color: #c4b5fd;",
    dotBg: "background-color: #8b5cf6;",
    checkCircle: "rgba(139,92,246,0.15)",
    checkMark: "#7C3AED",
  },
  mcp: {
    border: "border-cyan-200/70 dark:border-cyan-900/60",
    bg: "background: linear-gradient(90deg, rgba(6,182,212,0.06) 0%, rgba(6,182,212,0.02) 100%);",
    iconBg: "background: rgba(6,182,212,0.12);",
    iconFilter: "",
    label: "color: #0891B2;",
    arg: "color: #0e7490; background: rgba(6,182,212,0.08);",
    pingBg: "background-color: #67e8f9;",
    dotBg: "background-color: #06b6d4;",
    checkCircle: "rgba(6,182,212,0.15)",
    checkMark: "#0891B2",
  },
  default: {
    border: "border-[var(--border-light)] dark:border-[var(--border-main)]",
    bg: "background: var(--fill-tsp-gray-main);",
    iconBg: "background: var(--fill-tsp-gray-dark);",
    iconFilter: "",
    label: "color: var(--text-secondary);",
    arg: "color: var(--text-tertiary); background: var(--fill-tsp-gray-main);",
    pingBg: "background-color: #9ca3af;",
    dotBg: "background-color: #6b7280;",
    checkCircle: "rgba(107,114,128,0.15)",
    checkMark: "#6b7280",
  },
};

const chipStyle = computed(() => {
  const name = props.tool?.name ?? "";
  return PALETTES[name] ?? PALETTES.default;
});

// Smart argument display: show hostname for URLs, filename for file paths
const displayArg = computed(() => {
  const raw = toolInfo.value?.functionArg ?? "";
  if (!raw) return "";
  const fn = props.tool?.function ?? "";
  if (fn === "browser_navigate" || fn === "browser_restart" || fn === "browser_view") {
    try {
      return new URL(raw).hostname;
    } catch {
      return raw.length > 40 ? raw.slice(0, 38) + "…" : raw;
    }
  }
  if (raw.length > 40) return raw.slice(0, 38) + "…";
  return raw;
});

const cleanLinkText = (href: string, text: string): string => {
  const isRawUrl = text === href || text.startsWith("http://") || text.startsWith("https://");
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
  if (typeof text !== "string") return "";
  const html = marked(text, { renderer }) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target", "rel"] });
};

const handleClick = () => {
  emit("click");
};
</script>
