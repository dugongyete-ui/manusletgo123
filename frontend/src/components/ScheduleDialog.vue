<template>
  <span class="relative flex-shrink-0" aria-expanded="false" aria-haspopup="dialog">
    <Popover>
      <PopoverTrigger>
        <button :aria-label="t('Schedule this task')" :title="t('Schedule this task')"
          class="h-8 px-3 rounded-[100px] inline-flex items-center gap-1 clickable outline outline-1 outline-offset-[-1px] outline-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)] me-1.5">
          <Clock :size="15" color="var(--icon-secondary)" />
          <span class="text-[var(--text-secondary)] text-sm font-medium hidden sm:inline">{{ t('Schedule') }}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent>
        <div class="w-[400px] flex flex-col rounded-2xl bg-[var(--background-menu-white)] shadow-[0px_8px_32px_0px_var(--shadow-S),0px_0px_0px_1px_var(--border-light)] p-4 gap-3"
          style="max-width: calc(-16px + 100vw);">
          <div class="flex flex-col gap-1">
            <div class="text-sm font-medium text-[var(--text-primary)]">{{ t('Run this automatically') }}</div>
            <div class="text-[13px] text-[var(--text-tertiary)]">{{ t('The agent runs the prompt on a schedule — results land in this chat') }}</div>
          </div>

          <textarea v-model="prompt" rows="3" :placeholder="t('What should the agent do on every run?')"
            class="w-full rounded-xl border border-[var(--border-main)] bg-[var(--background-white-main)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--border-strong)] resize-none" />

          <div class="flex items-center gap-2">
            <span class="text-[13px] text-[var(--text-tertiary)] flex-shrink-0">{{ t('Every') }}</span>
            <select v-model="intervalMinutes"
              class="flex-1 h-9 rounded-lg border border-[var(--border-main)] bg-[var(--background-white-main)] px-2 text-sm text-[var(--text-primary)] outline-none">
              <option value="60">{{ t('1 hour') }}</option>
              <option value="360">{{ t('6 hours') }}</option>
              <option value="1440">{{ t('day') }}</option>
              <option value="10080">{{ t('week') }}</option>
            </select>
          </div>

          <button @click="createSchedule" :disabled="creating || !prompt.trim()"
            class="inline-flex items-center justify-center font-medium transition-colors hover:opacity-90 active:opacity-80 bg-[var(--Button-primary-black)] text-[var(--text-onblack)] h-[36px] px-[12px] rounded-[10px] gap-[6px] text-sm w-full disabled:opacity-50 disabled:cursor-not-allowed">
            <div v-if="creating" class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
            {{ creating ? t('Scheduling…') : t('Schedule it') }}
          </button>

          <!-- Existing schedules for this session -->
          <div v-if="sessionTasks.length" class="flex flex-col gap-2 border-t border-[var(--border-main)] pt-3">
            <div class="text-xs font-medium text-[var(--text-tertiary)]">{{ t('Scheduled runs') }}</div>
            <div v-for="task in sessionTasks" :key="task.task_id"
              class="flex items-center gap-2 rounded-xl border border-[var(--border-light)] p-2.5">
              <div class="flex-1 min-w-0">
                <p class="text-[13px] text-[var(--text-primary)] truncate" :title="task.prompt">{{ task.prompt }}</p>
                <p class="text-xs text-[var(--text-tertiary)]">
                  {{ intervalLabel(task) }} · {{ task.run_count }} {{ t('runs') }}
                </p>
              </div>
              <button @click="toggleTask(task)" :title="task.is_active ? t('Pause') : t('Resume')"
                class="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)]">
                <component :is="task.is_active ? PauseIcon : PlayIcon" :size="16" />
              </button>
              <button @click="deleteTask(task)" :title="t('Delete')"
                class="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)]">
                <Trash :size="16" />
              </button>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  </span>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, PropType } from 'vue';
import { useI18n } from 'vue-i18n';
import { Clock, Pause as PauseIcon, Play as PlayIcon, Trash } from 'lucide-vue-next';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  getScheduledTasks,
  createScheduledTask,
  toggleScheduledTask,
  deleteScheduledTask,
  type ScheduledTask,
} from '../api/scheduled';
import { showErrorToast, showSuccessToast } from '../utils/toast';

const { t } = useI18n();
const props = defineProps({
  sessionId: { type: String as PropType<string>, required: true },
});

const prompt = ref('');
const intervalMinutes = ref(1440);
const creating = ref(false);
const tasks = ref<ScheduledTask[]>([]);

const sessionTasks = computed(() =>
  tasks.value.filter((task) => task.session_id === props.sessionId)
);

const intervalLabel = (task: ScheduledTask): string => {
  const minutes = task.interval_minutes;
  if (minutes < 1440) return `${Math.round(minutes / 60)}h`;
  if (minutes < 10080) return t('day');
  return t('week');
};

const loadTasks = async () => {
  try {
    tasks.value = await getScheduledTasks();
  } catch {
    tasks.value = [];
  }
};

const createSchedule = async () => {
  if (!prompt.value.trim() || creating.value) return;
  creating.value = true;
  try {
    await createScheduledTask({
      prompt: prompt.value.trim(),
      session_id: props.sessionId,
      interval_minutes: intervalMinutes.value,
    });
    showSuccessToast(t('Scheduled — the agent will run this automatically'));
    prompt.value = '';
    await loadTasks();
  } catch (error) {
    console.error('[schedule] create failed:', error);
    showErrorToast(t('Could not schedule, please try again'));
  } finally {
    creating.value = false;
  }
};

const toggleTask = async (task: ScheduledTask) => {
  try {
    await toggleScheduledTask(task.task_id, !task.is_active);
    task.is_active = !task.is_active;
  } catch {
    showErrorToast(t('Could not update, please try again'));
  }
};

const deleteTask = async (task: ScheduledTask) => {
  try {
    await deleteScheduledTask(task.task_id);
    tasks.value = tasks.value.filter((x) => x.task_id !== task.task_id);
  } catch {
    showErrorToast(t('Could not delete, please try again'));
  }
};

onMounted(loadTasks);
</script>
