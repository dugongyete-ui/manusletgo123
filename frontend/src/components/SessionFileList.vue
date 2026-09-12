<template>
    <div class="absolute z-[1000] pointer-events-auto" v-if="visible">
        <div class="w-full h-full bg-black/60 backdrop-blur-[4px] fixed inset-0 data-[state=open]:animate-dialog-bg-fade-in data-[state=closed]:animate-dialog-bg-fade-out"
            style="position: fixed; overflow: auto; inset: 0px;" @click="hideSessionFileList"></div>
        <div role="dialog"
            class="bg-[var(--background-menu-white)] rounded-[20px] border border-white/5 fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 max-w-[95%] max-h-[95%] overflow-auto data-[state=open]:animate-dialog-slide-in-from-bottom data-[state=closed]:animate-dialog-slide-out-to-bottom h-[680px] flex flex-col"
            style="width: 600px;">
            <div class="p-0">
                <h3 class="text-[var(--text-primary)] text-[18px] leading-[24px] font-semibold flex items-center"></h3>
            </div>
            <header class="flex items-center pt-6 pr-6 pl-6 pb-2.5">
                <h1 class="flex-1 text-[var(--text-primary)] text-lg font-semibold">{{ $t('All Files in This Task') }}</h1>
                <div class="flex items-center gap-4">
                    <div @click="hideSessionFileList"
                        class="flex h-7 w-7 items-center justify-center cursor-pointer hover:bg-[var(--fill-tsp-gray-main)] rounded-md">
                        <X class="size-5 text-[var(--icon-tertiary)]" />
                    </div>
                </div>
            </header>
            <div class="flex-1 min-h-0 flex flex-col">
                <div v-if="files.length > 0" class="flex-1 min-h-0 overflow-auto px-3 mt-4 pb-4">
                    <!-- Image grid for image files -->
                    <div v-if="imageFiles.length > 0" class="mb-4">
                        <p class="text-xs text-[var(--text-tertiary)] font-medium px-2 mb-2">Images</p>
                        <div class="grid grid-cols-2 gap-2 px-1">
                            <div v-for="file in imageFiles" :key="file.file_id"
                                class="relative group rounded-lg overflow-hidden border border-[var(--border-light)] bg-[var(--background-gray-main)] cursor-pointer"
                                @click="showFile(file)">
                                <SessionImageThumbnail :file="file" />
                                <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-2">
                                    <span class="text-white text-xs truncate flex-1">{{ file.filename }}</span>
                                    <div @click.stop="downloadFile(file)"
                                        class="flex items-center justify-center w-6 h-6 rounded bg-black/50 hover:bg-black/70 ml-1">
                                        <Download class="size-3.5 text-white" />
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- Non-image files grouped by semantic category
                         (Manus getSessionFilesV2: slides/tables/docs/code/archives). -->
                    <div v-for="group in groupedFiles" :key="group.category" class="mb-4">
                        <p class="text-xs text-[var(--text-tertiary)] font-medium px-2 mb-2">{{ group.label }}</p>
                        <div class="flex flex-col gap-1">
                            <div v-for="file in group.files" :key="file.file_id"
                                class="flex items-center gap-3 px-3 py-2.5 hover:bg-[var(--fill-tsp-gray-main)] transition-colors rounded-lg clickable">
                                <div class="relative flex items-center justify-center">
                                    <component :is="getFileType(file.filename).icon" />
                                </div>
                                <div @click="showFile(file)" class="flex flex-col gap-1 flex-grow flex-1 min-w-0">
                                    <div class="flex justify-between items-center flex-1 min-w-0">
                                        <div class="flex flex-col flex-1 min-w-0 max-w-[100%]">
                                            <div class="flex-1 min-w-0 flex gap-2 items-center">
                                                <span
                                                    class="inline-block whitespace-nowrap text-sm text-[var(--text-primary)]"
                                                    style="overflow: hidden; text-overflow: ellipsis;">{{ file.filename }}</span>
                                            </div>
                                            <span class="text-xs text-[var(--text-tertiary)]">{{
                                                formatRelativeTime(parseISODateTime(file.upload_date)) }}</span>
                                        </div>
                                        <div @click.stop="downloadFile(file)"
                                            class="flex items-center justify-center cursor-pointer hover:bg-[var(--fill-tsp-gray-main)] rounded-md w-8 h-8 text-[var(--icon-tertiary)]">
                                            <Download class="size-5 text-[var(--icon-tertiary)]" />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div v-else class="flex-1 min-h-0 flex flex-col items-center justify-center gap-3">
                    <File />
                    <p class="text-[var(--icon-tertiary)] text-[14px]">{{ $t('No Content') }}</p>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { X, Download, File } from 'lucide-vue-next';
import { ref, computed, watch } from 'vue';
import { useRoute } from 'vue-router';
import type { FileInfo } from '../api/file';
import { getFileDownloadUrl } from '../api/file';
import { getSessionFiles, getSharedSessionFiles } from '../api/agent';
import { formatRelativeTime, parseISODateTime } from '../utils/time';
import { getFileType } from '../utils/fileType';
import { useSessionFileList } from '../composables/useSessionFileList';
import { useFilePanel } from '../composables/useFilePanel';
import SessionImageThumbnail from './SessionImageThumbnail.vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const route = useRoute();
const files = ref<FileInfo[]>([]);

const { showFilePanel } = useFilePanel();
const { visible, hideSessionFileList, shared } = useSessionFileList();

const imageExtensions = new Set([
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico', 'tiff', 'tif', 'heic', 'heif',
]);

function isImageFile(filename: string): boolean {
    const ext = (filename ?? '').split('.').pop()?.toLowerCase() ?? '';
    return imageExtensions.has(ext);
}

const imageFiles = computed(() => files.value.filter(f => isImageFile(f.filename ?? '')));
const nonImageFiles = computed(() => files.value.filter(f => !isImageFile(f.filename ?? '')));

// ── Semantic categories (Manus getSessionFilesV2 equivalent) ─────────────
// The backend sends `category`; a local fallback keeps old payloads grouped
// too, so the panel never shows one flat undifferentiated list.
const CATEGORY_ORDER = ['slides', 'tables', 'docs', 'code', 'archives', 'other'] as const;
const CATEGORY_LABELS: Record<string, () => string> = {
    slides: () => t('Slides'),
    tables: () => t('Data'),
    docs: () => t('Documents'),
    code: () => t('Code'),
    archives: () => t('Archives'),
    other: () => t('Files'),
};

const LOCAL_CATEGORY_BY_EXT: Record<string, string> = {
    ppt: 'slides', pptx: 'slides', odp: 'slides',
    csv: 'tables', tsv: 'tables', xlsx: 'tables', xls: 'tables', ods: 'tables',
    md: 'docs', txt: 'docs', pdf: 'docs', doc: 'docs', docx: 'docs', rtf: 'docs',
    js: 'code', ts: 'code', tsx: 'code', jsx: 'code', py: 'code', html: 'code',
    css: 'code', vue: 'code', json: 'code', yaml: 'code', yml: 'code', sql: 'code', sh: 'code',
    zip: 'archives', tar: 'archives', gz: 'archives', tgz: 'archives', rar: 'archives', '7z': 'archives',
};

function fileCategory(file: FileInfo): string {
    const fromApi = (file as any).category as string | undefined;
    if (fromApi && CATEGORY_ORDER.includes(fromApi as any)) return fromApi;
    const ext = (file.filename ?? '').split('.').pop()?.toLowerCase() ?? '';
    return LOCAL_CATEGORY_BY_EXT[ext] ?? 'other';
}

const groupedFiles = computed(() => {
    const buckets = new Map<string, FileInfo[]>();
    for (const file of nonImageFiles.value) {
        const category = fileCategory(file);
        if (!buckets.has(category)) buckets.set(category, []);
        buckets.get(category)!.push(file);
    }
    return [...buckets.entries()]
        .sort((a, b) => CATEGORY_ORDER.indexOf(a[0] as any) - CATEGORY_ORDER.indexOf(b[0] as any))
        .map(([category, groupFiles]) => ({
            category,
            label: (CATEGORY_LABELS[category] ?? CATEGORY_LABELS.other)(),
            files: groupFiles,
        }));
});

const fetchFiles = async (sessionId: string) => {
    if (!sessionId) return;
    let response: FileInfo[] = [];
    if (shared.value) {
        response = await getSharedSessionFiles(sessionId);
    } else {
        response = await getSessionFiles(sessionId);
    }
    files.value = response;
};

const downloadFile = async (fileInfo: FileInfo) => {
    const url = await getFileDownloadUrl(fileInfo);
    window.open(url, '_blank');
};

const showFile = (file: FileInfo) => {
    showFilePanel(file);
    hideSessionFileList();
};

watch(visible, (newVisible) => {
    if (newVisible) {
        const sessionId = route.params.sessionId as string;
        if (sessionId) {
            fetchFiles(sessionId);
        }
    }
});
</script>
