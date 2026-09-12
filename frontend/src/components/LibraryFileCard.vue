<template>
  <!-- Grid card -->
  <div
    v-if="viewMode === 'grid'"
    role="button"
    tabindex="0"
    class="clickable relative flex cursor-pointer flex-col overflow-hidden rounded-[12px] border-[0.5px] border-[var(--border-dark)] bg-[var(--background-menu-white)] group hover:shadow-[0_7px_16px_0_var(--shadow-S)] text-left w-full"
    @click="emit('open')"
    @keydown.enter="emit('open')">
    <div class="flex items-center gap-2 px-2 py-[10px] relative border-b border-[var(--border-main)]">
      <div class="flex items-center justify-center flex-shrink-0 [&_svg]:w-6 [&_svg]:h-6">
        <component :is="fileType.icon" />
      </div>
      <div class="flex flex-1 min-w-0 items-center gap-1">
        <div class="min-w-0 flex-1 truncate text-[var(--text-primary)] text-sm" :title="displayName">
          <div class="flex min-w-0 max-w-full">
            <span class="truncate min-w-0">{{ baseName }}</span>
            <span v-if="extDot" class="flex-shrink-0">{{ extDot }}</span>
          </div>
        </div>
        <Star
          v-if="file.is_favorite"
          :size="16"
          class="flex-shrink-0"
          color="var(--function-warning)"
          fill="var(--function-warning)"
        />
      </div>
      <div class="flex items-center flex-shrink-0">
        <button
          type="button"
          class="flex size-7 items-center justify-center rounded-md text-[var(--icon-tertiary)] hover:bg-[var(--fill-tsp-gray-main)]"
          :class="menuOpen ? 'bg-[var(--fill-tsp-gray-main)]' : ''"
          :title="t('More options')"
          @click.stop="openMenu">
          <Ellipsis :size="16" />
        </button>
      </div>
    </div>

    <!-- Preview area -->
    <div class="aspect-[16/9] overflow-hidden relative bg-[var(--background-menu-white)]">
      <img
        v-if="previewKind === 'image' && previewUrl"
        :src="previewUrl"
        :alt="displayName"
        class="h-full w-full bg-[var(--fill-tsp-gray-dark)] object-top object-cover"
      />
      <pre
        v-else-if="previewKind === 'text' && previewText !== null"
        class="m-0 size-full overflow-hidden whitespace-pre p-[12px] text-[11px] leading-[15px] font-mono text-[var(--text-secondary)]"
        :style="{ background: 'var(--fill-tsp-white-main)' }"
        >{{ previewText }}</pre>
      <div
        v-else
        class="flex h-full w-full items-center justify-center bg-[var(--fill-tsp-white-main)]">
        <div class="[&_svg]:w-16 [&_svg]:h-16 opacity-90">
          <component :is="fileType.icon" />
        </div>
      </div>

      <button
        type="button"
        class="absolute bottom-2 start-2 z-20 size-7 rounded-[8px] items-center justify-center transition-opacity group-hover:pointer-events-auto group-hover:flex hidden bg-[var(--background-mask-black)] hover:opacity-80 hover:bg-[var(--background-mask-black)]"
        :title="t('Preview')"
        @click.stop="emit('open')">
        <Eye :size="16" class="text-[var(--icon-white)]" />
      </button>
    </div>
  </div>

  <!-- List row -->
  <div
    v-else
    role="button"
    tabindex="0"
    class="clickable group flex cursor-pointer items-center hover:bg-[var(--fill-tsp-white-light)] rounded-lg text-left"
    @click="emit('open')"
    @keydown.enter="emit('open')">
    <div class="w-full flex items-center border-b border-[var(--border-main)] gap-10 py-[12px] md:ps-[8px]">
      <div class="flex flex-1 min-w-0 items-center gap-3">
        <div class="flex-shrink-0 [&_svg]:w-6 [&_svg]:h-6">
          <component :is="fileType.icon" />
        </div>
        <div class="flex flex-1 min-w-0 items-center">
          <span class="min-w-0 truncate text-[14px] leading-[20px] text-[var(--text-primary)]">
            {{ displayName }}
          </span>
          <Star
            v-if="file.is_favorite"
            :size="16"
            class="flex-shrink-0 ms-1"
            color="var(--function-warning)"
            fill="var(--function-warning)"
          />
        </div>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <span
          v-if="file.latest_message_at"
          class="hidden md:block text-[12px] text-[var(--text-tertiary)]"
          >{{ timeLabel }}</span>
        <button
          type="button"
          class="clickable size-7 flex items-center justify-center rounded-md pointer-events-none opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 hover:bg-[var(--fill-tsp-white-main)]"
          :title="t('Preview')"
          @click.stop="emit('open')">
          <Eye :size="16" class="text-[var(--icon-secondary)]" />
        </button>
        <button
          type="button"
          class="flex size-7 shrink-0 items-center justify-center rounded-md text-[var(--icon-secondary)] hover:bg-[var(--fill-tsp-white-main)]"
          :class="menuOpen ? 'opacity-100 bg-[var(--fill-tsp-white-main)]' : 'opacity-0 group-hover:opacity-100'"
          :title="t('More options')"
          @click.stop="openMenu">
          <Ellipsis :size="16" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Ellipsis, Eye, ExternalLink, MessageSquarePlus, Star } from 'lucide-vue-next';
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { downloadFile, getFileDownloadUrl, type FileInfo } from '../api/file';
import { useContextMenu, type MenuItem } from '../composables/useContextMenu';
import type { LibraryFileItem } from '../types/response';
import { getFileType } from '../utils/fileType';
import { formatCustomTime } from '../utils/time';

const props = defineProps<{
  file: LibraryFileItem;
  viewMode: 'grid' | 'list';
}>();

const emit = defineEmits<{
  (e: 'open'): void
  (e: 'locate'): void
  (e: 'favorite', isFavorite: boolean): void
  (e: 'send'): void
}>();

const { t, locale } = useI18n();
const { showContextMenu } = useContextMenu();
const menuOpen = ref(false);

const previewUrl = ref<string | null>(null);
const previewText = ref<string | null>(null);
const previewKind = ref<'image' | 'text' | 'none'>('none');

const displayName = computed(() => props.file.filename || props.file.file_path || t('Untitled'));

const ext = computed(() => {
  const name = displayName.value;
  const i = name.lastIndexOf('.');
  if (i <= 0 || i === name.length - 1) return '';
  return name.slice(i + 1).toLowerCase();
});

const baseName = computed(() => {
  const name = displayName.value;
  const i = name.lastIndexOf('.');
  if (i <= 0) return name;
  return name.slice(0, i);
});

const extDot = computed(() => (ext.value ? `.${ext.value}` : ''));

const fileType = computed(() => getFileType(displayName.value));

const timeLabel = computed(() => {
  if (!props.file.latest_message_at) return '';
  return formatCustomTime(props.file.latest_message_at, t, locale.value);
});

const isImage = computed(() => {
  const ct = props.file.content_type || '';
  if (ct.startsWith('image/')) return true;
  return ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico'].includes(ext.value);
});

const isTextLike = computed(() => {
  const ct = props.file.content_type || '';
  if (ct.startsWith('text/') || ct.includes('json') || ct.includes('javascript') || ct.includes('xml')) {
    return true;
  }
  return [
    'py', 'js', 'ts', 'jsx', 'tsx', 'vue', 'java', 'c', 'cpp', 'go', 'rs', 'php',
    'rb', 'swift', 'kt', 'css', 'scss', 'html', 'xml', 'json', 'yaml', 'yml',
    'sql', 'toml', 'ini', 'md', 'txt', 'sh', 'bash',
  ].includes(ext.value);
});

const canSendToAgent = computed(() => !!props.file.file_id);

const openMenu = (event: MouseEvent) => {
  const target = event.currentTarget as HTMLElement;
  menuOpen.value = true;
  const favorited = !!props.file.is_favorite;

  const items: MenuItem[] = [
    { key: 'locate', label: t('Locate in task'), icon: ExternalLink },
    { key: 'favorite', label: favorited ? t('Unfavorite') : t('Add to favorites'), icon: Star },
  ];
  if (canSendToAgent.value) {
    items.push({ key: 'send', label: t('Send to Manus'), icon: MessageSquarePlus });
  }

  const menuId = props.file.file_id || `${props.file.session_id}:${displayName.value}`;
  showContextMenu(menuId, target, items, async (itemKey: string) => {
    if (itemKey === 'locate') emit('locate');
    else if (itemKey === 'favorite') emit('favorite', !favorited);
    else if (itemKey === 'send') emit('send');
  }, () => {
    menuOpen.value = false;
  });
};

onMounted(async () => {
  const fileId = props.file.file_id;
  if (!fileId) return;
  try {
    if (isImage.value) {
      const info: FileInfo = {
        file_id: fileId,
        filename: displayName.value,
        content_type: props.file.content_type || undefined,
        upload_date: props.file.upload_date || '',
      };
      previewUrl.value = await getFileDownloadUrl(info);
      previewKind.value = 'image';
      return;
    }
    if (isTextLike.value && (props.file.size == null || props.file.size < 200_000)) {
      const blob = await downloadFile(fileId);
      const text = await blob.text();
      previewText.value = text.slice(0, 1800);
      previewKind.value = 'text';
    }
  } catch {
    previewKind.value = 'none';
  }
});
</script>
