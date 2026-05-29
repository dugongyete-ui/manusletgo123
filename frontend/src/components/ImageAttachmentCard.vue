<template>
  <div class="relative w-full">
    <!-- Thumbnail -->
    <div class="w-full h-40 overflow-hidden rounded-t-[11px] bg-[var(--background-gray-main)]">
      <img
        v-if="imageUrl"
        :src="imageUrl"
        :alt="file.filename"
        class="w-full h-full object-cover"
        @error="imgError = true"
      />
      <div v-else class="w-full h-full flex items-center justify-center">
        <div class="w-6 h-6 border-2 border-[var(--border-main)] border-t-transparent rounded-full animate-spin" />
      </div>
    </div>
    <!-- File name bar -->
    <div class="flex items-center gap-1.5 px-2 py-2 border-t border-[var(--border-light)]">
      <div class="text-sm text-[var(--text-primary)] text-ellipsis overflow-hidden whitespace-nowrap flex-1 min-w-0">
        {{ file.filename }}
      </div>
      <div class="shrink-0 text-xs text-[var(--text-tertiary)]">{{ extLabel }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import { getFileDownloadUrl } from '../api/file';
import type { FileInfo } from '../api/file';

const props = defineProps<{
  file: FileInfo;
}>();

const imageUrl = ref('');
const imgError = ref(false);

watch(
  () => props.file,
  async (file) => {
    if (!file) return;
    try {
      imageUrl.value = await getFileDownloadUrl(file);
    } catch {
      imgError.value = true;
    }
  },
  { immediate: true },
);

const extLabel = computed(() => {
  return props.file.filename.split('.').pop()?.toUpperCase() ?? 'IMG';
});
</script>
