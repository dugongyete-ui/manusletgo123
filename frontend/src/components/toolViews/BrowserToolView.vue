<template>
  <div
    class="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
    <div class="flex-1 flex items-center justify-center">
      <div class="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
        {{ isConsole ? 'JS Console' : (toolContent?.args?.url || 'Browser') }}
        <span v-if="!isConsole && toolContent?.function" class="ml-1 text-[9px] text-[var(--text-tertiary)] opacity-50">[{{ toolContent.function }}]</span>
      </div>
    </div>
  </div>
  <div class="flex-1 min-h-0 w-full overflow-y-auto">

    <!-- JS Console view for browser_console_exec / browser_console_view -->
    <div v-if="isConsole" class="flex flex-col h-full font-mono text-sm">
      <div v-if="toolContent?.content?.js_code" class="px-3 py-2 border-b border-[var(--border-main)]">
        <div class="text-[10px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wider">Input</div>
        <pre class="whitespace-pre-wrap break-all text-[var(--text-primary)] bg-[var(--fill-tsp-gray-main)] rounded p-2 text-xs overflow-auto max-h-40">{{ toolContent.content.js_code }}</pre>
      </div>
      <div class="px-3 py-2 flex-1 overflow-auto">
        <div class="text-[10px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wider">Result</div>
        <pre
          v-if="toolContent?.content?.js_result !== undefined && toolContent?.content?.js_result !== null"
          class="whitespace-pre-wrap break-all text-[var(--text-primary)] bg-[var(--fill-tsp-gray-main)] rounded p-2 text-xs overflow-auto"
        >{{ formatResult(toolContent.content.js_result) }}</pre>
        <div v-else class="text-[var(--text-tertiary)] text-xs italic">
          {{ toolContent?.status === 'calling' ? 'Executing…' : 'No result' }}
        </div>
      </div>
      <!-- Small screenshot thumbnail for context -->
      <div v-if="imageUrl" class="px-3 pb-2">
        <div class="text-[10px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wider">Browser state</div>
        <img :src="imageUrl" alt="Browser state" class="w-full rounded border border-[var(--border-main)] opacity-80" />
      </div>
    </div>

    <!-- Normal browser screenshot view -->
    <div v-else class="px-0 py-0 flex flex-col relative h-full">
      <div class="w-full h-full object-cover flex items-center justify-center bg-[var(--fill-white)] relative">
        <div class="w-full h-full">
          <img
            v-if="imageUrl"
            alt="Browser Screenshot"
            class="cursor-pointer w-full"
            referrerpolicy="no-referrer"
            :src="imageUrl"
          />
          <div
            v-else
            class="w-full h-full flex items-center justify-center text-[var(--text-tertiary)] text-sm"
          >
            <span>{{ $t('Loading browser…') }}</span>
          </div>
        </div>
        <button
          v-if="!isShare"
          @click="takeOver"
          class="absolute right-[10px] bottom-[10px] z-10 min-w-10 h-10 flex items-center justify-center rounded-full bg-[var(--background-white-main)] text-[var(--text-primary)] border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-S)] backdrop-blur-3xl cursor-pointer hover:bg-[var(--text-brand)] hover:px-4 hover:text-[var(--text-white)] group transition-width duration-300">
          <TakeOverIcon />
          <span
            class="text-sm max-w-0 overflow-hidden whitespace-nowrap opacity-0 transition-all duration-300 group-hover:max-w-[200px] group-hover:opacity-100 group-hover:ml-1 group-hover:text-[var(--text-white)]">{{ t('Take Over') }}</span>
        </button>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ToolContent } from '@/types/message';
import { ref, watch, computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { getFileDownloadUrl } from '@/api/file';
import { API_CONFIG } from '@/api/client';
import TakeOverIcon from '@/components/icons/TakeOverIcon.vue';

const props = defineProps<{
  sessionId: string;
  toolContent: ToolContent;
  live: boolean;
  isShare: boolean;
}>();

const { t } = useI18n();
const imageUrl = ref('');

const isConsole = computed(() => {
  const fn = props.toolContent?.function;
  if (fn === 'browser_console_exec' || fn === 'browser_console_view') return true;
  if (props.toolContent?.args?.javascript !== undefined) return true;
  if (props.toolContent?.content?.js_code !== undefined) return true;
  return false;
});

const formatResult = (val: any): string => {
  if (val === null || val === undefined) return 'null';
  if (typeof val === 'string') return val;
  try { return JSON.stringify(val, null, 2); } catch { return String(val); }
};

watch(
  () => props.toolContent?.content?.screenshot,
  async (screenshotId) => {
    if (!screenshotId) {
      return;
    }
    try {
      // The backend SSE layer replaces the file_id with a signed URL path
      // (e.g. "/api/v1/files/<id>?signature=...") before streaming to the
      // frontend.  If screenshotId is already a path/URL, use it directly
      // instead of trying to create a second signed URL from it.
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

const takeOver = () => {
  window.dispatchEvent(new CustomEvent('takeover', {
    detail: {
      sessionId: props.sessionId,
      active: true
    }
  }));
};
</script>

<style scoped>
</style>
