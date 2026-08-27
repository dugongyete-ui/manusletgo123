<template>
    <div v-if="shouldShow" class="fixed bg-[var(--background-gray-main)] z-50 transition-all w-full h-full inset-0">
        <div class="w-full h-full relative">
            <VNCViewer 
                :session-id="sessionId"
                :enabled="shouldShow"
                :retry-token="retryToken"
                :view-only="false"
                @connected="onVNCConnected"
                @disconnected="onVNCDisconnected"
                @credentials-required="onVNCCredentialsRequired"
            />
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

        <div class="absolute bottom-4 left-1/2 -translate-x-1/2">
            <button @click="exitTakeOver"
                class="inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-black)] text-[var(--text-onblack)] h-[36px] px-[12px] gap-[6px] text-sm rounded-full border-2 border-[var(--border-dark)] shadow-[0px_8px_32px_0px_rgba(0,0,0,0.32)]">
                <span class="text-sm font-medium">{{ t('Exit Takeover') }}</span>
            </button>
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { MonitorX } from 'lucide-vue-next';
import VNCViewer from './VNCViewer.vue';

const route = useRoute();
const { t } = useI18n();

// Takeover state
const takeOverActive = ref(false);
const currentSessionId = ref('');

// 'connecting' | 'connected' | 'failed'
const connectionState = ref<'connecting' | 'connected' | 'failed'>('connecting');
const failReason = ref('');
// Bumped by Retry — VNCViewer watches it to re-init the connection
const retryToken = ref(0);


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
</style>
