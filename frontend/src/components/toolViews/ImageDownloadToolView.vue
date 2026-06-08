<template>
  <div
    class="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
    <div class="flex-1 flex items-center justify-center">
      <div class="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
        Image Download
      </div>
    </div>
  </div>
  <div class="flex-1 min-h-0 w-full overflow-y-auto flex flex-col items-center justify-center p-4 gap-3">
    <template v-if="dataUrl">
      <div class="w-full max-w-[400px] rounded-lg overflow-hidden border border-[var(--border-light)] bg-[var(--background-gray-main)] shadow">
        <img
          :src="dataUrl"
          alt="Downloaded image"
          class="w-full object-contain max-h-[340px]"
          @error="onImgError"
        />
      </div>
      <div class="text-[var(--text-tertiary)] text-xs text-center break-all max-w-[360px]">
        {{ shortPath }}
        <span v-if="sizeKb" class="ml-1 text-[var(--text-quaternary)]">({{ sizeKb }} KB)</span>
      </div>
    </template>

    <template v-else-if="filePath">
      <div class="flex flex-col items-center gap-2 text-center">
        <div class="w-12 h-12 rounded-full bg-[var(--fill-tsp-gray-main)] flex items-center justify-center">
          <ImageIcon :size="24" class="text-[var(--text-tertiary)]" />
        </div>
        <div class="text-[var(--text-secondary)] text-sm font-medium">Image saved</div>
        <div class="text-[var(--text-tertiary)] text-xs break-all max-w-[300px]">{{ filePath }}</div>
        <div v-if="sizeKb" class="text-[var(--text-quaternary)] text-xs">{{ sizeKb }} KB</div>
      </div>
    </template>

    <template v-else>
      <div class="text-[var(--text-tertiary)] text-sm">Downloading image…</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { Image as ImageIcon } from 'lucide-vue-next';
import type { ToolContent } from '@/types/message';

const props = defineProps<{
  sessionId: string;
  toolContent: ToolContent;
  live: boolean;
}>();

const imgError = ref(false);

const resultData = computed(() => {
  const content = props.toolContent as any;
  return content?.content ?? content;
});

const dataUrl = computed(() => {
  if (imgError.value) return null;
  return resultData.value?.data_url ?? null;
});

const filePath = computed(() => resultData.value?.file_path ?? null);

const shortPath = computed(() => {
  const p = filePath.value;
  if (!p) return '';
  return p.replace(/^\/home\/runner\//, '~/');
});

const sizeKb = computed(() => {
  const s = resultData.value?.size;
  if (!s) return null;
  return Math.round(s / 1024);
});

function onImgError() {
  imgError.value = true;
}
</script>
