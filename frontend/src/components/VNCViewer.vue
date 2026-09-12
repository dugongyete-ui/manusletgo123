<template>
  <div
    ref="vncContainer"
    class="vnc-container"
    :class="{ 'vnc-mobile': viewMode === 'mobile' }"
    style="display: flex; width: 100%; height: 100%; overflow: auto; background: rgb(40, 40, 40);">
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount, watch } from 'vue';
import { getVNCUrl } from '@/api/agent';
// @ts-ignore
import RFB from '@novnc/novnc';

type VNCViewMode = 'fit' | 'pan' | 'mobile';

const props = defineProps<{
  sessionId: string;
  enabled?: boolean;
  viewOnly?: boolean;
  retryToken?: number;
  /** 'fit' — scale remote screen to container (default);
   *  'pan'  — native resolution, scrollbars + drag to pan;
   *  'mobile' — constrained by parent into a phone frame, scaled to fit. */
  viewMode?: VNCViewMode;
}>();

const emit = defineEmits<{
  connected: [];
  disconnected: [reason?: any];
  credentialsRequired: [];
}>();

const vncContainer = ref<HTMLDivElement | null>(null);
let rfb: RFB | null = null;
let initAttempts = 0;

const initVNCConnection = async () => {
  if (!vncContainer.value || !props.enabled) return;

  // Disconnect existing connection
  if (rfb) {
    rfb.disconnect();
    rfb = null;
  }

  initAttempts = 0;
  let wsUrl: string | null = null;
  // Fetch the signed URL with a few retries — the backend may still be
  // waking the sandbox services on the very first click.
  while (initAttempts < 3 && !wsUrl) {
    try {
      wsUrl = await getVNCUrl(props.sessionId);
    } catch (error) {
      initAttempts++;
      console.error(`Failed to get VNC URL (attempt ${initAttempts}/3):`, error);
      if (initAttempts < 3) await new Promise(r => setTimeout(r, 2000));
    }
  }
  if (!wsUrl) {
    emit('disconnected', { detail: 'Could not obtain a VNC access URL for this session.' });
    return;
  }

  try {
    // Create NoVNC connection
    rfb = new RFB(vncContainer.value, wsUrl, {
      credentials: { password: '' },
      shared: true,
      repeaterID: '',
      wsProtocols: ['binary'],
    });

    // Set viewOnly based on props, default to false (interactive)
    rfb.viewOnly = props.viewOnly ?? false;
    applyViewMode(props.viewMode ?? 'fit');

    rfb.addEventListener('connect', () => {
      console.log('VNC connection successful');
      emit('connected');
    });

    rfb.addEventListener('disconnect', (e: any) => {
      console.log('VNC connection disconnected', e);
      emit('disconnected', e);
    });

    rfb.addEventListener('credentialsrequired', () => {
      console.log('VNC credentials required');
      emit('credentialsRequired');
    });
  } catch (error) {
    console.error('Failed to initialize VNC connection:', error);
    emit('disconnected', { detail: String(error) });
  }
};

/** Apply the display/interaction mode to the live RFB connection. */
const applyViewMode = (mode: VNCViewMode) => {
  if (!rfb) return;
  switch (mode) {
    case 'pan':
      // Native resolution with scrollbars; drag with mouse/touch to pan
      rfb.scaleViewport = false;
      rfb.clipViewport = true;
      rfb.dragViewport = true;
      break;
    case 'mobile':
      // Parent constrains the container to a phone frame; scale inside it
      rfb.clipViewport = false;
      rfb.scaleViewport = true;
      rfb.dragViewport = false;
      break;
    case 'fit':
    default:
      // Whole remote screen scaled to fit the container
      rfb.clipViewport = false;
      rfb.scaleViewport = true;
      rfb.dragViewport = false;
      break;
  }
};

const disconnect = () => {
  if (rfb) {
    rfb.disconnect();
    rfb = null;
  }
};

/* ---------------- keyboard injection API (virtual keyboard) ---------------- */

/** Send a single keysym press + release. */
const sendKey = (keysym: number, code: string) => {
  rfb?.sendKey(keysym, code);
};

/** Send an ordered sequence of raw key events: [keysym, code, down][]. */
const sendSequence = (seq: Array<[number, string, boolean]>) => {
  if (!rfb) return;
  for (const [keysym, code, down] of seq) {
    rfb.sendKey(keysym, code, down);
  }
};

const sendCtrlAltDel = () => {
  rfb?.sendCtrlAltDel();
};

// Watch for session ID or enabled state changes
watch([() => props.sessionId, () => props.enabled], () => {
  if (props.enabled && vncContainer.value) {
    initVNCConnection();
  } else {
    disconnect();
  }
}, { immediate: true });

// Watch for container availability
watch(vncContainer, () => {
  if (vncContainer.value && props.enabled) {
    initVNCConnection();
  }
});

// Watch for manual retry
watch(() => props.retryToken, () => {
  if (props.enabled && vncContainer.value) {
    initVNCConnection();
  }
});

// React to view mode changes without reconnecting
watch(() => props.viewMode, (mode) => {
  applyViewMode(mode ?? 'fit');
});

onBeforeUnmount(() => {
  disconnect();
});

// Expose methods for parent component
defineExpose({
  disconnect,
  initConnection: initVNCConnection,
  sendKey,
  sendSequence,
  sendCtrlAltDel,
});
</script>

<style scoped>
/* When the parent constrains us into a phone frame, round the inner corners */
.vnc-mobile {
  border-radius: inherit;
  background: #000;
}
</style>
