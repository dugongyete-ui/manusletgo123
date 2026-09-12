<template>
  <div v-if="items.length"
    class="flex flex-col gap-2 rounded-2xl border border-[var(--border-main)] bg-[var(--fill-tsp-white-main)] p-4 mx-auto w-full">
    <div class="flex items-center gap-2 mb-1">
      <div
        class="w-7 h-7 rounded-full bg-[var(--fill-tsp-white-dark)] flex items-center justify-center flex-shrink-0">
        <Sparkles class="size-4 text-[var(--icon-primary)]" />
      </div>
      <div class="flex flex-col min-w-0">
        <div class="text-sm font-medium text-[var(--text-primary)]">{{ t('Learned from this task') }}</div>
        <div class="text-xs text-[var(--text-tertiary)]">{{ t('Accept what should carry over to future tasks') }}</div>
      </div>
    </div>

    <div v-for="(item, index) in items" :key="item.id || index"
      class="flex flex-col gap-2 rounded-xl border border-[var(--border-light)] bg-[var(--background-white-main)] p-3">
      <div class="flex items-start gap-2">
        <span class="text-[13px] leading-[20px] text-[var(--text-primary)] flex-1 min-w-0">{{ item.text }}</span>
        <span v-if="item.status !== 'pending'"
          class="text-xs px-2 py-0.5 rounded-full flex-shrink-0"
          :class="item.status === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-[var(--fill-tsp-gray-main)] text-[var(--text-tertiary)]'">
          {{ item.status === 'active' ? t('Saved') : t('Dismissed') }}
        </span>
      </div>
      <div v-if="item.status === 'pending'" class="flex items-center gap-2">
        <button @click="accept(item)"
          class="h-7 px-3 rounded-lg text-xs font-medium bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90 active:opacity-80">
          {{ t('Accept') }}
        </button>
        <button @click="reject(item)"
          class="h-7 px-3 rounded-lg text-xs font-medium border border-[var(--border-btn-main)] text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-white-light)]">
          {{ t('Dismiss') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { PropType } from 'vue';
import { Sparkles } from 'lucide-vue-next';
import { useI18n } from 'vue-i18n';
import { setKnowledgeStatus } from '../api/knowledge';
import { showErrorToast } from '../utils/toast';

const { t } = useI18n();

export interface PendingLearning {
  id: string | null;
  text: string;
  status: 'pending' | 'active' | 'rejected';
}

const props = defineProps({
  items: {
    type: Array as PropType<PendingLearning[]>,
    default: () => [],
  },
});

async function accept(item: PendingLearning) {
  if (!item.id) {
    item.status = 'active';
    return;
  }
  try {
    await setKnowledgeStatus(item.id, 'active');
    item.status = 'active';
  } catch {
    showErrorToast(t('Could not save, please try again'));
  }
}

async function reject(item: PendingLearning) {
  if (!item.id) {
    item.status = 'rejected';
    return;
  }
  try {
    await setKnowledgeStatus(item.id, 'rejected');
    item.status = 'rejected';
  } catch {
    showErrorToast(t('Could not save, please try again'));
  }
}
</script>
