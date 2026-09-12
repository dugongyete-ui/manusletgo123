<template>
  <div
    class="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
    <div class="flex-1 flex items-center justify-center">
      <div class="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
        Image Search
      </div>
    </div>
  </div>
  <div class="flex-1 min-h-0 w-full overflow-y-auto">
    <div class="flex-1 min-h-0 max-w-[640px] mx-auto">
      <div class="grid grid-cols-2 gap-2 p-4" v-if="images.length > 0">
        <div
          v-for="(img, i) in images"
          :key="i"
          class="relative group rounded-lg overflow-hidden border border-[var(--border-light)] bg-[var(--background-gray-main)] cursor-pointer"
          @click="openImage(img.url)"
        >
          <img
            :src="img.thumbnail || img.url"
            :alt="img.title"
            class="w-full h-32 object-cover"
            @error="onImgError($event)"
          />
          <div
            class="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-2"
          >
            <div class="text-white text-xs font-medium line-clamp-2">{{ img.title }}</div>
            <div class="text-white/70 text-[10px] truncate mt-0.5">{{ img.source }}</div>
          </div>
        </div>
      </div>
      <div v-else class="flex items-center justify-center h-24 text-[var(--text-tertiary)] text-sm">
        No image results found
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { ToolContent } from '@/types/message';

const props = defineProps<{
  sessionId: string;
  toolContent: ToolContent;
  live: boolean;
}>();

const images = computed(() => {
  const content = props.toolContent as any;
  const data = content?.content ?? content;
  return data?.results ?? [];
});

function openImage(url: string) {
  if (url) window.open(url, '_blank');
}

function onImgError(e: Event) {
  const img = e.target as HTMLImageElement;
  img.style.display = 'none';
}
</script>
