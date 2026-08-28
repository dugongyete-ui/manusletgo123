<template>
  <div :class="isLeftPanelShow ?
    'h-full flex flex-col' :
    'h-full flex flex-col fixed top-0 start-0 bottom-0 z-[1]'" :style="isLeftPanelShow ?
      'width: 300px; transition: width 0.28s cubic-bezier(0.4, 0, 0.2, 1);' :
      'width: 24px; transition: width 0.36s cubic-bezier(0.4, 0, 0.2, 1);'">
    <div
      :class="isLeftPanelShow ?
        'relative flex flex-col overflow-hidden bg-[var(--background-nav)] h-full opacity-100 translate-x-0' :
        'relative flex flex-col overflow-hidden bg-[var(--background-nav)] fixed top-1 start-1 bottom-1 z-[1] border-1 dark:border-[1px] border-[var(--border-main)] dark:border-[var(--border-light)] rounded-xl shadow-[0px_8px_32px_0px_rgba(0,0,0,0.16),0px_0px_0px_1px_rgba(0,0,0,0.06)] opacity-0 pointer-events-none -translate-x-10'"
      :style="(isLeftPanelShow ? 'width: 300px;' : 'width: 0px;') + ' transition: opacity 0.2s, transform 0.2s, width 0.2s;'">

      <!-- Tombol collapse di atas -->
      <div class="flex items-center px-3 h-[52px] flex-shrink-0">
        <div class="flex justify-between w-full px-1 pt-2">
          <div class="relative flex">
            <div
              class="flex h-7 w-7 items-center justify-center cursor-pointer hover:bg-[var(--fill-tsp-gray-main)] rounded-md"
              @click="toggleLeftPanel">
              <PanelLeft class="h-5 w-5 text-[var(--icon-secondary)]" />
            </div>
          </div>
        </div>
      </div>

      <!-- Area akses cepat -->
      <div class="flex flex-col flex-1 min-h-0 px-[8px] pb-0 gap-px">

        <!-- Tugas baru -->
        <div
          @click="handleNewTaskClick"
          class="flex items-center rounded-[10px] cursor-pointer transition-colors w-full gap-[12px] h-[36px] ps-[9px] pe-[2px]"
          :class="route.path === '/' ? 'bg-[var(--fill-tsp-white-main)]' : 'hover:bg-[var(--fill-tsp-white-light)]'">
          <div class="shrink-0 size-[18px] flex items-center justify-center">
            <SquarePen :size="18" class="text-[var(--text-primary)]" />
          </div>
          <div class="flex-1 min-w-0 flex gap-[4px] items-center text-[14px] text-[var(--text-primary)]">
            <span class="truncate">{{ t('New Task') }}</span>
          </div>
          <div class="shrink-0 flex items-center gap-1 pe-[6px]">
            <span class="flex text-[var(--text-tertiary)] justify-center items-center h-5 px-1 rounded-[4px] bg-[var(--fill-tsp-white-light)] border border-[var(--border-light)]">
              <Command :size="12" />
            </span>
            <span class="flex justify-center items-center w-5 h-5 px-1 rounded-[4px] bg-[var(--fill-tsp-white-light)] border border-[var(--border-light)] text-xs text-[var(--text-tertiary)]">
              K
            </span>
          </div>
        </div>

        <!-- Library -->
        <div
          @click="router.push('/library')"
          class="flex items-center rounded-[10px] cursor-pointer transition-colors w-full gap-[12px] h-[36px] ps-[9px] pe-[2px]"
          :class="route.path === '/library' ? 'bg-[var(--fill-tsp-white-main)]' : 'hover:bg-[var(--fill-tsp-white-light)]'">
          <div class="shrink-0 size-[18px] flex items-center justify-center">
            <LibraryBig :size="18" class="text-[var(--text-primary)]" />
          </div>
          <div class="flex-1 min-w-0 flex gap-[4px] items-center text-[14px] text-[var(--text-primary)]">
            <span class="truncate">{{ t('Library') }}</span>
          </div>
        </div>

        <!-- Container scroll -->
        <div class="flex flex-col flex-1 min-h-0 -mx-[8px] mt-[4px] overflow-hidden" style="padding-bottom: 48px;">
          <div class="w-full border-t border-[var(--border-main)] transition-opacity duration-200" :class="isListScrolled ? 'opacity-100' : 'opacity-0'"></div>

          <!-- Container scroll: judul + daftar scroll bersama -->
          <div ref="scrollContainerRef" class="flex flex-col flex-1 min-h-0 overflow-y-auto overflow-x-hidden pb-5 px-[8px]" @scroll="handleListScroll">

            <!-- Judul grup -->
            <div
              class="group flex items-center justify-between ps-[10px] pe-[2px] py-[2px] h-[36px] gap-[12px] flex-shrink-0 rounded-[10px]">
              <div class="flex items-center flex-1 min-w-0 gap-0.5 cursor-pointer hover:bg-[var(--fill-tsp-white-light)] transition-colors rounded-[10px] px-1 h-full" @click="isAllTasksCollapsed = !isAllTasksCollapsed">
                <span class="text-[13px] leading-[18px] text-[var(--text-tertiary)] font-medium min-w-0 truncate tracking-[-0.091px]">
                  {{ t('All Tasks') }}
                </span>
                <ChevronUp
                  :size="14"
                  class="shrink-0 transition-all opacity-0 group-hover:opacity-100"
                  :class="isAllTasksCollapsed ? 'rotate-180' : 'rotate-90'"
                  stroke="var(--icon-tertiary)" />
              </div>
              <button
                v-if="sessions.length > 0"
                @click="handleDeleteAll"
                :disabled="deletingAll"
                class="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center w-6 h-6 rounded-md hover:bg-[var(--fill-tsp-white-dark)] disabled:cursor-not-allowed"
                :title="t('Delete all chats')"
              >
                <Trash2 v-if="!deletingAll" :size="13" class="text-[var(--icon-tertiary)]" />
                <div v-else class="w-3 h-3 border border-[var(--icon-tertiary)] border-t-transparent rounded-full animate-spin"></div>
              </button>
            </div>

            <!-- Daftar sesi tanpa project -->
            <template v-if="!isAllTasksCollapsed">
              <div v-if="unassignedSessions.length > 0" class="flex flex-col gap-px">
                <SessionItem
                  v-for="session in unassignedSessions"
                  :key="session.session_id"
                  :session="session"
                  :projects="projects"
                  @deleted="handleSessionDeleted" />
              </div>
              <div v-else class="flex flex-col items-center justify-center gap-4 py-8">
                <div class="flex flex-col items-center gap-2 text-[var(--text-tertiary)]">
                  <MessageSquareDashed :size="38" />
                  <span class="text-sm font-medium">{{ t('Create a task to get started') }}</span>
                </div>
              </div>
            </template>

            <!-- Projects section -->
            <div
              class="group flex items-center justify-between ps-[10px] pe-[2px] py-[2px] h-[36px] gap-[12px] flex-shrink-0 rounded-[10px] mt-[8px]">
              <div class="flex items-center flex-1 min-w-0 gap-0.5 cursor-pointer hover:bg-[var(--fill-tsp-white-light)] transition-colors rounded-[10px] px-1 h-full" @click="isProjectsCollapsed = !isProjectsCollapsed">
                <span class="text-[13px] leading-[18px] text-[var(--text-tertiary)] font-medium min-w-0 truncate tracking-[-0.091px]">
                  {{ t('Projects') }}
                </span>
                <ChevronUp
                  :size="14"
                  class="shrink-0 transition-all opacity-0 group-hover:opacity-100"
                  :class="isProjectsCollapsed ? 'rotate-180' : 'rotate-90'"
                  stroke="var(--icon-tertiary)" />
              </div>
              <button
                @click="openNewProject"
                class="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center w-6 h-6 rounded-md hover:bg-[var(--fill-tsp-white-dark)]"
                :title="t('New Project')"
              >
                <Plus :size="14" class="text-[var(--icon-tertiary)]" />
              </button>
            </div>

            <template v-if="!isProjectsCollapsed">
              <div v-if="projects.length > 0" class="flex flex-col gap-px">
                <div v-for="project in projects" :key="project.project_id">
                  <!-- Project row -->
                  <div
                    @click="toggleProjectExpand(project.project_id)"
                    class="group/project flex items-center rounded-[10px] cursor-pointer transition-colors w-full gap-[12px] h-[36px] flex-shrink-0 ps-[9px] pe-[2px]"
                    :class="isProjectActive(project.project_id) ? 'bg-[var(--fill-tsp-white-main)]' : 'hover:bg-[var(--fill-tsp-white-light)]'">
                    <div class="shrink-0 size-[18px] flex items-center justify-center">
                      <Pin v-if="project.is_pinned" :size="14" class="text-[var(--text-primary)]" />
                      <Folder v-else :size="16" class="text-[var(--icon-secondary)]" />
                    </div>
                    <div class="flex-1 min-w-0 flex gap-[4px] items-center text-[14px]" :class="isProjectActive(project.project_id) ? 'text-[var(--text-primary)]' : 'text-[var(--text-primary)]'">
                      <span class="truncate" :title="project.name">{{ project.name }}</span>
                    </div>
                    <div class="shrink-0 flex items-center gap-1">
                      <div
                        @click.stop="handleProjectMenuClick($event, project)"
                        class="group-hover/project:flex hidden size-8 rounded-[8px] cursor-pointer items-center justify-center hover:bg-[var(--fill-tsp-white-light)]"
                        aria-expanded="false" aria-haspopup="dialog">
                        <Ellipsis :size="18" class="text-[var(--icon-tertiary)]" />
                      </div>
                      <ChevronUp
                        :size="14"
                        class="shrink-0 transition-all"
                        :class="expandedProjects.has(project.project_id) ? '' : 'rotate-90'"
                        stroke="var(--icon-tertiary)" />
                    </div>
                  </div>
                  <!-- Nested sessions -->
                  <div v-if="expandedProjects.has(project.project_id)" class="flex flex-col gap-px ps-[14px]">
                    <div
                      @click="router.push(`/project/${project.project_id}`)"
                      class="flex items-center rounded-[10px] cursor-pointer transition-colors w-full gap-[12px] h-[32px] flex-shrink-0 ps-[9px] pe-[2px] hover:bg-[var(--fill-tsp-white-light)]">
                      <div class="shrink-0 size-[18px] flex items-center justify-center">
                        <Plus :size="15" class="text-[var(--icon-tertiary)]" />
                      </div>
                      <div class="flex-1 min-w-0 text-[13px] text-[var(--text-tertiary)] truncate">
                        {{ t('New Task') }}
                      </div>
                    </div>
                    <SessionItem
                      v-for="session in sessionsOf(project.project_id)"
                      :key="session.session_id"
                      :session="session"
                      :projects="projects"
                      @deleted="handleSessionDeleted" />
                  </div>
                </div>
              </div>
              <div v-else class="flex flex-col items-center justify-center gap-2 py-4">
                <span class="text-[13px] text-[var(--text-tertiary)]">{{ t('No projects yet') }}</span>
                <button
                  @click="openNewProject"
                  class="flex items-center gap-1 rounded-[8px] border border-[var(--border-btn-main)] bg-[var(--Button-secondary-main)] px-2.5 py-1 text-[13px] text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-white-dark)]">
                  <Plus :size="14" color="var(--icon-secondary)" />
                  {{ t('New Project') }}
                </button>
              </div>
            </template>

          </div>
        </div>

      </div>

      <!-- Dark mode toggle — fixed bottom of panel -->
      <div class="absolute bottom-0 left-0 right-0 px-[8px] pb-[10px] pt-[8px] border-t border-[var(--border-main)] bg-[var(--background-nav)]">
        <button
          @click="toggleTheme"
          class="flex items-center w-full rounded-[10px] cursor-pointer transition-colors gap-[12px] h-[36px] ps-[9px] pe-[2px] hover:bg-[var(--fill-tsp-white-light)]"
          :title="theme === 'dark' ? t('Switch to light mode') : t('Switch to dark mode')"
        >
          <div class="shrink-0 size-[18px] flex items-center justify-center">
            <Sun v-if="theme === 'dark'" :size="18" class="text-[var(--icon-secondary)]" />
            <Moon v-else :size="18" class="text-[var(--icon-secondary)]" />
          </div>
          <div class="flex-1 min-w-0 text-[14px] text-[var(--text-secondary)] text-left truncate">
            {{ theme === 'dark' ? t('Light Mode') : t('Dark Mode') }}
          </div>
        </button>
      </div>
    </div>

    <!-- New / rename project dialog -->
    <div
      v-if="showProjectDialog"
      class="fixed inset-0 z-[1000] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/60 backdrop-blur-[4px]" @click="showProjectDialog = false" />
      <div
        role="dialog"
        class="relative z-10 flex w-[440px] max-w-[95%] flex-col overflow-hidden rounded-[20px] border border-white/5 bg-[var(--background-menu-white)] p-[16px]">
        <h3 class="text-[14px] font-[500] leading-[20px] text-[var(--text-primary)] mb-3">
          {{ renameProjectId ? t('Edit project') : t('New Project') }}
        </h3>
        <input
          ref="projectNameInputRef"
          v-model="projectNameDraft"
          type="text"
          class="w-full rounded-[8px] bg-[var(--fill-tsp-white-light)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-disable)]"
          :placeholder="t('Enter project name')"
          @keydown.enter="saveProjectDialog"
        />
        <div class="mt-4 flex shrink-0 items-center justify-end gap-[8px]">
          <button
            type="button"
            class="rounded-[10px] border border-[var(--border-btn-main)] bg-[var(--Button-secondary-main)] px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-white-dark)]"
            @click="showProjectDialog = false">
            {{ t('Cancel') }}
          </button>
          <button
            type="button"
            class="rounded-[10px] bg-[var(--Button-primary-black)] px-3 py-2 text-sm text-[var(--text-onblack)] hover:opacity-90 disabled:opacity-50"
            :disabled="savingProject"
            @click="saveProjectDialog">
            {{ t('Create') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { PanelLeft, SquarePen, Command, MessageSquareDashed, ChevronUp, Sun, Moon, Trash2, LibraryBig, Folder, Pin, Plus, Ellipsis, Pencil } from 'lucide-vue-next';
import { useTheme } from '../composables/useTheme';
import SessionItem from './SessionItem.vue';
import { useLeftPanel } from '../composables/useLeftPanel';
import { ref, computed, onMounted, watch, onUnmounted, nextTick } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getSessionsSSE, getSessions, deleteAllSessions } from '../api/agent';
import { getProjects, createProject, updateProject, deleteProject, pinProject } from '../api/project';
import { ListSessionItem, ProjectItem } from '../types/response';
import { useI18n } from 'vue-i18n';
import { useContextMenu, type MenuItem } from '../composables/useContextMenu';
import { useDialog } from '../composables/useDialog';
import { showSuccessToast, showErrorToast } from '../utils/toast';
import { eventBus } from '../utils/eventBus';

const { t } = useI18n()
const { theme, toggleTheme } = useTheme()
const { isLeftPanelShow, toggleLeftPanel } = useLeftPanel()
const route = useRoute()
const router = useRouter()
const { showContextMenu } = useContextMenu()
const { showConfirmDialog } = useDialog()

const sessions = ref<ListSessionItem[]>([])
const projects = ref<ProjectItem[]>([])
const cancelGetSessionsSSE = ref<(() => void) | null>(null)
const isAllTasksCollapsed = ref(false)
const isProjectsCollapsed = ref(false)
const isListScrolled = ref(false)
const scrollContainerRef = ref<HTMLElement | null>(null)
const deletingAll = ref(false)
const expandedProjects = ref(new Set<string>())

// Project dialog state
const showProjectDialog = ref(false)
const projectNameDraft = ref('')
const renameProjectId = ref<string | null>(null)
const savingProject = ref(false)
const projectNameInputRef = ref<HTMLInputElement | null>(null)

const unassignedSessions = computed(() =>
  sessions.value.filter((s) => !s.project_id),
)

const sessionsOf = (projectId: string) =>
  sessions.value.filter((s) => s.project_id === projectId)

const isProjectActive = (projectId: string) =>
  route.path === `/project/${projectId}`

const handleListScroll = () => {
  if (scrollContainerRef.value) {
    isListScrolled.value = scrollContainerRef.value.scrollTop > 0
  }
}

// Function to fetch sessions data
const updateSessions = async () => {
  try {
    const response = await getSessions()
    sessions.value = response.sessions
  } catch (error) {
    console.error('Failed to fetch sessions:', error)
  }
}

const updateProjects = async () => {
  try {
    const response = await getProjects()
    projects.value = response.projects
  } catch (error) {
    console.error('Failed to fetch projects:', error)
  }
}

// Function to fetch sessions data
const fetchSessions = async () => {
  try {
    if (cancelGetSessionsSSE.value) {
      cancelGetSessionsSSE.value()
      cancelGetSessionsSSE.value = null
    }
    cancelGetSessionsSSE.value = await getSessionsSSE({
      onOpen: () => {
        console.log('Sessions SSE opened')
      },
      onMessage: (event) => {
        sessions.value = event.data.sessions
      },
      onError: (error) => {
        console.error('Failed to fetch sessions:', error)
      },
      onClose: () => {
        console.log('Sessions SSE closed')
      }
    })
  } catch (error) {
    console.error('Failed to fetch sessions:', error)
  }
}

const handleNewTaskClick = () => {
  router.push('/')
}

const handleSessionDeleted = (sessionId: string) => {
  console.log('handleSessionDeleted', sessionId)
  sessions.value = sessions.value.filter(session => session.session_id !== sessionId);
}

const toggleProjectExpand = (projectId: string) => {
  const next = new Set(expandedProjects.value)
  if (next.has(projectId)) next.delete(projectId)
  else next.add(projectId)
  expandedProjects.value = next
}

const openNewProject = async () => {
  renameProjectId.value = null
  projectNameDraft.value = ''
  showProjectDialog.value = true
  await nextTick()
  projectNameInputRef.value?.focus()
}

const openRenameProject = async (project: ProjectItem) => {
  renameProjectId.value = project.project_id
  projectNameDraft.value = project.name
  showProjectDialog.value = true
  await nextTick()
  projectNameInputRef.value?.focus()
}

const saveProjectDialog = async () => {
  const name = projectNameDraft.value.trim()
  if (!name || savingProject.value) return
  savingProject.value = true
  try {
    if (renameProjectId.value) {
      await updateProject(renameProjectId.value, { name })
      showSuccessToast(t('Project updated successfully'))
    } else {
      const project = await createProject(name)
      expandedProjects.value = new Set([...expandedProjects.value, project.project_id])
      showSuccessToast(t('Project created'))
      router.push(`/project/${project.project_id}`)
    }
    await updateProjects()
    eventBus.emit('projects:changed')
    showProjectDialog.value = false
  } catch (error) {
    console.error('Failed to save project:', error)
    showErrorToast(t('Failed to update project'))
  } finally {
    savingProject.value = false
  }
}

const handleProjectMenuClick = (event: MouseEvent, project: ProjectItem) => {
  event.stopPropagation()
  const target = event.currentTarget as HTMLElement

  const items: MenuItem[] = [
    { key: 'pin', label: project.is_pinned ? t('Unpin') : t('Pin'), icon: Pin },
    { key: 'rename', label: t('Edit project'), icon: Pencil },
    { key: 'delete', label: t('Delete'), icon: Trash2, variant: 'danger' },
  ]

  showContextMenu(project.project_id, target, items, async (itemKey: string) => {
    if (itemKey === 'pin') {
      try {
        await pinProject(project.project_id, !project.is_pinned)
        await updateProjects()
        eventBus.emit('projects:changed')
      } catch (error) {
        console.error(error)
        showErrorToast(t('Failed to update project'))
      }
    } else if (itemKey === 'rename') {
      openRenameProject(project)
    } else if (itemKey === 'delete') {
      showConfirmDialog({
        title: t('Delete project?'),
        content: t('Tasks in this project will not be deleted, but they will be removed from the project.'),
        confirmText: t('Delete'),
        confirmType: 'danger',
        onConfirm: async () => {
          try {
            await deleteProject(project.project_id)
            await Promise.all([updateProjects(), updateSessions()])
            eventBus.emit('projects:changed')
            eventBus.emit('sessions:changed')
            showSuccessToast(t('Project deleted'))
            if (isProjectActive(project.project_id)) router.push('/')
          } catch (error) {
            console.error(error)
            showErrorToast(t('Failed to update project'))
          }
        }
      })
    }
  })
}

const handleDeleteAll = async () => {
  if (!confirm(t('Delete all chats? This cannot be undone.'))) return
  deletingAll.value = true
  try {
    await deleteAllSessions()
    sessions.value = []
    router.push('/')
  } catch (error) {
    console.error('Failed to delete all sessions:', error)
  } finally {
    deletingAll.value = false
  }
}

// Handle keyboard shortcuts
const handleKeydown = (event: KeyboardEvent) => {
  // Check for Command + K (Mac) or Ctrl + K (Windows/Linux)
  if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
    event.preventDefault()
    handleNewTaskClick()
  }
}

onMounted(async () => {
  // Initial fetch of sessions + projects
  fetchSessions()
  updateProjects()
  eventBus.on('projects:changed', updateProjects)

  // Add keyboard event listener
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  if (cancelGetSessionsSSE.value) {
    cancelGetSessionsSSE.value()
    cancelGetSessionsSSE.value = null
  }
  eventBus.off('projects:changed', updateProjects)

  // Remove keyboard event listener
  window.removeEventListener('keydown', handleKeydown)
})

watch(() => route.path, async () => {
  await updateSessions()
  // Auto-expand project group when opening a project page
  const match = route.path.match(/^\/project\/([^/]+)/)
  if (match) {
    isProjectsCollapsed.value = false
    expandedProjects.value = new Set([...expandedProjects.value, match[1]])
  }
})
</script>

<style scoped>
</style>
