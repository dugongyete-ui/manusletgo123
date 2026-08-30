<template>
    <div class="vnc-toolbar-wrap" :class="{ collapsed }">
        <!-- Collapsed state: slim edge tab -->
        <button v-if="collapsed" class="vnc-toolbar-tab" @click="$emit('update:collapsed', false)"
            :aria-label="t('Expand toolbar')" :title="t('Expand toolbar')">
            <PanelLeftOpen :size="19" class="vnc-toolbar-icon" />
        </button>

        <!-- Expanded toolbar (Manus.im style: vertical dark rounded bar) -->
        <div v-else class="vnc-toolbar" role="toolbar" :aria-label="t('Session toolbar')">
            <!-- 1. Collapse toolbar -->
            <button class="vnc-tb-btn" @click="$emit('update:collapsed', true)"
                :aria-label="t('Collapse toolbar')" :title="t('Collapse toolbar')">
                <PanelLeftClose :size="19" class="vnc-toolbar-icon" />
            </button>

            <div class="vnc-tb-sep"></div>

            <!-- 2. Hand / pan mode -->
            <button class="vnc-tb-btn" :class="{ active: panMode }" @click="$emit('update:panMode', !panMode)"
                :aria-label="t('Pan mode')" :title="t('Pan mode — drag to move the view')" aria-pressed="true">
                <Hand :size="19" class="vnc-toolbar-icon" />
            </button>

            <!-- 3. Virtual keyboard -->
            <button class="vnc-tb-btn" :class="{ active: keyboardOpen }" @click="$emit('update:keyboardOpen', !keyboardOpen)"
                :aria-label="t('Virtual keyboard')" :title="t('Virtual keyboard')" aria-pressed="true">
                <Keyboard :size="19" class="vnc-toolbar-icon" />
            </button>

            <!-- 4. Open session in new window -->
            <button class="vnc-tb-btn" @click="$emit('open-window')"
                :aria-label="t('Open in new window')" :title="t('Open in new window')">
                <SquareArrowOutUpRight :size="19" class="vnc-toolbar-icon" />
            </button>

            <!-- 5. Mobile view mode -->
            <button class="vnc-tb-btn" :class="{ active: mobileMode }" @click="$emit('update:mobileMode', !mobileMode)"
                :aria-label="t('Mobile view')" :title="t('Mobile view')" aria-pressed="true">
                <Smartphone :size="19" class="vnc-toolbar-icon" />
            </button>
        </div>
    </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import {
    PanelLeftClose,
    PanelLeftOpen,
    Hand,
    Keyboard,
    SquareArrowOutUpRight,
    Smartphone,
} from 'lucide-vue-next';

const { t } = useI18n();

defineProps<{
    collapsed: boolean;
    panMode: boolean;
    keyboardOpen: boolean;
    mobileMode: boolean;
}>();

defineEmits<{
    'update:collapsed': [value: boolean];
    'update:panMode': [value: boolean];
    'update:keyboardOpen': [value: boolean];
    'update:mobileMode': [value: boolean];
    'open-window': [];
}>();
</script>

<style scoped>
.vnc-toolbar-wrap {
    position: absolute;
    left: 14px;
    top: 50%;
    transform: translateY(-50%);
    z-index: 30;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
}

/* Slim tab shown when toolbar is collapsed */
.vnc-toolbar-tab {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    padding: 0;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 10px;
    background: rgba(28, 28, 30, 0.92);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    cursor: pointer;
    transition: background 0.15s ease, transform 0.15s ease;
}

.vnc-toolbar-tab:hover {
    background: rgba(58, 58, 62, 0.95);
    transform: translateX(1px);
}

/* Main vertical toolbar */
.vnc-toolbar {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 7px 6px;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 14px;
    background: rgba(28, 28, 30, 0.92);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
}

.vnc-tb-btn {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: rgba(235, 235, 245, 0.86);
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
}

.vnc-tb-btn:hover {
    background: rgba(255, 255, 255, 0.12);
    color: #ffffff;
}

.vnc-tb-btn.active {
    background: #ffffff;
    color: #1c1c1e;
}

.vnc-tb-btn.active:hover {
    background: #f2f2f4;
    color: #1c1c1e;
}

.vnc-toolbar-icon {
    pointer-events: none;
    /* lucide uses 2px stroke; 1.8 renders closer to Manus thin icons */
    stroke-width: 1.8;
}

.vnc-tb-sep {
    width: 22px;
    height: 1px;
    margin: 3px 0;
    background: rgba(255, 255, 255, 0.16);
}

/* Tooltip on the right side of each button */
.vnc-tb-btn::after {
    content: attr(title);
    position: absolute;
    left: calc(100% + 12px);
    top: 50%;
    transform: translateY(-50%) translateX(-4px);
    white-space: nowrap;
    padding: 5px 9px;
    border-radius: 7px;
    background: rgba(18, 18, 20, 0.96);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: rgba(235, 235, 245, 0.95);
    font-size: 12px;
    line-height: 1;
    font-weight: 500;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.12s ease, transform 0.12s ease;
}

.vnc-tb-btn:hover::after {
    opacity: 1;
    transform: translateY(-50%) translateX(0);
}

/* Small screens: keep the toolbar but tuck it closer to the edge */
@media (max-width: 640px) {
    .vnc-toolbar-wrap {
        left: 8px;
    }
}
</style>
