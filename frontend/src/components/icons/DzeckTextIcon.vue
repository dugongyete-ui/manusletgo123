<template>
    <svg height="16" :width="width" viewBox="0 0 52 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <text
            y="13"
            font-family="ui-serif, Georgia, Cambria, 'Times New Roman', Times, serif"
            font-size="14"
            font-weight="500"
            fill="var(--logo-color)"
            letter-spacing="-0.3">Dzeck</text>
    </svg>
</template>
<script setup lang="ts">
defineProps({
    width: {
        type: [String, Number],
        default: 52
    }
})
</script>
