<template>
    <div class="vkb" role="group" :aria-label="t('Virtual keyboard')">
        <!-- Row 0: numbers + backspace -->
        <div class="vkb-row">
            <button v-for="k in numberKeys" :key="'n' + k.main" class="vkb-key" @pointerdown.prevent="tapKey(k)"
                @contextmenu.prevent>
                {{ shift ? k.alt : k.main }}
            </button>
            <button class="vkb-key vkb-wide" @pointerdown.prevent="tapSpecial('BackSpace')"
                :title="t('Backspace')">⌫</button>
        </div>

        <!-- Row 1: qwertyuiop -->
        <div class="vkb-row">
            <button v-for="k in row1" :key="'r1' + k.main" class="vkb-key" @pointerdown.prevent="tapKey(k)"
                @contextmenu.prevent>
                {{ shift || capsLock ? k.main.toUpperCase() : k.main }}
            </button>
        </div>

        <!-- Row 2: asdfghjkl + enter -->
        <div class="vkb-row">
            <button v-for="k in row2" :key="'r2' + k.main" class="vkb-key" @pointerdown.prevent="tapKey(k)"
                @contextmenu.prevent>
                {{ shift || capsLock ? k.main.toUpperCase() : k.main }}
            </button>
            <button class="vkb-key vkb-wide vkb-accent" @pointerdown.prevent="tapSpecial('Return')"
                :title="t('Enter')">↵</button>
        </div>

        <!-- Row 3: shift, zxcvbnm, arrows up -->
        <div class="vkb-row">
            <button class="vkb-key vkb-wide" :class="{ 'vkb-on': shift }" @pointerdown.prevent="toggleShift()"
                :title="t('Shift')">⇧</button>
            <button v-for="k in row3" :key="'r3' + k.main" class="vkb-key" @pointerdown.prevent="tapKey(k)"
                @contextmenu.prevent>
                {{ shift || capsLock ? k.main.toUpperCase() : k.main }}
            </button>
            <button class="vkb-key" @pointerdown.prevent="tapSpecial('ArrowUp')" :title="t('Up')">↑</button>
        </div>

        <!-- Row 4: ctrl, alt, space, arrows -->
        <div class="vkb-row">
            <button class="vkb-key vkb-wide" :class="{ 'vkb-on': ctrl }" @pointerdown.prevent="ctrl = !ctrl"
                :title="t('Ctrl')">Ctrl</button>
            <button class="vkb-key vkb-wide" :class="{ 'vkb-on': alt }" @pointerdown.prevent="alt = !alt"
                :title="t('Alt')">Alt</button>
            <button class="vkb-key vkb-space" @pointerdown.prevent="tapSpecial('Space')">{{ t('space') }}</button>
            <button class="vkb-key" @pointerdown.prevent="tapSpecial('ArrowLeft')" :title="t('Left')">←</button>
            <button class="vkb-key" @pointerdown.prevent="tapSpecial('ArrowDown')" :title="t('Down')">↓</button>
            <button class="vkb-key" @pointerdown.prevent="tapSpecial('ArrowRight')" :title="t('Right')">→</button>
        </div>

        <!-- Row 5: utility keys -->
        <div class="vkb-row vkb-row-util">
            <button class="vkb-key vkb-util" @pointerdown.prevent="tapSpecial('Tab')" :title="t('Tab')">Tab</button>
            <button class="vkb-key vkb-util" @pointerdown.prevent="tapSpecial('Escape')" :title="t('Esc')">Esc</button>
            <button class="vkb-key vkb-util" @pointerdown.prevent="tapSpecial('Delete')" :title="t('Del')">Del</button>
            <button class="vkb-key vkb-util" @pointerdown.prevent="toggleCaps()" :class="{ 'vkb-on': capsLock }"
                :title="t('Caps Lock')">Caps</button>
            <button class="vkb-key vkb-util" @pointerdown.prevent="sendCtrlAltDel()" :title="t('Send Ctrl+Alt+Del')">
                Ctl+Alt+Del
            </button>
            <button class="vkb-key vkb-util" @pointerdown.prevent="$emit('close')" :title="t('Close keyboard')">
                ✕
            </button>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const emit = defineEmits<{
    close: [];
}>();

const props = defineProps<{
    /** Sends a keysym press+release to the VNC session. */
    sendKey: (keysym: number, code: string) => void;
    /** Sends a full key sequence: [[keysym, code, down], ...] in order. */
    sendSequence: (seq: Array<[number, string, boolean]>) => void;
    sendCtrlAltDel?: () => void;
}>();

/* ---------------- key tables ---------------- */

interface CharKey {
    main: string;
    alt: string;
    code: string;
}

const mk = (main: string, alt: string, letter: string): CharKey => ({ main, alt, code: `Key${letter}` });

const numberKeys: CharKey[] = [
    { main: '1', alt: '!', code: 'Digit1' }, { main: '2', alt: '@', code: 'Digit2' },
    { main: '3', alt: '#', code: 'Digit3' }, { main: '4', alt: '$', code: 'Digit4' },
    { main: '5', alt: '%', code: 'Digit5' }, { main: '6', alt: '^', code: 'Digit6' },
    { main: '7', alt: '&', code: 'Digit7' }, { main: '8', alt: '*', code: 'Digit8' },
    { main: '9', alt: '(', code: 'Digit9' }, { main: '0', alt: ')', code: 'Digit0' },
];

const row1: CharKey[] = ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'].map(c => mk(c, c.toUpperCase(), c.toUpperCase()));
const row2: CharKey[] = ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'].map(c => mk(c, c.toUpperCase(), c.toUpperCase()));
const row3: CharKey[] = ['z', 'x', 'c', 'v', 'b', 'n', 'm'].map(c => mk(c, c.toUpperCase(), c.toUpperCase()));

/* X11 keysyms — see @novnc/novnc core/input/keysym.js */
const SPECIAL: Record<string, { keysym: number; code: string }> = {
    BackSpace: { keysym: 0xff08, code: 'Backspace' },
    Tab: { keysym: 0xff09, code: 'Tab' },
    Return: { keysym: 0xff0d, code: 'Enter' },
    Escape: { keysym: 0xff1b, code: 'Escape' },
    Delete: { keysym: 0xffff, code: 'Delete' },
    Space: { keysym: 0x0020, code: 'Space' },
    ArrowLeft: { keysym: 0xff51, code: 'ArrowLeft' },
    ArrowUp: { keysym: 0xff52, code: 'ArrowUp' },
    ArrowRight: { keysym: 0xff53, code: 'ArrowRight' },
    ArrowDown: { keysym: 0xff54, code: 'ArrowDown' },
    Shift_L: { keysym: 0xffe1, code: 'ShiftLeft' },
    Control_L: { keysym: 0xffe3, code: 'ControlLeft' },
    Alt_L: { keysym: 0xffe9, code: 'AltLeft' },
};

/* ---------------- modifier state ---------------- */

const shift = ref(false);
const ctrl = ref(false);
const alt = ref(false);
const capsLock = ref(false);

const toggleShift = () => { shift.value = !shift.value; };
const toggleCaps = () => { capsLock.value = !capsLock.value; };

/* ---------------- send helpers ---------------- */

/** Send a modifier + key combo with proper down/up ordering. */
const sendChord = (modKeysyms: Array<[number, string]>, key: [number, string]) => {
    const seq: Array<[number, string, boolean]> = [];
    for (const [mKeysym, mCode] of modKeysyms) seq.push([mKeysym, mCode, true]);
    seq.push([key[0], key[1], true]);
    seq.push([key[0], key[1], false]);
    for (let i = modKeysyms.length - 1; i >= 0; i--) seq.push([modKeysyms[i][0], modKeysyms[i][1], false]);
    props.sendSequence(seq);
};

/** A printable character key was tapped. */
const tapKey = (k: CharKey) => {
    const useAlt = shift.value;
    const ch = useAlt ? k.alt : k.main;
    // For letters: shift/caps decide the case of the keysym we send
    let keysym: number;
    if (k.code.startsWith('Key')) {
        const lower = k.main;
        const upper = k.alt;
        const asUpper = shift.value !== capsLock.value; // XOR
        keysym = (asUpper ? upper : lower).charCodeAt(0);
    } else {
        keysym = ch.charCodeAt(0);
    }

    const mods: Array<[number, string]> = [];
    if (ctrl.value) mods.push([SPECIAL.Control_L.keysym, SPECIAL.Control_L.code]);
    if (alt.value) mods.push([SPECIAL.Alt_L.keysym, SPECIAL.Alt_L.code]);
    if (shift.value) mods.push([SPECIAL.Shift_L.keysym, SPECIAL.Shift_L.code]);

    if (mods.length > 0) {
        sendChord(mods, [keysym, k.code]);
    } else {
        props.sendKey(keysym, k.code);
    }
    // One-shot: modifiers are consumed by the next key
    if (shift.value) shift.value = false;
    if (ctrl.value) ctrl.value = false;
    if (alt.value) alt.value = false;
};

/** A special / non-printable key was tapped. */
const tapSpecial = (name: string) => {
    const s = SPECIAL[name];
    if (!s) return;
    props.sendKey(s.keysym, s.code);
};

const sendCtrlAltDel = () => {
    props.sendCtrlAltDel?.();
};

defineExpose({ shift, ctrl, alt, capsLock });
</script>

<style scoped>
.vkb {
    display: flex;
    flex-direction: column;
    gap: 7px;
    padding: 10px 10px 12px;
    background: rgba(24, 24, 27, 0.96);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-top: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.4);
    user-select: none;
    -webkit-user-select: none;
    touch-action: manipulation;
}

.vkb-row {
    display: flex;
    gap: 6px;
    justify-content: center;
    width: 100%;
}

.vkb-key {
    flex: 1 1 0;
    min-width: 0;
    height: 42px;
    padding: 0 2px;
    border: none;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.10);
    color: rgba(235, 235, 245, 0.95);
    font-size: 14px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.1s ease, transform 0.05s ease;
    white-space: nowrap;
    overflow: hidden;
}

.vkb-key:active {
    background: rgba(255, 255, 255, 0.28);
    transform: scale(0.96);
}

.vkb-key.vkb-wide {
    flex: 1.6 1 0;
}

.vkb-key.vkb-space {
    flex: 5 1 0;
    font-size: 12px;
    letter-spacing: 0.3em;
    text-indent: 0.3em;
}

.vkb-key.vkb-accent {
    background: rgba(255, 255, 255, 0.22);
}

.vkb-key.vkb-on {
    background: #ffffff;
    color: #18181b;
}

.vkb-key.vkb-util {
    flex: 1.4 1 0;
    font-size: 12px;
}

/* Compact phones: smaller keys so everything fits */
@media (max-width: 480px) {
    .vkb-key {
        height: 38px;
        font-size: 13px;
        border-radius: 7px;
    }

    .vkb {
        gap: 6px;
        padding: 8px 6px 10px;
    }

    .vkb-row {
        gap: 4px;
    }
}
</style>
