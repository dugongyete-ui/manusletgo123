<template>
  <div class="w-full max-w-[768px] mx-auto my-2 rounded-xl border"
    :class="overall === 'pass' ? 'border-emerald-200 dark:border-emerald-900' : 'border-amber-200 dark:border-amber-900'"
    style="background: var(--background-white-main);">
    <!-- header -->
    <button @click="expanded = !expanded" class="w-full flex items-center gap-2.5 px-4 py-3 text-left"
      :aria-expanded="expanded">
      <div class="flex items-center justify-center w-7 h-7 rounded-full shrink-0"
        :class="overall === 'pass' ? 'bg-emerald-50 dark:bg-emerald-950' : 'bg-amber-50 dark:bg-amber-950'">
        <CheckCircle2 v-if="overall === 'pass'" class="text-emerald-600" :size="16" />
        <AlertTriangle v-else class="text-amber-600" :size="16" />
      </div>
      <div class="flex-1 min-w-0">
        <div class="text-sm font-medium text-[var(--text-primary)]">
          {{ overall === 'pass' ? t('Task validation') : t('Completed with warnings') }}
        </div>
        <div class="text-xs text-[var(--text-tertiary)] truncate">
          {{ t('Overall') }}: {{ overall === 'pass' ? t('PASS') : t('NEEDS_REVIEW') }}
          <span v-if="result.warnings"> · {{ t('Warnings') }}: {{ result.warnings }}</span>
          <span v-if="result.unresolved_errors"> · {{ t('Unresolved errors') }}: {{ result.unresolved_errors }}</span>
        </div>
      </div>
      <ChevronDown class="text-[var(--icon-secondary)] transition-transform shrink-0"
        :class="expanded ? 'rotate-180' : ''" :size="18" />
    </button>

    <!-- body -->
    <div v-if="expanded" class="px-4 pb-4 flex flex-col gap-4 border-t border-[var(--border-light)] pt-3">
      <!-- checks -->
      <div class="flex flex-col gap-1.5">
        <div v-for="check in labeledChecks" :key="check.key" class="flex items-start gap-2 text-xs">
          <span class="shrink-0 mt-[1px] inline-flex items-center justify-center min-w-[44px] h-[18px] px-1.5 rounded font-medium"
            :class="stateClass(check.state)">
            {{ stateLabel(check.state) }}
          </span>
          <div class="min-w-0">
            <span class="text-[var(--text-secondary)] font-medium">{{ check.label }}</span>
            <span class="text-[var(--text-tertiary)]"> — {{ check.detail }}</span>
          </div>
        </div>
      </div>

      <!-- execution summary -->
      <div v-if="hasSummary" class="flex flex-col gap-1">
        <div class="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">{{ t('Execution summary') }}</div>
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs">
          <div><span class="text-[var(--text-tertiary)]">{{ t('Stages') }}:</span> <span class="text-[var(--text-primary)]">{{ s.steps_completed }}/{{ s.total_steps }}</span></div>
          <div><span class="text-[var(--text-tertiary)]">{{ t('Tool calls') }}:</span> <span class="text-[var(--text-primary)]">{{ s.tool_calls_succeeded }}/{{ s.tool_calls_total }}</span></div>
          <div v-if="s.tool_calls_failed"><span class="text-[var(--text-tertiary)]">{{ t('Failed') }}:</span> <span class="text-[var(--text-primary)]">{{ s.tool_calls_failed }}</span></div>
          <div v-if="s.files_created"><span class="text-[var(--text-tertiary)]">{{ t('Files created') }}:</span> <span class="text-[var(--text-primary)]">{{ s.files_created }}</span></div>
          <div v-if="s.files_updated"><span class="text-[var(--text-tertiary)]">{{ t('Files updated') }}:</span> <span class="text-[var(--text-primary)]">{{ s.files_updated }}</span></div>
          <div v-if="duration"><span class="text-[var(--text-tertiary)]">{{ t('Duration') }}:</span> <span class="text-[var(--text-primary)]">{{ duration }}</span></div>
        </div>
      </div>

      <!-- evidence register -->
      <div v-if="result.evidence.length" class="flex flex-col gap-1.5">
        <div class="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide flex items-center gap-1.5">
          {{ t('Evidence register') }}
          <span class="text-[var(--text-tertiary)] font-normal">({{ result.evidence.length }})</span>
        </div>
        <div class="flex flex-col gap-1.5 max-h-[280px] overflow-y-auto pr-1">
          <div v-for="ev in result.evidence" :key="ev.id"
            class="flex items-start gap-2 rounded-lg bg-[var(--fill-tsp-gray-main)] px-2.5 py-1.5 text-xs">
            <span class="shrink-0 font-mono text-[10px] text-[var(--text-tertiary)] mt-[2px]">{{ ev.id }}</span>
            <div class="min-w-0 flex-1">
              <a :href="ev.url" target="_blank" rel="noopener noreferrer"
                class="text-[var(--text-primary)] hover:underline break-all line-clamp-2">{{ ev.title || ev.url }}</a>
              <div class="text-[10px] text-[var(--text-tertiary)] flex items-center gap-2 flex-wrap">
                <span class="uppercase">{{ ev.source }}</span>
                <span v-if="ev.site_name">{{ ev.site_name }}</span>
                <span v-if="!ev.verified" class="text-amber-600">{{ t('Unverified') }}</span>
              </div>
              <div v-if="ev.redirected" class="mt-1 rounded bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-400 px-2 py-1 text-[10px] leading-relaxed">
                {{ t('Redirect warning') }}: {{ t('The target URL differs from the URL that was actually opened. Please verify whether this redirect is official before using the data as evidence.') }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { CheckCircle2, AlertTriangle, ChevronDown } from 'lucide-vue-next';
import type { ValidationResultData, ValidationCheck, CheckState } from '../types/event';

const { t } = useI18n();

const props = defineProps<{
  result: ValidationResultData;
}>();

const expanded = ref(true);
const overall = computed(() => props.result.overall);
const s = computed(() => props.result.summary);

const hasSummary = computed(() =>
  s.value.total_steps > 0 || s.value.tool_calls_total > 0 || s.value.files_created > 0
);

const duration = computed(() => {
  const d = s.value.duration_seconds;
  if (!d || d <= 0) return '';
  if (d < 60) return `${Math.round(d)}s`;
  if (d < 3600) return `${Math.floor(d / 60)}m ${Math.round(d % 60)}s`;
  return `${Math.floor(d / 3600)}h ${Math.floor((d % 3600) / 60)}m`;
});

// Gate keys → the VALIDATION RESULT lines the user expects.
const CHECK_LABELS: Record<string, string> = {
  required_stages: 'Required stages',
  required_files: 'Required files',
  file_integrity: 'File integrity',
  data_completeness: 'Data completeness',
  source_coverage: 'Source coverage',
  calculation_consistency: 'Calculation consistency',
  unresolved_errors: 'Unresolved errors',
  redirect_warnings: 'Source redirects',
};

const labeledChecks = computed<Array<ValidationCheck & { label: string }>>(() =>
  props.result.checks.map(c => ({
    ...c,
    label: CHECK_LABELS[c.key] ? t(CHECK_LABELS[c.key]) : c.key,
  }))
);

const stateLabel = (state: CheckState): string => {
  switch (state) {
    case 'pass': return t('PASS');
    case 'fail': return t('FAIL');
    case 'warn': return t('NEEDS_REVIEW');
    default: return '—';
  }
};

const stateClass = (state: CheckState): string => {
  switch (state) {
    case 'pass': return 'bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400';
    case 'fail': return 'bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-400';
    case 'warn': return 'bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-400';
    default: return 'bg-[var(--fill-tsp-gray-main)] text-[var(--text-tertiary)]';
  }
};
</script>
