<template>
  <SimpleBar>
    <div class="flex flex-col h-full flex-1 min-w-0 mx-auto w-full sm:min-w-[390px] px-5 max-w-[900px]">
      <!-- Header -->
      <div class="w-full pt-4 pb-4 px-5 sticky top-0 z-10 bg-[var(--background-gray-main)] mx-[-1.25]">
        <div class="flex items-center gap-2">
          <div @click="toggleLeftPanel" v-if="!isLeftPanelShow"
            class="flex h-7 w-7 items-center justify-center cursor-pointer rounded-md hover:bg-[var(--fill-tsp-gray-main)]">
            <PanelLeft class="size-5 text-[var(--icon-secondary)]" />
          </div>
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-full bg-[var(--fill-tsp-white-dark)] flex items-center justify-center">
              <Globe class="size-4 text-[var(--icon-primary)]" />
            </div>
            <div class="flex flex-col">
              <span class="text-[var(--text-primary)] text-lg font-medium leading-tight">{{ t('Community') }}</span>
              <span class="text-xs text-[var(--text-tertiary)]">{{ t('Tasks shared publicly by other users') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="flex flex-col items-center justify-center gap-3 py-20">
        <LoaderCircle class="animate-spin text-[var(--icon-secondary)]" :size="22" />
        <span class="text-sm text-[var(--text-secondary)]">{{ t('Loading community tasks') }}…</span>
      </div>

      <!-- Empty -->
      <div v-else-if="!sessions.length" class="flex flex-col items-center justify-center gap-4 py-20 px-4">
        <div class="flex items-center justify-center w-12 h-12 rounded-full bg-[var(--fill-tsp-gray-main)]">
          <Inbox class="text-[var(--icon-secondary)]" :size="24" />
        </div>
        <div class="text-base font-medium text-[var(--text-primary)]">{{ t('No shared tasks yet') }}</div>
        <div class="text-sm text-[var(--text-secondary)] text-center max-w-[420px] leading-relaxed">
          {{ t('Share one of your finished tasks and it will appear here for everyone to explore and fork.') }}
        </div>
        <button @click="router.push('/chat')"
          class="h-9 px-4 rounded-[10px] text-sm font-medium bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90">
          {{ t('Back to chats') }}
        </button>
      </div>

      <!-- Session cards -->
      <div v-else class="flex flex-col gap-2 pb-6">
        <button v-for="session in sessions" :key="session.session_id"
          @click="openSession(session)"
          class="flex flex-col gap-1.5 text-left p-4 rounded-2xl border border-[var(--border-main)] bg-[var(--background-white-main)] hover:bg-[var(--fill-tsp-white-light)] transition-colors group">
          <div class="flex items-center gap-2 min-w-0">
            <div class="w-7 h-7 rounded-lg bg-[var(--fill-tsp-white-dark)] flex items-center justify-center flex-shrink-0">
              <MessageCircle class="size-4 text-[var(--icon-primary)]" />
            </div>
            <span class="text-sm font-medium text-[var(--text-primary)] truncate flex-1">
              {{ session.title || t('Untitled task') }}
            </span>
            <GitFork class="size-4 text-[var(--icon-tertiary)] opacity-0 group-hover:opacity-100 flex-shrink-0" />
          </div>
          <p v-if="session.latest_message"
            class="text-[13px] text-[var(--text-tertiary)] line-clamp-2 leading-[19px] ps-9">
            {{ session.latest_message }}
          </p>
          <div v-if="session.latest_message_at" class="text-xs text-[var(--text-quaternary)] ps-9">
            {{ formatTime(session.latest_message_at) }}
          </div>
        </button>
      </div>
    </div>
  </SimpleBar>
</template>

<script setup lang="ts">
import SimpleBar from '../components/SimpleBar.vue';
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { getCommunitySessions, type CommunitySession } from '../api/profiles';
import { useLeftPanel } from '../composables/useLeftPanel';
import { showErrorToast } from '../utils/toast';
import {
  PanelLeft, Globe, Inbox, LoaderCircle, MessageCircle, GitFork,
} from 'lucide-vue-next';

const { t } = useI18n();
const router = useRouter();
const { toggleLeftPanel, isLeftPanelShow } = useLeftPanel();
const loading = ref(true);
const sessions = ref<CommunitySession[]>([]);

const openSession = (session: CommunitySession) => {
  // Shared sessions open in the public share view (works logged in or out).
  router.push(`/share/${session.session_id}`);
};

const formatTime = (ts: number): string => {
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return '';
  }
};

onMounted(async () => {
  try {
    sessions.value = await getCommunitySessions(50);
  } catch (error) {
    console.error('[community] failed to load shared sessions:', error);
    showErrorToast(t('Could not load community tasks, please try again later'));
    sessions.value = [];
  } finally {
    loading.value = false;
  }
});
</script>
