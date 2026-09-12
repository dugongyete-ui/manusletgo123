<template>
  <!-- Official Manus file panel: Diff / Original / Modified tabs appear when
       the file existed before the edit (old_content present). -->
  <div class="flex flex-col min-h-0 h-full w-full">
    <div
      v-if="hasOldContent"
      class="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]"
    >
      <div class="flex-1 flex items-center justify-center">
        <div class="backdrop-blur-3xl inline-flex h-7 items-center rounded-lg bg-[var(--tab-fill)] p-0.5">
          <button
            v-for="tab in tabs"
            :key="tab.value"
            type="button"
            class="inline-flex items-center justify-center rounded-md px-3 py-1 text-xs transition-colors text-[var(--text-tertiary)] hover:cursor-pointer data-[state=on]:bg-[var(--fill-white)] data-[state=on]:text-[var(--text-primary)] data-[state=on]:shadow-[0px_0px_2px_0px_var(--shadow-S)]"
            :data-state="activeTab === tab.value ? 'on' : 'off'"
            @click="activeTab = tab.value">
            {{ tab.label }}
          </button>
        </div>
      </div>
    </div>
    <div v-else
      class="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]"
    >
      <div class="flex-1 flex items-center justify-center">
        <div
          class="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center"
        >
          {{ fileName }}
        </div>
      </div>
    </div>

    <div class="flex-1 min-h-0 w-full overflow-y-auto">
      <div
        dir="ltr"
        data-orientation="horizontal"
        class="flex flex-col min-h-0 h-full relative"
      >
        <div
          data-state="active"
          data-orientation="horizontal"
          role="tabpanel"
          tabindex="0"
          class="focus-visible:outline-none data-[state=inactive]:hidden flex-1 min-h-0 h-full text-sm flex flex-col py-0 outline-none overflow-auto"
        >
          <div v-if="activeView === 'diff' && hasOldContent" class="flex-1 min-h-0 h-full">
            <MonacoDiffEditor
              class="w-full h-full"
              :original="oldContent || ''"
              :modified="fileContent"
              :filename="fileName"
              :theme="monacoTheme"
            />
          </div>
          <section
            v-else
            style="
              display: flex;
              position: relative;
              text-align: initial;
              width: 100%;
              height: 100%;
            "
          >
            <MonacoEditor
              :value="activeView === 'oldContent' ? (oldContent || '') : fileContent"
              :filename="fileName"
              :read-only="true"
              :theme="monacoTheme"
              :line-numbers="'off'"
              :word-wrap="'on'"
              :minimap="false"
              :scroll-beyond-last-line="false"
              :automatic-layout="true"
            />
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed, watch, onUnmounted } from "vue";
import { ToolContent } from "@/types/message";
import { viewFile } from "@/api/agent";
import MonacoEditor from "@/components/ui/MonacoEditor.vue";
import MonacoDiffEditor from "@/components/ui/MonacoDiffEditor.vue";
import { useTheme } from "@/composables/useTheme";
import { useI18n } from "vue-i18n";

const props = defineProps<{
  sessionId: string;
  toolContent: ToolContent;
  live: boolean;
}>();

defineExpose({
  loadContent: () => {
    loadFileContent();
  },
});

const { t } = useI18n();
const { theme } = useTheme();
const monacoTheme = computed(() => theme.value === 'dark' ? 'vs-dark' : 'vs');

const fileContent = ref("");
const oldContent = ref<string | null>(null);
/** Official default selected tab is Modified / 已修改 */
const activeTab = ref<FileTab>('newContent');
const refreshTimer = ref<ReturnType<typeof setInterval> | null>(null);

type FileTab = 'diff' | 'oldContent' | 'newContent';

const tabs = computed(() => [
  { label: t('Diff'), value: 'diff' as const },
  { label: t('Original'), value: 'oldContent' as const },
  { label: t('Modified'), value: 'newContent' as const },
]);

const hasOldContent = computed(() => oldContent.value != null);

const activeView = computed<FileTab>(() => {
  if (!hasOldContent.value) return 'newContent';
  return activeTab.value;
});

const filePath = computed(() => {
  if (props.toolContent && props.toolContent.args.file) {
    return props.toolContent.args.file;
  }
  return "";
});

const fileName = computed(() => {
  if (filePath.value) {
    return filePath.value.split("/").pop() || "";
  }
  return "";
});

// old_content arrives with the tool event (both live SSE and history).
const applyContentPayload = () => {
  const payload = props.toolContent.content;
  if (!props.live) {
    fileContent.value = payload?.content || "";
  }
  if (payload && 'old_content' in payload) {
    oldContent.value = payload.old_content ?? '';
  } else if (!props.live) {
    oldContent.value = null;
  }
};

// Load file content
const loadFileContent = async () => {
  applyContentPayload();

  if (!props.live) {
    return;
  }

  if (!filePath.value) return;

  try {
    const response = await viewFile(props.sessionId, filePath.value);
    fileContent.value = response.content;
  } catch (error) {
    console.error("Failed to load file content:", error);
  }
};

// Start auto-refresh timer
const startAutoRefresh = () => {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value);
  }

  if (props.live && filePath.value) {
    refreshTimer.value = setInterval(() => {
      loadFileContent();
    }, 5000);
  }
};

// Stop auto-refresh timer
const stopAutoRefresh = () => {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value);
    refreshTimer.value = null;
  }
};

// Watch for filename changes to reload content
watch(filePath, (newVal: string) => {
  if (newVal) {
    loadFileContent();
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }
});

watch(() => props.toolContent.content, () => {
  applyContentPayload();
}, { immediate: true, deep: true });

watch(() => props.toolContent.timestamp, () => {
  loadFileContent();
});

// Watch for live prop changes
watch(() => props.live, (live: boolean) => {
  if (live) {
    loadFileContent();
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }
});

// Load content when component is mounted
onMounted(() => {
  loadFileContent();
  startAutoRefresh();
});

onUnmounted(() => {
  stopAutoRefresh();
});
</script>
