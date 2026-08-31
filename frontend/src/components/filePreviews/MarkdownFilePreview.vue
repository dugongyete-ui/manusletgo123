<template>
    <div class="flex flex-col overflow-hidden h-full">
        <!-- view toggle: rendered ↔ raw (P1) -->
        <div class="shrink-0 px-5 pt-3 pb-1 flex items-center gap-1.5 border-b border-[var(--border-light)]">
            <button @click="viewMode = 'rendered'" :aria-pressed="viewMode === 'rendered'"
                class="h-7 px-2.5 rounded-md text-xs font-medium transition-colors"
                :class="viewMode === 'rendered' ? 'bg-[var(--fill-tsp-gray-main)] text-[var(--text-primary)]' : 'text-[var(--text-tertiary)] hover:bg-[var(--fill-tsp-gray-main)]'">
                {{ t('Rendered view') }}</button>
            <button @click="viewMode = 'raw'" :aria-pressed="viewMode === 'raw'"
                class="h-7 px-2.5 rounded-md text-xs font-medium transition-colors"
                :class="viewMode === 'raw' ? 'bg-[var(--fill-tsp-gray-main)] text-[var(--text-primary)]' : 'text-[var(--text-tertiary)] hover:bg-[var(--fill-tsp-gray-main)]'">
                {{ t('Raw view') }}</button>
        </div>
        <!-- rendered -->
        <div v-if="viewMode === 'rendered'" class="relative overflow-auto flex-1 min-h-0 p-5">
            <div class="relative w-full max-w-[768px] mx-auto" style="min-height: calc(-200px + 100vh);">
                <div class="prose prose-gray max-w-none dark:prose-invert
                            [&_a]:text-blue-500 dark:[&_a]:text-blue-400 [&_a]:underline [&_a]:break-all
                            [&_pre]:bg-[var(--background-card)] [&_pre]:text-[var(--text-primary)]
                            [&_code]:bg-[var(--fill-tsp-gray-main)] [&_code]:text-[var(--text-primary)] [&_code]:rounded [&_code]:px-1"
                     v-html="renderedContent">
                </div>
            </div>
        </div>
        <!-- raw markdown source -->
        <div v-else class="relative overflow-auto flex-1 min-h-0 p-5">
            <pre class="w-full max-w-[768px] mx-auto text-sm text-[var(--text-primary)] whitespace-pre-wrap font-mono">{{ content || '…' }}</pre>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { marked, Renderer } from 'marked';
import DOMPurify from 'dompurify';
import type { FileInfo } from '../../api/file';
import { getFileDownloadUrl } from '../../api/file';

const { t } = useI18n();
const content = ref('');
const viewMode = ref<'rendered' | 'raw'>('rendered');

const props = defineProps<{
    file: FileInfo;
}>();

const renderer = new Renderer();
renderer.link = ({ href, title, text }: { href: string; title?: string | null; text: string }) => {
    const titleAttr = title ? ` title="${title}"` : '';
    return `<a href="${href}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`;
};

const renderedContent = computed(() => {
    if (!content.value) return '';
    try {
        const html = marked(content.value, {
            renderer,
            gfm: true,
            breaks: true,
        }) as string;
        return DOMPurify.sanitize(html, {
            ADD_ATTR: ['target', 'rel'],
            ADD_TAGS: ['iframe'],
        });
    } catch (error) {
        console.error('Failed to render markdown:', error);
        return `<pre class="text-sm text-[var(--text-secondary)] whitespace-pre-wrap">${content.value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`;
    }
});

watch(() => props.file, async (file) => {
    if (!file?.file_id) return;
    try {
        const url = await getFileDownloadUrl(file);
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        content.value = await response.text();
    } catch (error) {
        console.error('Failed to load file content:', error);
        content.value = '(Failed to load file content)';
    }
}, { immediate: true, deep: false });
</script>
