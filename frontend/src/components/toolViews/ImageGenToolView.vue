<template>
  <div
    class="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
    <div class="flex-1 flex items-center justify-center">
      <div class="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
        Image Generation
      </div>
    </div>
  </div>
  <div class="flex-1 min-h-0 w-full overflow-y-auto">
    <div class="flex-1 min-h-0 max-w-[640px] mx-auto p-4">

      <div v-if="result && result.url" class="flex flex-col gap-3">
        <div class="rounded-xl overflow-hidden border border-[var(--border-light)] bg-[var(--background-gray-main)] relative group">
          <img
            :src="result.url"
            :alt="result.prompt"
            class="w-full object-contain max-h-[420px]"
            @error="onImgError"
          />
          <button
            @click="openImage(result.url)"
            class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-black/60 hover:bg-black/80 text-white text-xs px-3 py-1.5 rounded-full"
          >
            Open full size
          </button>
        </div>

        <div class="flex flex-col gap-1.5">
          <div class="text-[11px] text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Prompt</div>
          <div class="text-[13px] text-[var(--text-secondary)] leading-relaxed bg-[var(--fill-tsp-gray-main)] rounded-lg px-3 py-2 border border-[var(--border-light)]">
            {{ result.revised_prompt || result.prompt }}
          </div>
        </div>

        <div class="flex items-center gap-2 text-[12px] text-[var(--text-tertiary)]">
          <span class="rounded-full bg-[var(--fill-tsp-gray-main)] border border-[var(--border-light)] px-2 py-0.5 font-mono">{{ result.model }}</span>
          <button
            @click="openImage(result.url)"
            class="ml-auto text-[var(--text-brand)] hover:underline"
          >
            Download ↗
          </button>
        </div>
      </div>

      <div v-else-if="isLoading" class="flex flex-col items-center justify-center gap-3 py-12 text-[var(--text-tertiary)]">
        <div class="w-8 h-8 border-2 border-[var(--border-main)] border-t-[var(--text-brand)] rounded-full animate-spin" />
        <span class="text-sm">Generating image…</span>
      </div>

      <div v-else class="flex items-center justify-center h-24 text-[var(--text-tertiary)] text-sm">
        No image generated
      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { ToolContent } from '@/types/message';

const props = defineProps<{
  sessionId: string;
  toolContent: ToolContent;
  live: boolean;
}>();

const result = computed(() => {
  const content = props.toolContent as any;
  const data = content?.content ?? content;
  if (data?.generated_url) {
    return {
      url: data.generated_url,
      prompt: data.generated_prompt,
      model: data.generated_model,
      revised_prompt: data.generated_prompt,
    };
  }
  if (data?.url) return data;
  return null;
});

const isLoading = computed(() => props.live && !result.value);

function openImage(url: string) {
  if (url) window.open(url, '_blank');
}

function onImgError(e: Event) {
  const img = e.target as HTMLImageElement;
  img.style.opacity = '0.3';
}
</script>
