<template>
  <!-- Official Manus live-status: lottie spinner + shimmering label -->
  <div class="flex items-center gap-2 text-sm">
    <LiveStatusCanvas :size="16" :active="true" />
    <span v-if="text" class="shimmer-text-tertiary">{{ text }}</span>
  </div>
</template>

<script setup lang="ts">
import LiveStatusCanvas from '@/components/LiveStatusCanvas.vue';

interface Props {
  text?: string
}

withDefaults(defineProps<Props>(), {
  text: undefined
})
</script>
