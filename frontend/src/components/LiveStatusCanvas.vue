<template>
  <!-- Official LiveStatusLoading: lottie-web canvas, speed=2, size default 16 -->
  <div
    ref="containerRef"
    :class="className"
    :style="{ width: `${size}px`, height: `${size}px` }"
  />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import lottie, { type AnimationItem } from 'lottie-web'
import animationData from '@/assets/live-status-loading.json'

const props = withDefaults(
  defineProps<{
    size?: number
    className?: string
    /** Pause animation when false (e.g. completed step swaps away). */
    active?: boolean
  }>(),
  { size: 16, className: undefined, active: true },
)

const containerRef = ref<HTMLDivElement | null>(null)
let anim: AnimationItem | null = null

const destroy = () => {
  anim?.destroy()
  anim = null
}

const mount = () => {
  destroy()
  const el = containerRef.value
  if (!el || !props.active) return
  anim = lottie.loadAnimation({
    container: el,
    renderer: 'canvas',
    loop: true,
    autoplay: true,
    animationData,
    rendererSettings: {
      clearCanvas: true,
      preserveAspectRatio: 'xMidYMid meet',
    },
  })
  anim.setSpeed(2)
}

onMounted(() => {
  mount()
  // Battery/CPU: the loading animation used to keep redrawing its canvas via
  // rAF the whole time the tab was HIDDEN (a 20-40min agent run = 20-40min of
  // invisible canvas work heating the phone). Pause on hide, resume on show.
  document.addEventListener('visibilitychange', onVisibility)
})

const onVisibility = () => {
  if (document.hidden) destroy()
  else mount()
}

onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  destroy()
})
watch(() => props.active, (active) => {
  if (active) mount()
  else destroy()
})
</script>
