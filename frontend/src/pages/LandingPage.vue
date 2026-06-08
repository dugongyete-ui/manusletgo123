<template>
  <div class="page" :class="{ dark: theme === 'dark' }">

    <!-- Navbar -->
    <nav class="nav">
      <div class="nav-inner">
        <a href="/" class="nav-logo">
          <Bot :size="22" />
          <span class="nav-logo-text">Dzeck</span>
        </a>
        <div class="nav-right">
          <button @click="toggleTheme" class="icon-btn" :title="theme === 'dark' ? 'Light mode' : 'Dark mode'">
            <Sun v-if="theme === 'dark'" :size="16" />
            <Moon v-else :size="16" />
          </button>
          <a href="/login" class="btn-secondary">Sign in</a>
          <a href="/login" class="btn-primary">Sign up</a>
        </div>
      </div>
    </nav>

    <!-- Main centered content -->
    <main class="main">
      <h1 class="headline">What can I do for you?</h1>

      <!-- Interactive input box -->
      <div class="input-box" :class="{ focused: isFocused }">
        <textarea
          ref="textareaRef"
          v-model="message"
          class="input-textarea"
          placeholder="Assign a task or ask anything"
          rows="1"
          @focus="isFocused = true"
          @blur="isFocused = false"
          @input="autoResize"
          @keydown.enter.exact.prevent="handleSend"
        />
        <div class="input-actions">
          <button class="attach-btn" title="Attach file">
            <Plus :size="18" />
          </button>
          <button
            class="send-btn"
            :class="{ active: message.trim().length > 0 }"
            @click="handleSend"
            title="Send"
          >
            <ArrowUp :size="16" />
          </button>
        </div>
      </div>

      <!-- Task suggestion pills -->
      <div class="suggestions">
        <button class="suggestion-pill" @click="fillAndSend('Create slides')">
          <PresentationIcon :size="14" />
          Create slides
        </button>
        <button class="suggestion-pill" @click="fillAndSend('Build website')">
          <Globe :size="14" />
          Build website
        </button>
        <button class="suggestion-pill" @click="fillAndSend('Develop desktop apps')">
          <Monitor :size="14" />
          Develop desktop apps
        </button>
        <button class="suggestion-pill" @click="fillAndSend('Design')">
          <Palette :size="14" />
          Design
        </button>
        <button class="suggestion-pill" @click="fillAndSend('Run code')">
          <Terminal :size="14" />
          Run code
        </button>
        <button class="suggestion-pill" @click="goToLogin">
          <MoreHorizontal :size="14" />
          More
        </button>
      </div>
    </main>

  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  Bot, Sun, Moon, Plus, ArrowUp,
  Globe, Monitor, Terminal, Palette, MoreHorizontal,
  Presentation as PresentationIcon
} from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'

const { theme, toggleTheme } = useTheme()
const router = useRouter()

const message = ref('')
const isFocused = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const autoResize = () => {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

const PENDING_KEY = 'dzeck_pending_prompt'

const handleSend = () => {
  if (!message.value.trim()) return
  localStorage.setItem(PENDING_KEY, message.value.trim())
  router.push('/login')
}

const fillAndSend = async (text: string) => {
  message.value = text
  await nextTick()
  autoResize()
  localStorage.setItem(PENDING_KEY, text)
  router.push('/login')
}

const goToLogin = () => router.push('/login')
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--background-gray-main);
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
}

/* ── Navbar ── */
.nav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: var(--background-gray-main);
}
.nav-inner {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 20px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.nav-logo {
  display: flex;
  align-items: center;
  gap: 7px;
  text-decoration: none;
  color: var(--text-primary);
}
.nav-logo-text {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: var(--text-primary);
}
.nav-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}
.icon-btn:hover { background: var(--fill-tsp-white-main); }

.btn-primary {
  padding: 7px 16px;
  border-radius: 8px;
  background: var(--Button-primary-black);
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  border: none;
  cursor: pointer;
}
.btn-primary:hover { opacity: 0.85; }

.btn-secondary {
  padding: 7px 16px;
  border-radius: 8px;
  background: transparent;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  border: 1px solid var(--border-btn-main);
  cursor: pointer;
}
.btn-secondary:hover { background: var(--fill-tsp-white-main); }

/* ── Main ── */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px 120px;
}

.headline {
  font-size: clamp(26px, 4vw, 38px);
  font-weight: 400;
  letter-spacing: -0.025em;
  font-family: ui-serif, Georgia, 'Times New Roman', serif;
  color: var(--text-primary);
  margin: 0 0 28px;
  text-align: center;
  line-height: 1.2;
}

/* ── Input box ── */
.input-box {
  width: 100%;
  max-width: 680px;
  background: var(--background-card);
  border: 1px solid var(--border-dark);
  border-radius: 16px;
  padding: 16px 16px 12px 20px;
  cursor: text;
  box-shadow: 0 1px 4px var(--shadow-XS);
  transition: box-shadow 0.18s, border-color 0.18s;
  margin-bottom: 16px;
}
.input-box:hover {
  border-color: var(--border-input-active);
  box-shadow: 0 2px 12px var(--shadow-S);
}
.input-box.focused {
  border-color: var(--border-input-active);
  box-shadow: 0 0 0 3px var(--fill-blue), 0 2px 12px var(--shadow-S);
}
.input-textarea {
  width: 100%;
  min-height: 24px;
  max-height: 200px;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-primary);
  font-family: inherit;
  margin-bottom: 12px;
  overflow-y: auto;
}
.input-textarea::placeholder {
  color: var(--text-disable);
}
.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.attach-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--border-btn-main);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}
.attach-btn:hover { background: var(--fill-tsp-white-main); }

.send-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: var(--Button-primary-black);
  color: #fff;
  cursor: pointer;
  opacity: 0.3;
  transition: opacity 0.15s;
}
.send-btn.active {
  opacity: 1;
}
.send-btn.active:hover {
  opacity: 0.85;
}

/* ── Suggestions ── */
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  max-width: 680px;
}
.suggestion-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 99px;
  border: 1px solid var(--border-btn-main);
  background: var(--background-card);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 450;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.suggestion-pill:hover {
  background: var(--fill-tsp-white-main);
  color: var(--text-primary);
}

/* ── Responsive ── */
@media (max-width: 480px) {
  .headline { font-size: 22px; }
  .nav-right .btn-secondary { display: none; }
}
</style>
