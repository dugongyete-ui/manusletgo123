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

      <!-- Fake input box — clicking redirects to login -->
      <div class="input-box" @click="goToLogin">
        <span class="input-placeholder">Assign a task or ask anything</span>
        <div class="input-actions">
          <button class="attach-btn" @click.stop="goToLogin">
            <Plus :size="18" />
          </button>
          <button class="send-btn" @click.stop="goToLogin">
            <ArrowUp :size="16" />
          </button>
        </div>
      </div>

      <!-- Task suggestion pills -->
      <div class="suggestions">
        <button class="suggestion-pill" @click="goToLogin">
          <PresentationIcon :size="14" />
          Create slides
        </button>
        <button class="suggestion-pill" @click="goToLogin">
          <Globe :size="14" />
          Build website
        </button>
        <button class="suggestion-pill" @click="goToLogin">
          <Monitor :size="14" />
          Develop desktop apps
        </button>
        <button class="suggestion-pill" @click="goToLogin">
          <Palette :size="14" />
          Design
        </button>
        <button class="suggestion-pill" @click="goToLogin">
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
import { useRouter } from 'vue-router'
import {
  Bot, Sun, Moon, Plus, ArrowUp,
  Globe, Monitor, Terminal, Palette, MoreHorizontal,
  Presentation as PresentationIcon
} from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'

const { theme, toggleTheme } = useTheme()
const router = useRouter()

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
  font-size: clamp(26px, 4vw, 36px);
  font-weight: 500;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  margin: 0 0 28px;
  text-align: center;
}

/* ── Input box ── */
.input-box {
  width: 100%;
  max-width: 680px;
  background: var(--background-card);
  border: 1px solid var(--border-main);
  border-radius: 16px;
  padding: 16px 16px 12px 20px;
  cursor: text;
  box-shadow: 0 2px 8px var(--shadow-XS);
  transition: box-shadow 0.15s, border-color 0.15s;
  margin-bottom: 16px;
}
.input-box:hover {
  border-color: var(--border-dark);
  box-shadow: 0 4px 16px var(--shadow-S);
}
.input-placeholder {
  display: block;
  font-size: 15px;
  color: var(--text-disable);
  margin-bottom: 28px;
  user-select: none;
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
  opacity: 0.4;
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
