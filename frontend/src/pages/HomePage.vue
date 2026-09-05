<template>
  <SimpleBar>
    <div
      class="flex flex-col h-full flex-1 min-w-0 mx-auto w-full sm:min-w-[390px] px-5 items-start gap-2 relative max-w-full sm:max-w-full">
      <div class="w-full pt-4 pb-4 px-5 bg-[var(--background-gray-main)] sticky top-0 z-10 mx-[-1.25]">
        <div class="flex justify-between items-center w-full absolute left-0 right-0">
          <div class="h-8 relative z-20 overflow-hidden flex gap-2 items-center flex-shrink-0">
            <div class="relative flex items-center">
              <div @click="toggleLeftPanel" v-if="!isLeftPanelShow"
                class="flex h-7 w-7 items-center justify-center cursor-pointer rounded-md hover:bg-[var(--fill-tsp-gray-main)]">
                <PanelLeft class="size-5 text-[var(--icon-secondary)]" />
              </div>
            </div>
            <div class="flex">
              <DzeckLogoMark :size="30" />
              <DzeckLogoTextIcon />
            </div>
          </div>
          <div class="flex items-center gap-2">
            <div class="relative flex items-center" aria-expanded="false" aria-haspopup="dialog"
              @mouseenter="handleUserMenuEnter" @mouseleave="handleUserMenuLeave">
              <div class="relative flex items-center justify-center font-bold cursor-pointer flex-shrink-0">
                <div
                  class="relative flex items-center justify-center font-bold flex-shrink-0 rounded-full overflow-hidden"
                  style="width: 32px; height: 32px; font-size: 16px; color: var(--text-onblack); background-color: var(--text-brand);">
                  {{ avatarLetter }}</div>
              </div>
              <!-- User Menu -->
              <div v-if="showUserMenu" @mouseenter="handleUserMenuEnter" @mouseleave="handleUserMenuLeave"
                class="absolute top-full right-0 mt-1 mr-[-15px] z-50">
                <UserMenu />
              </div>
            </div>
          </div>
        </div>
        <div class="h-8"></div>
      </div>
      <!-- Greeting — vertically centered in the space between the header and
           the composer (ChatGPT / Claude / z.ai new-chat layout). -->
      <div class="w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] mx-auto my-auto">
        <div class="w-full flex pl-4 items-center justify-start pb-4">
          <span class="text-[var(--text-primary)] text-start font-serif text-[32px] leading-[40px]" :style="{
            fontFamily:
              'ui-serif, Georgia, Cambria, &quot;Times New Roman&quot;, Times, serif',
          }">
            {{ $t('Hello') }}, {{ currentUser?.fullname }}
            <br />
            <span class="text-[var(--text-tertiary)]">
              {{ $t('What can I do for you?') }}
            </span>
          </span>
        </div>
      </div>
      <!-- Composer — docked at the bottom of the screen. -->
      <div class="w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] mx-auto w-full pb-2">
        <!-- Agent profile picker (Manus InitAgentAgent equivalent): choose a
             persona for this new chat — built-in presets or your own. -->
        <div v-if="profiles.length" class="flex items-center gap-1.5 flex-wrap mb-2 px-1">
          <button v-for="profile in profiles" :key="profile.profile_id" @click="selectedProfileId = profile.profile_id"
            :class="selectedProfileId === profile.profile_id
              ? 'bg-[var(--Button-primary-black)] text-[var(--text-onblack)] border-transparent'
              : 'bg-[var(--fill-tsp-white-main)] text-[var(--text-secondary)] border-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)]'"
            class="h-7 px-3 rounded-full text-xs font-medium border inline-flex items-center gap-1.5 transition-colors"
            :title="profile.description || profile.instruction">
            <span v-if="profile.emoji">{{ profile.emoji }}</span>
            <span>{{ profile.name }}</span>
          </button>
        </div>
        <ChatBox :rows="2" v-model="message" @submit="handleSubmit" :isRunning="false" :attachments="attachments" />
      </div>
    </div>
  </SimpleBar>
</template>

<script setup lang="ts">
import SimpleBar from '../components/SimpleBar.vue';
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import ChatBox from '../components/ChatBox.vue';
import { createSession } from '../api/agent';
import { getAgentProfiles, type AgentProfile } from '../api/profiles';
import { showErrorToast } from '../utils/toast';
import { PanelLeft } from 'lucide-vue-next';
import DzeckLogoTextIcon from '../components/icons/DzeckLogoTextIcon.vue';
import DzeckLogoMark from '../components/icons/DzeckLogoMark.vue';
import type { FileInfo } from '../api/file';
import { useLeftPanel } from '../composables/useLeftPanel';
import { useFilePanel } from '../composables/useFilePanel';
import { useAuth } from '../composables/useAuth';
import UserMenu from '../components/UserMenu.vue';

const { t } = useI18n();
const router = useRouter();
const message = ref('');
const isSubmitting = ref(false);
const attachments = ref<FileInfo[]>([]);
const { toggleLeftPanel, isLeftPanelShow } = useLeftPanel();
const { hideFilePanel } = useFilePanel();
const { currentUser } = useAuth();

// Get first letter of user's fullname for avatar display
const avatarLetter = computed(() => {
  return currentUser.value?.fullname?.charAt(0)?.toUpperCase() || 'M';
});

// User menu state
const showUserMenu = ref(false);
const userMenuTimeout = ref<ReturnType<typeof setTimeout> | null>(null);

// Show user menu on hover
const handleUserMenuEnter = () => {
  if (userMenuTimeout.value) {
    clearTimeout(userMenuTimeout.value);
    userMenuTimeout.value = null;
  }
  showUserMenu.value = true;
};

// Hide user menu with delay
const handleUserMenuLeave = () => {
  userMenuTimeout.value = setTimeout(() => {
    showUserMenu.value = false;
  }, 200); // 200ms delay to allow moving to menu
};

const PENDING_KEY = 'dzeck_pending_prompt'

// ── Agent profiles (Manus InitAgentAgent) ─────────────────────────
const profiles = ref<AgentProfile[]>([]);
const selectedProfileId = ref<string | null>(null);
const loadProfiles = async () => {
  try {
    const list = await getAgentProfiles();
    profiles.value = list;
    // Default = the built-in general profile (or none when list is empty).
    const general = list.find((p) => p.profile_id === 'builtin-general');
    selectedProfileId.value = general ? general.profile_id : (list[0]?.profile_id ?? null);
  } catch {
    // Profiles unavailable — default behaviour, no picker shown.
    profiles.value = [];
  }
};

onMounted(() => {
  hideFilePanel();
  loadProfiles();
  const pending = localStorage.getItem(PENDING_KEY)
  if (pending) {
    message.value = pending
    localStorage.removeItem(PENDING_KEY)
    setTimeout(() => {
      handleSubmit()
    }, 300)
  }
});

const handleSubmit = async () => {
  if (message.value.trim() && !isSubmitting.value) {
    isSubmitting.value = true;

    try {
      // Create new Agent — with the selected profile persona when present.
      const session = await createSession(selectedProfileId.value);
      const sessionId = session.session_id;

      // Navigate to new route with session_id, passing initial message via state
      router.push({
        path: `/chat/${sessionId}`,
        state: {
          message: message.value, files: attachments.value.map((file: FileInfo) => ({
            file_id: file.file_id,
            filename: file.filename,
            content_type: file.content_type,
            size: file.size,
            upload_date: file.upload_date
          }))
        }
      });
    } catch (error) {
      console.error('Failed to create session:', error);
      showErrorToast(t('Failed to create session, please try again later'));
      isSubmitting.value = false;
    }
  }
};
</script>
