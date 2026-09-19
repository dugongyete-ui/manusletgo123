<template>
  <div
    class="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
    <div class="flex-1 flex items-center justify-center">
      <div class="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">{{
        shellSessionId }}
      </div>
    </div>
  </div>
  <div class="flex-1 min-h-0 w-full overflow-y-auto">
    <div dir="ltr" data-orientation="horizontal" class="flex flex-col flex-1 min-h-0">
      <div data-state="active" data-orientation="horizontal" role="tabpanel"
        id="radix-:r5m:-content-setup" tabindex="0"
        class="py-2 focus-visible:outline-none data-[state=inactive]:hidden flex-1 font-mono text-sm leading-relaxed px-3 outline-none overflow-auto whitespace-pre-wrap break-all text-[var(--text-primary)] bg-[var(--background-gray-main)]"
        style="animation-duration: 0s;">
        <code v-html="shell"></code>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed, watch, onUnmounted } from 'vue';
import { viewShellSession } from '@/api/agent';
import { ToolContent } from '@/types/message';
//import { showErrorToast } from '@/utils/toast';

const props = defineProps<{
  sessionId: string;
  toolContent: ToolContent;
  live: boolean;
}>();

defineExpose({
  loadContent: () => {
    loadShellContent();
  }
});

const shell = ref('');
const refreshTimer = ref<ReturnType<typeof setInterval> | null>(null);

/** Escape untrusted shell output before it lands in v-html (XSS hardening). */
const escapeHtml = (s: unknown): string =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

// Get shellSessionId from toolContent
const shellSessionId = computed(() => {
  // Explicit `id` argument wins (agent reused an existing session).
  if (props.toolContent?.args?.id) {
    return props.toolContent.args.id;
  }
  // The agent may omit `id` (auto-created session) — the backend echoes the
  // resolved session id inside the tool content so live polling still works.
  if (props.toolContent?.content?.session_id) {
    return props.toolContent.content.session_id;
  }
  return '';
});

/**
 * PERF: batasi output yang dirender (innerHTML penuh untuk output shell
 * puluhan-ribuan baris adalah sumber utama UI "lelet" saat agent bekerja).
 * Simpan TAIL output + penanda truncation; data penuh tetap di backend.
 */
const MAX_RENDER_CHARS = 120_000;
const MAX_RENDER_LINES = 400;
const truncateRendered = (s: string): string => {
  if (s.length <= MAX_RENDER_CHARS && s.split('\n').length <= MAX_RENDER_LINES) return s;
  const lines = s.split('\n');
  let tail = lines.slice(-MAX_RENDER_LINES).join('\n');
  if (tail.length > MAX_RENDER_CHARS) tail = tail.slice(-MAX_RENDER_CHARS);
  return `[… ${lines.length - MAX_RENDER_LINES} baris lebih awal disembunyikan (output penuh tersimpan di sesi) …]\n` + tail;
};

let loadPending = false;
let loadQueued = false;
/** PERF: debounce trailing — watcher ganda + timer polling tidak menumpuk request. */
const scheduleLoad = () => {
  if (loadPending) { loadQueued = true; return; }
  loadPending = true;
  setTimeout(async () => {
    loadPending = false;
    try { await loadShellContent(); } finally {
      if (loadQueued) { loadQueued = false; scheduleLoad(); }
    }
  }, 250);
};

/** PERF: jeda polling saat tab tidak terlihat — hemat CPU & request. */
const documentVisible = ref(true);
const onVisibility = () => { documentVisible.value = !document.hidden; };

const updateShellContent = (console: any) => {
  if (console == null) return;
  let newShell = '';
  if (Array.isArray(console)) {
    // Normal shape: list of {ps1, command, output} records. Guard every
    // field — a malformed record must render as text, never as "undefined".
    for (const e of console) {
      if (e && typeof e === 'object') {
        newShell += `<span style="color: var(--function-success);">${escapeHtml(e.ps1)}</span><span style="color: var(--text-primary);"> ${escapeHtml(e.command)}</span>\n`;
        newShell += `<span>${escapeHtml(e.output)}</span>\n`;
      } else if (e != null) {
        newShell += `${escapeHtml(e)}\n`;
      }
    }
  } else if (typeof console === 'string') {
    // Plain-text payload (e.g. an error message or "(No Console)") — render
    // it as-is. Iterating a string per-character is what produced the
    // "undefined undefined" garbage in the first place.
    newShell = escapeHtml(console);
  } else if (typeof console === 'object') {
    newShell = escapeHtml(JSON.stringify(console));
  }
  if (newShell !== shell.value) {
    shell.value = truncateRendered(newShell);
  }
}

// Function to load Shell session content
const loadShellContent = async () => {
  if (!props.live) {
    updateShellContent(props.toolContent.content?.console);
    return;
  }
  
  if (!shellSessionId.value) return;

  try {
    const response = await viewShellSession(props.sessionId, shellSessionId.value);
    updateShellContent(response.console);
  } catch (error) {
    console.error("Failed to load shell content:", error);
  }
};

// Start auto-refresh timer
const startAutoRefresh = () => {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value);
  }

  if (props.live && shellSessionId.value) {
    refreshTimer.value = setInterval(() => {
      // PERF: skip polling saat tab hidden / panel tidak aktif —
      // interval tetap berjalan tapi tanpa request sampai visible lagi.
      if (document.hidden) return;
      scheduleLoad();
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

watch(() => props.toolContent, () => {
  scheduleLoad();
});

// The session id can arrive AFTER mount (tool event transitions from
// "calling" to "called" and the backend echoes the resolved id) — start
// polling as soon as it shows up, not only on mount.
watch(shellSessionId, (newId) => {
  if (newId) {
    scheduleLoad();
    startAutoRefresh();
  }
});

watch(() => props.toolContent.timestamp, () => {
  scheduleLoad();
});

// Watch for live prop changes
watch(() => props.live, (live: boolean) => {
  if (live) {
    scheduleLoad();
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }
});

// Load content and set up refresh timer when component is mounted
onMounted(() => {
  document.addEventListener('visibilitychange', onVisibility);
  scheduleLoad();
  startAutoRefresh();
});

// Clear timer when component is unmounted
onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibility);
  stopAutoRefresh();
});
</script>
