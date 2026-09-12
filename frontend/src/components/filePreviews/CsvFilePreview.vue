<template>
  <div class="flex flex-col h-full w-full min-h-0 overflow-hidden">
    <!-- metadata + controls -->
    <div class="px-4 pt-3 pb-2 flex flex-col gap-2 border-b border-[var(--border-light)] shrink-0">
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--text-tertiary)]">
        <span>{{ t('Rows') }}: <b class="text-[var(--text-primary)]">{{ dataRows }}</b></span>
        <span>{{ t('Columns') }}: <b class="text-[var(--text-primary)]">{{ headers.length }}</b></span>
        <span v-if="fileSizeText">{{ t('Size') }}: <b class="text-[var(--text-primary)]">{{ fileSizeText }}</b></span>
        <span v-if="truncated" class="text-amber-600">{{ t('Showing first {count} rows', { count: parsedRows }) }}</span>
      </div>
      <div v-if="warnings.length" class="flex flex-col gap-1">
        <div v-for="(w, i) in warnings" :key="i"
          class="text-xs rounded px-2 py-1 bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-400">
          {{ w }}
        </div>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <div class="relative flex-1 min-w-[140px] max-w-[280px]">
          <Search class="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--icon-tertiary)]" :size="14" />
          <input v-model="filterText" :placeholder="t('Search columns...')" :aria-label="t('Search columns...')"
            class="w-full h-8 pl-7 pr-2 rounded-lg border border-[var(--border-main)] bg-[var(--background-white-main)] text-xs text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--border-light)]" />
        </div>
        <button @click="copyCsv" :aria-label="t('Copy CSV')" :title="t('Copy CSV')"
          class="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--border-main)] text-xs text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-gray-main)]">
          <Copy :size="14" /> {{ t('Copy CSV') }}
        </button>
        <button @click="openRaw" :aria-label="t('Open raw text')" :title="t('Open raw text')"
          class="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--border-main)] text-xs text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-gray-main)]">
          <FileText :size="14" /> {{ t('Open raw text') }}
        </button>
        <button @click="download" :aria-label="t('Download')" :title="t('Download')"
          class="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--border-main)] text-xs text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-gray-main)]">
          <Download :size="14" /> {{ t('Download') }}
        </button>
      </div>
    </div>

    <!-- states -->
    <div v-if="loading" class="flex-1 flex items-center justify-center gap-2 text-sm text-[var(--text-secondary)]">
      <LoaderCircle class="animate-spin" :size="18" /> {{ t('Loading') }}…
    </div>
    <div v-else-if="error" class="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center">
      <AlertCircle class="text-[var(--icon-secondary)]" :size="28" />
      <div class="text-sm text-[var(--text-secondary)]">{{ error }}</div>
      <button @click="load" class="text-xs underline underline-offset-2 text-[var(--text-tertiary)]">{{ t('Retry') }}</button>
    </div>
    <div v-else-if="!rows.length" class="flex-1 flex items-center justify-center text-sm text-[var(--text-tertiary)]">
      {{ t('This file cannot be previewed directly. The file was found and is available to download.') }}
    </div>

    <!-- table -->
    <div v-else class="flex-1 min-h-0 overflow-auto" role="region" :aria-label="file.filename">
      <table class="min-w-full text-xs border-collapse">
        <thead class="sticky top-0 z-[1]">
          <tr>
            <th class="sticky left-0 z-[2] bg-[var(--background-gray-main)] border-b border-r border-[var(--border-light)] px-2 py-1.5 text-[var(--text-tertiary)] font-normal w-10">#</th>
            <th v-for="(h, ci) in headers" :key="ci" @click="sortBy(ci)"
              class="bg-[var(--background-gray-main)] border-b border-r border-[var(--border-light)] px-2 py-1.5 text-left font-medium text-[var(--text-secondary)] cursor-pointer select-none whitespace-nowrap hover:bg-[var(--fill-tsp-gray-main)]"
              :aria-sort="sortColumn === ci ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'">
              {{ h === '' ? '—' : h }}
              <span v-if="sortColumn === ci" class="ml-0.5">{{ sortDir === 'asc' ? '↑' : '↓' }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ri) in pageRows" :key="pageStart + ri"
            class="odd:bg-[var(--background-white-main)] even:bg-[var(--fill-tsp-white-main)]">
            <td class="sticky left-0 bg-inherit border-b border-r border-[var(--border-light)] px-2 py-1 text-[var(--text-tertiary)] whitespace-nowrap">{{ pageStart + ri + 1 }}</td>
            <td v-for="(cell, ci) in row" :key="ci"
              class="border-b border-r border-[var(--border-light)] px-2 py-1 text-[var(--text-primary)] whitespace-nowrap max-w-[280px] truncate"
              :class="{ 'text-[var(--text-tertiary)] italic': cell === '' }">
              <span v-if="cell !== ''" :title="cell">{{ cell }}</span>
              <span v-else>—</span>
            </td>
            <!-- pad missing cells so striped rows stay aligned -->
            <td v-for="ci in Math.max(0, headers.length - row.length)" :key="'pad' + ci"
              class="border-b border-r border-[var(--border-light)] px-2 py-1 text-[var(--text-tertiary)]">—</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- pagination -->
    <div v-if="pages > 1" class="shrink-0 px-4 py-2 border-t border-[var(--border-light)] flex items-center justify-between text-xs text-[var(--text-tertiary)]">
      <span>{{ t('Page {page} of {pages}', { page: page, pages }) }}</span>
      <div class="flex items-center gap-1.5">
        <button @click="page--" :disabled="page <= 1" :aria-label="t('Previous page')"
          class="h-7 px-2 rounded border border-[var(--border-main)] disabled:opacity-40 hover:bg-[var(--fill-tsp-gray-main)]">‹</button>
        <button @click="page++" :disabled="page >= pages" :aria-label="t('Next page')"
          class="h-7 px-2 rounded border border-[var(--border-main)] disabled:opacity-40 hover:bg-[var(--fill-tsp-gray-main)]">›</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { Search, Copy, FileText, Download, AlertCircle, LoaderCircle } from 'lucide-vue-next';
import type { FileInfo } from '../../api/file';
import { getFileDownloadUrl } from '../../api/file';
import { copyToClipboard } from '../../utils/dom';
import { formatFileSize } from '../../utils/fileType';
import { showErrorToast, showSuccessToast } from '../../utils/toast';

const { t } = useI18n();

const props = defineProps<{
  file: FileInfo;
}>();

const PAGE_SIZE = 50;
// Parse cap: protects the main thread on huge CSVs; the metadata bar states
// when the preview comes from a truncated prefix.
const MAX_PARSE_CHARS = 2_000_000;

const content = ref('');
const rawBlobUrl = ref('');
const fileSizeText = ref('');
const loading = ref(true);
const error = ref('');
const truncated = ref(false);

const rows = ref<string[][]>([]);
const headers = ref<string[]>([]);
const filterText = ref('');
const sortColumn = ref<number | null>(null);
const sortDir = ref<'asc' | 'desc'>('asc');
const page = ref(1);

// ── RFC4180-ish parser (quotes, escaped quotes, commas, newlines in fields) ─
const parseCsv = (text: string): string[][] => {
  const out: string[][] = [];
  let row: string[] = [];
  let field = '';
  let inQuotes = false;
  const n = text.length;
  for (let i = 0; i < n; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (i + 1 < n && text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field); field = '';
    } else if (c === '\n') {
      row.push(field); field = '';
      if (row.some(cell => cell !== '')) out.push(row);
      row = [];
    } else if (c !== '\r') {
      field += c;
    }
  }
  if (field !== '' || row.length) {
    row.push(field);
    if (row.some(cell => cell !== '')) out.push(row);
  }
  return out;
};

const analyze = () => {
  let text = content.value;
  truncated.value = text.length > MAX_PARSE_CHARS;
  if (truncated.value) text = text.slice(0, MAX_PARSE_CHARS);
  const parsed = parseCsv(text);
  if (!parsed.length) return;
  headers.value = parsed[0].map((h, i) => h.trim() || `#${i + 1}`);
  rows.value = parsed.slice(1);
  page.value = 1;
  sortColumn.value = null;
};

const warnings = computed<string[]>(() => {
  const w: string[] = [];
  if (!rows.value.length) return w;
  const expected = headers.value.length;
  const inconsistent = rows.value.filter(r => r.length !== expected).length;
  if (inconsistent) {
    w.push(`${t('Inconsistent rows')}: ${inconsistent} ${t('Rows').toLowerCase()} ≠ ${expected} ${t('Columns').toLowerCase()}`);
  }
  const emptyCells = rows.value.reduce(
    (acc, r) => acc + r.filter(c => c.trim() === '').length, 0
  );
  if (emptyCells) {
    w.push(`${t('Empty cells found')}: ${emptyCells}`);
  }
  if (truncated.value) {
    w.push(t('Showing first {count} rows', { count: rows.value.length }));
  }
  return w;
});

const dataRows = computed(() => rows.value.length);
const parsedRows = computed(() => rows.value.length);

const filteredRows = computed(() => {
  const q = filterText.value.trim().toLowerCase();
  let list = rows.value;
  if (q) {
    list = list.filter(r => r.some(c => c.toLowerCase().includes(q)));
  }
  if (sortColumn.value !== null) {
    const col = sortColumn.value;
    const dir = sortDir.value === 'asc' ? 1 : -1;
    list = [...list].sort((a, b) => {
      const av = (a[col] ?? '').trim();
      const bv = (b[col] ?? '').trim();
      const an = Number(av); const bn = Number(bv);
      const numeric = av !== '' && bv !== '' && !isNaN(an) && !isNaN(bn);
      if (numeric) return (an - bn) * dir;
      return av.localeCompare(bv) * dir;
    });
  }
  return list;
});

const pages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / PAGE_SIZE)));
const pageStart = computed(() => (page.value - 1) * PAGE_SIZE);
const pageRows = computed(() => filteredRows.value.slice(pageStart.value, pageStart.value + PAGE_SIZE));

watch(filterText, () => { page.value = 1; });
watch(() => filteredRows.value.length, () => {
  if (page.value > pages.value) page.value = pages.value;
});

const sortBy = (ci: number) => {
  if (sortColumn.value === ci) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc';
  } else {
    sortColumn.value = ci;
    sortDir.value = 'asc';
  }
};

const load = async () => {
  if (!props.file?.file_id) return;
  loading.value = true;
  error.value = '';
  try {
    const url = await getFileDownloadUrl(props.file);
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    fileSizeText.value = formatFileSize(blob.size);
    rawBlobUrl.value = URL.createObjectURL(blob);
    content.value = await blob.text();
    analyze();
  } catch (e: any) {
    console.error('Failed to load CSV content:', e);
    error.value = String(e?.message || e);
  } finally {
    loading.value = false;
  }
};

watch(() => props.file, async (file) => {
  if (rawBlobUrl.value) URL.revokeObjectURL(rawBlobUrl.value);
  rawBlobUrl.value = '';
  if (!file?.file_id) return;
  await load();
}, { immediate: true, deep: false });

const download = async () => {
  const url = await getFileDownloadUrl(props.file);
  window.open(url, '_blank');
};

const openRaw = () => {
  if (rawBlobUrl.value) window.open(rawBlobUrl.value, '_blank');
  else download();
};

const copyCsv = async () => {
  const ok = await copyToClipboard(content.value);
  if (ok) showSuccessToast(t('CSV copied to clipboard'));
  else showErrorToast(t('Failed to copy CSV'));
};
</script>
