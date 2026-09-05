<template>
  <div
    @click="handleSessionClick"
    class="group flex items-center rounded-[10px] cursor-pointer transition-colors w-full gap-[12px] h-[36px] flex-shrink-0 pointer-events-auto ps-[9px] pe-[2px] active:bg-[var(--fill-tsp-white-dark)]"
    :class="isCurrentSession ? 'bg-[var(--fill-tsp-white-main)]' : 'hover:bg-[var(--fill-tsp-white-light)]'">

    <!-- Ikon status -->
    <div class="shrink-0 size-[18px] flex items-center justify-center relative">
      <template v-if="session.status === SessionStatus.RUNNING || session.status === SessionStatus.PENDING">
        <div class="border rounded-full animate-spin" style="width: 18px; height: 18px; border-width: 2px; border-color: var(--fill-blue); border-top-color: var(--icon-brand);"></div>
      </template>
      <!-- Queued: task/sandbox still booting — softer pulse so the user sees
           "waiting to start" instead of an ambiguous full spinner. -->
      <template v-else-if="session.status === SessionStatus.IN_QUEUE">
        <div class="border rounded-full animate-pulse" style="width: 18px; height: 18px; border-width: 2px; border-color: var(--fill-blue); border-top-color: var(--fill-blue);"></div>
      </template>
      <template v-else-if="session.status === SessionStatus.WAITING">
        <svg height="18" width="18" fill="none" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
          <g clip-path="url(#waiting-clip)">
            <circle cx="8" cy="8" r="6.5" stroke="var(--function-warning)" stroke-dasharray="2.44 1.62" stroke-width="1.5"></circle>
          </g>
          <defs><clipPath id="waiting-clip"><rect height="16" width="16" fill="white"></rect></clipPath></defs>
        </svg>
      </template>
      <!-- Failed: honest terminal state — clear warning icon, never hidden
           behind the normal "finished chat" bubble. -->
      <template v-else-if="session.status === SessionStatus.FAILED">
        <AlertCircle class="size-[18px] text-[var(--function-warning)]" />
      </template>
      <template v-else>
        <MessageCircle class="size-[18px] text-[var(--icon-tertiary)]" />
      </template>

    </div>

    <!-- Judul -->
    <div class="flex-1 min-w-0 flex gap-[4px] items-center text-[14px] text-[var(--text-primary)]">
      <span class="truncate" :title="session.title || t('New Chat')">
        {{ session.title || t('New Chat') }}
      </span>
    </div>

    <!-- Menu titik tiga -->
    <div class="shrink-0 flex items-center gap-1">
      <div
        @click.stop="handleSessionMenuClick"
        class="group-hover:flex hidden size-8 rounded-[8px] cursor-pointer items-center justify-center hover:bg-[var(--fill-tsp-white-light)]"
        :class="isContextMenuOpen ? '!flex bg-[var(--fill-tsp-white-light)]' : ''"
        aria-expanded="false" aria-haspopup="dialog">
        <Ellipsis :size="18" class="text-[var(--icon-tertiary)]" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Ellipsis, MessageCircle, FolderInput, Trash, AlertCircle } from 'lucide-vue-next';
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';
import { ListSessionItem, ProjectItem, SessionStatus } from '../types/response';
import { useContextMenu, createDangerMenuItem, type MenuItem } from '../composables/useContextMenu';
import { useDialog } from '../composables/useDialog';
import { deleteSession, moveSessionProject } from '../api/agent';
import { showSuccessToast, showErrorToast } from '../utils/toast';
import { eventBus } from '../utils/eventBus';

interface Props {
  session: ListSessionItem;
  projects?: ProjectItem[];
}

const props = defineProps<Props>();

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const { showContextMenu } = useContextMenu();
const { showConfirmDialog } = useDialog();
const isContextMenuOpen = ref(false);

const emit = defineEmits<{
  (e: 'deleted', sessionId: string): void
  (e: 'moved', sessionId: string, projectId: string | null): void
}>();

const currentSessionId = computed(() => {
  return route.params.sessionId as string;
});

const isCurrentSession = computed(() => {
  return currentSessionId.value === props.session.session_id;
});

const handleSessionClick = () => {
  router.push(`/chat/${props.session.session_id}`);
};

const moveToProject = async (projectId: string | null) => {
  try {
    await moveSessionProject(props.session.session_id, projectId);
    showSuccessToast(projectId ? t('Task moved') : t('Task removed from project'));
    emit('moved', props.session.session_id, projectId);
    eventBus.emit('sessions:changed');
  } catch (error) {
    console.error('Failed to move session:', error);
    showErrorToast(t('Failed to move task'));
  }
};

const handleSessionMenuClick = (event: MouseEvent) => {
  event.stopPropagation();

  const target = event.currentTarget as HTMLElement;
  isContextMenuOpen.value = true;

  const items: MenuItem[] = [];

  // Move-to-project submenu entries (only when projects are provided)
  if (props.projects && props.projects.length > 0) {
    for (const project of props.projects) {
      if (project.project_id === props.session.project_id) continue;
      items.push({
        key: `move:${project.project_id}`,
        label: `${t('Move to')} ${project.name}`,
        icon: FolderInput,
      });
    }
    if (props.session.project_id) {
      items.push({
        key: 'move:null',
        label: t('Remove from project'),
        icon: FolderInput,
      });
    }
  }

  items.push(createDangerMenuItem('delete', t('Delete'), { icon: Trash }));

  showContextMenu(props.session.session_id, target, items, (itemKey: string, _: string) => {
    if (itemKey.startsWith('move:')) {
      const targetId = itemKey.slice(5);
      moveToProject(targetId === 'null' ? null : targetId);
    } else if (itemKey === 'delete') {
      showConfirmDialog({
        title: t('Are you sure you want to delete this session?'),
        content: t('The chat history of this session cannot be recovered after deletion.'),
        confirmText: t('Delete'),
        cancelText: t('Cancel'),
        confirmType: 'danger',
        onConfirm: () => {
          deleteSession(props.session.session_id).then(() => {
            showSuccessToast(t('Deleted successfully'));
            emit('deleted', props.session.session_id);
          }).catch(() => {
            showErrorToast(t('Failed to delete session'));
          });
          if (isCurrentSession.value) {
            router.push('/');
          }
        }
      })
    }
  }, (_: string) => {
    isContextMenuOpen.value = false;
  });
};
</script>
