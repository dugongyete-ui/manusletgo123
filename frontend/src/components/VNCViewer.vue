<template>
  <div
    ref="vncContainer"
    class="vnc-container"
    style="display: flex; width: 100%; height: 100%; overflow: auto; background: rgb(40, 40, 40);">
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount, watch } from 'vue';
import { getVNCUrl } from '@/api/agent';
// @ts-ignore
import RFB from '@novnc/novnc';

const props = defineProps<{
  sessionId: string;
  enabled?: boolean;
  viewOnly?: boolean;
  retryToken?: number;
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
      // Scaling options
      scaleViewport: true,  // Automatically scale to fit container
      //resizeSession: true   // Request server to adjust resolution
    });

    // Set viewOnly based on props, default to false (interactive)
    rfb.viewOnly = props.viewOnly ?? false;
    rfb.scaleViewport = true;
    //rfb.resizeSession = true;

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

const disconnect = () => {
  if (rfb) {
    rfb.disconnect();
    rfb = null;
  }
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

onBeforeUnmount(() => {
  disconnect();
});

// Expose methods for parent component
defineExpose({
  disconnect,
  initConnection: initVNCConnection
});
</script>

<style scoped>
</style>
