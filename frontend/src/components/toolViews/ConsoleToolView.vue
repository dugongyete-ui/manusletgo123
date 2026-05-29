<template>
  <div
    class="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
    <div class="flex-1 flex items-center justify-center">
      <div class="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
        JS Console
      </div>
    </div>
  </div>
  <div class="flex-1 min-h-0 w-full overflow-y-auto flex flex-col font-mono text-sm">

    <div v-if="jsCode" class="px-3 py-2 border-b border-[var(--border-main)]">
      <div class="text-[10px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wider">Input</div>
      <pre class="whitespace-pre-wrap break-all text-[var(--text-primary)] bg-[var(--fill-tsp-gray-main)] rounded p-2 text-xs overflow-auto max-h-40">{{ jsCode }}</pre>
    </div>

    <div class="px-3 py-2 flex-1 overflow-auto">
      <div class="text-[10px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wider">Result</div>
      <pre
        v-if="hasResult"
        class="whitespace-pre-wrap break-all text-[var(--text-primary)] bg-[var(--fill-tsp-gray-main)] rounded p-2 text-xs overflow-auto"
      >{{ formattedResult }}</pre>
      <div v-else class="text-[var(--text-tertiary)] text-xs italic">
        {{ toolContent?.status === 'calling' ? 'Executing…' : 'No result' }}
      </div>
    </div>

    <div v-if="imageUrl" class="px-3 pb-3">
      <div class="text-[10px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wider">Browser state</div>
      <img :src="imageUrl" alt="Browser state" class="w-full rounded border border-[var(--border-main)] opacity-80" />
    </div>

  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { getFileDownloadUrl } from '@/api/file';
import { API_CONFIG } from '@/api/client';
import type { ToolContent } from '@/types/message';

const props = defineProps<{
  sessionId: string;
  toolContent: ToolContent;
  live: boolean;
  isShare: boolean;
}>();

const jsCode = computed(() => {
  const raw = props.toolContent?.content?.js_code ?? props.toolContent?.args?.javascript ?? '';
  return raw
    .replace(/^async\s*\(\.\.\.\w+\)\s*=>\s*\(?([\s\S]*?)\)?$/, '$1')
    .replace(/^\(\.\.\.\w+\)\s*=>\s*/, '')
    .trim();
});

const jsResult = computed(() =>
  props.toolContent?.content?.js_result
);

const hasResult = computed(() =>
  jsResult.value !== undefined && jsResult.value !== null
);

const formattedResult = computed(() => {
  const val = jsResult.value;
  if (val === null || val === undefined) return 'null';
  if (typeof val === 'string') return val;
  try { return JSON.stringify(val, null, 2); } catch { return String(val); }
});

const imageUrl = ref('');

watch(
  () => props.toolContent?.content?.screenshot,
  async (screenshotId) => {
    if (!screenshotId) return;
    try {
      if (screenshotId.startsWith('/') || screenshotId.startsWith('http')) {
        imageUrl.value = screenshotId.startsWith('http')
          ? screenshotId
          : `${API_CONFIG.host}${screenshotId}`;
        return;
      }
      const url = await getFileDownloadUrl({ file_id: screenshotId } as import('@/api/file').FileInfo);
      imageUrl.value = url;
    } catch {
      imageUrl.value = screenshotId;
    }
  },
  { immediate: true },
);
</script>
