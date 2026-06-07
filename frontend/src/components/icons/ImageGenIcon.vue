<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
  >
    <rect x="3" y="3" width="18" height="18" rx="3" />
    <path d="M3 16l5-5 4 4 3-3 4 4" />
    <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" stroke="none" />
    <path d="M16 3v3M19 6h-3" stroke-width="1.8" />
  </svg>
</template>

<script setup lang="ts">
defineProps<{ size?: number | string }>();
</script>
