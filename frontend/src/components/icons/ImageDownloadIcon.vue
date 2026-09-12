<template>
    <svg :width="size" :height="size" viewBox="0 0 19 18" fill="none" xmlns="http://www.w3.org/2000/svg"
        :style="{ minWidth: `${size}px`, minHeight: `${size}px` }">
        <g filter="url(#filter0_ii_img_dl)">
            <path
                d="M2 4.7C2 3.20883 3.20883 2 4.7 2H13.3C14.7912 2 16 3.20883 16 4.7V13.3C16 14.7912 14.7912 16 13.3 16H4.7C3.20883 16 2 14.7912 2 13.3V4.7Z"
                fill="url(#paint0_linear_img_dl)" />
        </g>
        <path
            d="M2.42857 4.7C2.42857 3.44552 3.44552 2.42857 4.7 2.42857H13.3C14.5545 2.42857 15.5714 3.44552 15.5714 4.7V13.3C15.5714 14.5545 14.5545 15.5714 13.3 15.5714H4.7C3.44552 15.5714 2.42857 14.5545 2.42857 13.3V4.7Z"
            stroke="#B9B9B7" stroke-width="0.857143" />
        <!-- Image frame (upper area) -->
        <rect x="3.5" y="3.5" width="8" height="6.2" rx="0.8" stroke="#535350" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" />
        <!-- Mountain peak inside frame -->
        <path d="M4.3 8.8L5.9 6.5L7.1 7.9L8 6.8L9.7 8.8" stroke="#ACACAC" stroke-width="0.9" stroke-linecap="round" stroke-linejoin="round" />
        <!-- Sun dot -->
        <circle cx="5.1" cy="5" r="0.55" fill="#ACACAC" />
        <!-- Download arrow: vertical line -->
        <path d="M13 10.2V14.5" stroke="#535350" stroke-width="1.15" stroke-linecap="round" />
        <!-- Arrow head -->
        <path d="M11 12.5L13 14.5L15 12.5" stroke="#535350" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round" />
        <defs>
            <filter id="filter0_ii_img_dl" x="1.5" y="1.5" width="15" height="15" filterUnits="userSpaceOnUse"
                color-interpolation-filters="sRGB">
                <feFlood flood-opacity="0" result="BackgroundImageFix" />
                <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
                <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"
                    result="hardAlpha" />
                <feOffset dx="1" dy="1" />
                <feGaussianBlur stdDeviation="0.25" />
                <feComposite in2="hardAlpha" operator="arithmetic" k2="-1" k3="1" />
                <feColorMatrix type="matrix" values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.6 0" />
                <feBlend mode="normal" in2="shape" result="effect1_innerShadow_img_dl" />
                <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"
                    result="hardAlpha" />
                <feOffset dx="-1" dy="-1" />
                <feGaussianBlur stdDeviation="0.25" />
                <feComposite in2="hardAlpha" operator="arithmetic" k2="-1" k3="1" />
                <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.08 0" />
                <feBlend mode="normal" in2="effect1_innerShadow_img_dl" result="effect2_innerShadow_img_dl" />
            </filter>
            <linearGradient id="paint0_linear_img_dl" x1="9" y1="2" x2="9" y2="16" gradientUnits="userSpaceOnUse">
                <stop stop-color="white" stop-opacity="0" />
                <stop offset="1" stop-opacity="0.16" />
            </linearGradient>
        </defs>
    </svg>
</template>

<script setup lang="ts">
defineProps({
    size: { type: Number, default: 21 }
});
</script>
