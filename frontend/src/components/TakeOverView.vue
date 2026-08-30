<template>
    <div v-if="shouldShow" class="fixed bg-[var(--background-gray-main)] z-50 transition-all w-full h-full inset-0">
        <div class="w-full h-full relative flex" :class="mobileMode ? 'items-center justify-center' : ''">
            <!-- Phone frame wrapper (mobile view mode) -->
            <div class="w-full h-full vnc-frame" :class="{ 'phone-frame': mobileMode }">
                <VNCViewer ref="vncViewerRef"
                    :session-id="sessionId"
                    :enabled="shouldShow"
                    :retry-token="retryToken"
                    :view-only="false"
                    :view-mode="viewMode"
                    @connected="onVNCConnected"
                    @disconnected="onVNCDisconnected"
                    @credentials-required="onVNCCredentialsRequired"
                />
            </div>
        </div>

        <!-- Connection status overlay — replaces the old silent black screen -->
        <div v-if="connectionState !== 'connected'"
            class="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[var(--background-gray-main)] pointer-events-none">
            <template v-if="connectionState === 'connecting'">
                <div class="w-10 h-10 rounded-full border-[3px] border-[var(--border-dark)] border-t-transparent animate-spin"></div>
                <div class="text-[15px] text-[var(--text-secondary)] font-medium">{{ t('Connecting to Dzeck Computer…') }}</div>
                <div class="text-[13px] text-[var(--text-tertiary)] max-w-[420px] text-center leading-relaxed">
                    {{ t('The first connection may take up to a minute while the computer environment is prepared.') }}
                </div>
            </template>
            <template v-else-if="connectionState === 'failed'">
                <div class="w-12 h-12 rounded-full bg-[var(--fill-tsp-gray-main)] flex items-center justify-center">
                    <MonitorX :size="26" class="text-[var(--text-tertiary)]" />
                </div>
                <div class="text-[15px] text-[var(--text-primary)] font-semibold">{{ t('Computer view unavailable') }}</div>
                <div class="text-[13px] text-[var(--text-tertiary)] max-w-[440px] text-center leading-relaxed">
                    {{ failReason || t('Could not reach the computer preview. The sandbox may be sleeping or still starting — try again in a moment.') }}
                </div>
                <button @click="retry"
                    class="mt-1 h-9 px-4 rounded-full bg-[var(--Button-primary-black)] text-[var(--text-onblack)] text-sm font-medium border-2 border-[var(--border-dark)] hover:opacity-90 cursor-pointer">
                    {{ t('Retry') }}
                </button>
            </template>
        </div>

        <!-- Manus-style vertical toolbar (left, vertically centered) -->
        <VNCToolbar v-model:collapsed="toolbarCollapsed" v-model:pan-mode="panMode"
            v-model:keyboard-open="keyboardOpen" v-model:mobile-mode="mobileMode"
            @open-window="openInNewWindow" />

        <!-- On-screen virtual keyboard (bottom) -->
        <div v-if="keyboardOpen" class="absolute left-0 right-0 bottom-0 z-30">
            <VirtualKeyboard :send-key="vncSendKey" :send-sequence="vncSendSequence"
                :send-ctrl-alt-del="vncSendCtrlAltDel" @close="keyboardOpen = false" />
        </div>

        <div class="absolute bottom-4 left-1/2 -translate-x-1/2" :class="{ 'kb-open': keyboardOpen }">
            <button @click="exitTakeOver"
                class="inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-black)] text-[var(--text-onblack)] h-[36px] px-[12px] gap-[6px] text-sm rounded-full border-2 border-[var(--border-dark)] shadow-[0px_8px_32px_0px_rgba(0,0,0,0.32)]">
                <span class="text-sm font-medium">{{ t('Exit Takeover') }}</span>
            </button>
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { MonitorX } from 'lucide-vue-next';
import VNCViewer from './VNCViewer.vue';
import VNCToolbar from './VNCToolbar.vue';
import VirtualKeyboard from './VirtualKeyboard.vue';

type VNCViewMode = 'fit' | 'pan' | 'mobile';

const route = useRoute();
const router = useRouter();
const { t } = useI18n();

// Takeover state
const takeOverActive = ref(false);
const currentSessionId = ref('');

// 'connecting' | 'connected' | 'failed'
const connectionState = ref<'connecting' | 'connected' | 'failed'>('connecting');
const failReason = ref('');
// Bumped by Retry — VNCViewer watches it to re-init the connection
const retryToken = ref(0);

// ---- Toolbar state (Manus.im-style) ----
const toolbarCollapsed = ref(false); // 1. collapse/expand the toolbar itself
const panMode = ref(false);          // 2. hand tool — drag to pan the view
const keyboardOpen = ref(false);     // 3. virtual keyboard
const mobileMode = ref(false);       // 5. phone-frame view

// Effective display mode passed to VNCViewer
const viewMode = computed<VNCViewMode>(() => {
    if (mobileMode.value) return 'mobile';
    if (panMode.value) return 'pan';
    return 'fit';
});

// VNC viewer ref for keyboard injection
const vncViewerRef = ref<InstanceType<typeof VNCViewer> | null>(null);

const vncSendKey = (keysym: number, code: string) => {
    vncViewerRef.value?.sendKey(keysym, code);
};
const vncSendSequence = (seq: Array<[number, string, boolean]>) => {
    vncViewerRef.value?.sendSequence(seq);
};
const vncSendCtrlAltDel = () => {
    vncViewerRef.value?.sendCtrlAltDel();
};

// 4. Open this takeover session in a new browser tab/window
const openInNewWindow = () => {
    const sid = sessionId.value;
    if (!sid) return;
    const href = router.resolve({ path: `/chat/${sid}`, query: { vnc: '1' } }).href;
    window.open(href, '_blank', 'noopener');
};

// Mobile mode replaces pan mode (mutually exclusive display modes)
watch(mobileMode, (on) => {
    if (on) panMode.value = false;
});
watch(panMode, (on) => {
    if (on) mobileMode.value = false;
});

// Listen to takeover events
const handleTakeOverEvent = (event: Event) => {
    const customEvent = event as CustomEvent;
    takeOverActive.value = customEvent.detail.active;
    currentSessionId.value = customEvent.detail.sessionId;
    if (customEvent.detail.active) {
        connectionState.value = 'connecting';
        failReason.value = '';
    }
};

// VNC event handlers
const onVNCConnected = () => {
    connectionState.value = 'connected';
};

const onVNCDisconnected = (reason?: any) => {
    // Only show failure if we never got a working connection
    if (connectionState.value !== 'connected') {
        connectionState.value = 'failed';
        const detail = reason?.detail || reason?.reason || '';
        failReason.value = typeof detail === 'string' && detail ? detail : '';
    } else {
        connectionState.value = 'failed';
        failReason.value = '';
    }
};

const onVNCCredentialsRequired = () => {
    connectionState.value = 'failed';
    failReason.value = t('The remote computer requires a VNC password.');
};

const retry = () => {
    connectionState.value = 'connecting';
    failReason.value = '';
    retryToken.value++;
};

// Calculate whether to show takeover view
const shouldShow = computed(() => {
    // Check component state first (from takeover event)
    if (takeOverActive.value && currentSessionId.value) {
        return true;
    }
    
    // Also check route parameters (for direct URL access or page refresh)
    const { params: { sessionId }, query: { vnc } } = route;
    // Only show if both sessionId exists in route AND vnc=1 in query
    return !!sessionId && vnc === '1';
});

// Re-arm the connecting state whenever takeover is (re)opened
watch(shouldShow, (shown) => {
    if (shown) {
        connectionState.value = 'connecting';
        failReason.value = '';
    }
});

// Add event listener when component is mounted
onMounted(() => {
    window.addEventListener('takeover', handleTakeOverEvent as EventListener);
});


// Remove event listener when component is unmounted
onBeforeUnmount(() => {
    window.removeEventListener('takeover', handleTakeOverEvent as EventListener);
});

// Get session ID
const sessionId = computed(() => {
    return currentSessionId.value || route.params.sessionId as string || '';
});

// Exit takeover functionality
const exitTakeOver = () => {
    // Reset toolbar state for the next session
    toolbarCollapsed.value = false;
    panMode.value = false;
    keyboardOpen.value = false;
    mobileMode.value = false;
    // Update local state
    takeOverActive.value = false;
    currentSessionId.value = '';
};

// Expose sessionId for parent component to use
defineExpose({
    sessionId
});
</script>

<style scoped>
/* Phone frame shown in mobile view mode */
.phone-frame {
    width: min(400px, calc(100vw - 48px));
    height: min(88vh, 860px);
    border-radius: 36px;
    border: 10px solid #1c1c1e;
    outline: 1px solid rgba(255, 255, 255, 0.18);
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.55);
    overflow: hidden;
    background: #000;
    position: relative;
}

.phone-frame :deep(.vnc-container) {
    border-radius: 26px;
}

/* Exit button lifts above the open keyboard */
.kb-open {
    bottom: 316px;
}

@media (max-width: 480px) {
    .kb-open {
        bottom: 284px;
    }
}
</style>
