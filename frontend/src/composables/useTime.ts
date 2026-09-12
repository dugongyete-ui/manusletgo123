import { ref, onMounted, onUnmounted } from 'vue';
import { formatRelativeTime, formatCustomTime } from '../utils/time';
import { useI18n } from 'vue-i18n';

// ── ONE shared app clock ──────────────────────────────────────────────────────
// Previously EVERY component instance calling useRelativeTime()/useCustomTime()
// spun up its OWN 60s setInterval — a chat page with 155 events ran 41+
// synchronized timers that all fired in the same burst every minute, forcing
// every message/tool/step component to re-render simultaneously (measured:
// 123ms main-thread freeze per minute on phone-class CPU). Now there is a
// single module-level clock, ref-counted by mounted consumers.
const sharedNow = ref(Date.now());
let clockConsumers = 0;
let clockTimer: number | null = null;

const startClock = () => {
  clockConsumers++;
  if (clockTimer === null) {
    clockTimer = window.setInterval(() => {
      sharedNow.value = Date.now();
    }, 60000);
  }
};

const stopClock = () => {
  clockConsumers = Math.max(0, clockConsumers - 1);
  if (clockConsumers === 0 && clockTimer !== null) {
    clearInterval(clockTimer);
    clockTimer = null;
  }
};

export function useRelativeTime() {
  onMounted(startClock);
  onUnmounted(stopClock);

  // Plain function that reads sharedNow INSIDE the render call — each
  // component tracks the clock as its own dependency, so it re-renders when
  // the minute ticks, but the render itself is cheap (markdown HTML is
  // memoized in computed properties at the call sites).
  const relativeTime = (timestamp: number) => {
    sharedNow.value; // reactive dependency
    return formatRelativeTime(timestamp);
  };

  return {
    relativeTime
  };
}

export function useCustomTime() {
  const { t, locale } = useI18n();

  onMounted(startClock);
  onUnmounted(stopClock);

  const customTime = (timestamp: number) => {
    sharedNow.value; // reactive dependency
    return formatCustomTime(timestamp, t, locale.value);
  };

  return {
    customTime
  };
}
