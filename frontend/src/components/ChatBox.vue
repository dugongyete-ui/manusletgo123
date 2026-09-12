<template>
    <div class="pb-3 relative bg-[var(--background-gray-main)]">
        <div
            class="flex flex-col gap-3 rounded-[22px] transition-all relative bg-[var(--fill-input-chat)] py-3 max-h-[480px] shadow-[0px_12px_32px_0px_rgba(0,0,0,0.08)] border border-black/8 dark:border-[var(--border-dark)]">
            <ChatBoxFiles ref="chatBoxFileListRef" :attachments="attachments" />
            <div class="overflow-y-auto pl-4 pr-2">
                <textarea
                    ref="textareaRef"
                    class="flex rounded-md border-input focus-visible:outline-none focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 flex-1 bg-transparent p-0 pt-[1px] border-0 focus-visible:ring-0 focus-visible:ring-offset-0 w-full placeholder:text-[var(--text-disable)] text-[15px] shadow-none resize-none"
                    :rows="rows" :value="modelValue"
                    @input="onInput"
                    @compositionstart="isComposing = true" @compositionend="isComposing = false"
                    @keydown="handleKeydown"
                    :placeholder="t('Give Dzeck a task to work on...')"
                    :style="{ minHeight: '46px', height: textareaHeight }"></textarea>
            </div>
            <footer class="flex flex-row justify-between w-full px-3">
                <div class="flex gap-2 pr-2 items-center">
                    <button @click="uploadFile"
                        class="rounded-full border border-[var(--border-main)] inline-flex items-center justify-center gap-1 clickable cursor-pointer text-xs text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-gray-main)] w-8 h-8 p-0 data-[popover-trigger]:bg-[var(--fill-tsp-gray-main)] shrink-0"
                        aria-expanded="false" aria-haspopup="dialog">
                        <Paperclip :size="16" />
                    </button>
                </div>
                <div class="flex gap-2">
                    <button v-if="!isRunning || sendEnabled || hideStopButton"
                        class="whitespace-nowrap text-sm font-medium focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 text-primary-foreground hover:bg-primary/90 p-0 w-8 h-8 rounded-full flex items-center justify-center transition-colors hover:opacity-90"
                        :class="!sendEnabled ? 'cursor-not-allowed bg-[var(--fill-tsp-white-dark)]' : 'cursor-pointer bg-[var(--Button-primary-black)]'"
                        @click="handleSubmit">
                        <SendIcon :disabled="!sendEnabled" />
                    </button>
                    <button v-else-if="!hideStopButton" @click="handleStop"
                        class="inline-flex items-center justify-center whitespace-nowrap text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring bg-[var(--Button-primary-black)] text-[var(--text-onblack)] gap-[4px] hover:opacity-90 rounded-full p-0 w-8 h-8">
                        <div class="w-[10px] h-[10px] bg-[var(--icon-onblack)] rounded-[2px]">
                        </div>
                    </button>
                </div>
            </footer>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import SendIcon from './icons/SendIcon.vue';
import { useI18n } from 'vue-i18n';
import ChatBoxFiles from './ChatBoxFiles.vue';
import { Paperclip } from 'lucide-vue-next';
import type { FileInfo } from '../api/file';

const { t } = useI18n();
const hasTextInput = ref(false);
const isComposing = ref(false);
const chatBoxFileListRef = ref();
const textareaRef = ref<HTMLTextAreaElement>();
const textareaHeight = ref('46px');
// ~17 lines at 22.5px line-height — comfortably shows 9+ paragraphs with
// blank lines between them while typing (user requirement: minimum 9 visible).
const TEXTAREA_MAX_HEIGHT = 400;

const autoResize = () => {
    const el = textareaRef.value;
    if (!el) return;
    // Reset to 'auto' so scrollHeight always measures the FULL content height
    // (never clamped by the previous explicit height).
    el.style.height = 'auto';
    const height = Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT);
    // Keep BOTH the reactive style binding and the DOM in sync. Writing the
    // DOM directly matters when the computed height is UNCHANGED: the old code
    // collapsed the box with a direct `height = '46px'` write and relied on the
    // ref changing to re-apply it — but when scrollHeight stayed the same the
    // ref never changed, no re-render happened, and the box stayed collapsed
    // at 2 rows forever while the user kept typing.
    textareaHeight.value = height + 'px';
    el.style.height = height + 'px';
};

const props = defineProps<{
    modelValue: string;
    rows: number;
    isRunning: boolean;
    attachments: FileInfo[];
    hideStopButton?: boolean;
    allowSendFilesOnly?: boolean;
}>();

const sendEnabled = computed(() => {
    const hasFiles = (props.attachments?.length ?? 0) > 0;
    const allUploaded = chatBoxFileListRef.value?.isAllUploaded ?? true;
    if (props.allowSendFilesOnly) {
        return hasTextInput.value || (hasFiles && allUploaded);
    }
    return hasTextInput.value && (!hasFiles || allUploaded);
});

const emit = defineEmits<{
    (e: 'update:modelValue', value: string): void;
    (e: 'submit'): void;
    (e: 'stop'): void;
}>();

const onInput = (event: Event) => {
    emit('update:modelValue', (event.target as HTMLTextAreaElement).value);
    autoResize();
};

// Touch-primary devices (phones/tablets): virtual keyboards have no Shift key,
// so Enter-to-send would make multi-line input impossible — Enter must insert
// a newline there and sending happens via the send button (Manus/ChatGPT
// mobile behaviour). Desktop keeps Enter=send, Shift+Enter=newline.
const isTouchDevice: boolean = (() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
    try {
        return window.matchMedia('(pointer: coarse)').matches;
    } catch {
        return false;
    }
})();

const handleKeydown = (event: KeyboardEvent) => {
    if (event.key !== 'Enter' || isComposing.value) return;
    if (isTouchDevice) {
        // Enter → newline (default textarea behaviour); send via the button.
        return;
    }
    // Desktop: Enter without any modifier → send
    if (!event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        if (sendEnabled.value) {
            handleSubmit();
        }
        return;
    }
    // Shift+Enter → new line (let browser insert naturally, do nothing here)
};

const handleSubmit = () => {
    if (!sendEnabled.value) return;
    emit('submit');
};

const handleStop = () => {
    emit('stop');
};

const uploadFile = () => {
    chatBoxFileListRef.value?.uploadFile();
};

watch(() => props.modelValue, (value) => {
    hasTextInput.value = value.trim() !== '';
    if (value === '') {
        textareaHeight.value = '46px';
        if (textareaRef.value) textareaRef.value.style.height = '46px';
    }
});
</script>
