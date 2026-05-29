<template>
    <svg xmlns="http://www.w3.org/2000/svg" :width="width" :height="height" viewBox="0 0 88 38" fill="none">
        <text
            y="28"
            font-family="ui-serif, Georgia, Cambria, 'Times New Roman', Times, serif"
            font-size="26"
            font-weight="500"
            fill="var(--logo-color)"
            letter-spacing="-0.8">Dzeck</text>
    </svg>
</template>
<script setup lang="ts">
defineProps({
    width: {
        type: [String, Number],
        default: 88
    },
    height: {
        type: [String, Number],
        default: 38
    }
})
</script>
