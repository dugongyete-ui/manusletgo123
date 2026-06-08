<template>
  <div class="landing-page" :class="{ dark: theme === 'dark' }">
    <!-- SEO Meta via useHead would go here in SSR; for SPA we rely on index.html -->

    <!-- Navbar -->
    <nav class="landing-nav">
      <div class="nav-inner">
        <a href="/" class="nav-logo">
          <Bot :size="26" />
          <span class="nav-logo-text">Dzeck</span>
        </a>
        <div class="nav-actions">
          <button @click="toggleTheme" class="theme-toggle" :title="theme === 'dark' ? 'Light mode' : 'Dark mode'">
            <Sun v-if="theme === 'dark'" :size="16" />
            <Moon v-else :size="16" />
          </button>
          <a href="/login" class="btn-outline">Sign in</a>
          <a href="/login" class="btn-primary">Get Started</a>
        </div>
      </div>
    </nav>

    <!-- Hero -->
    <section class="hero">
      <div class="hero-badge">
        <Sparkles :size="13" />
        <span>AI Agent Platform</span>
      </div>
      <h1 class="hero-title">
        The AI that <span class="hero-accent">acts</span>,<br />not just answers
      </h1>
      <p class="hero-subtitle">
        Dzeck is an autonomous AI agent that browses the web, writes &amp; runs code,
        manages files, and completes complex tasks — all on its own.
      </p>
      <div class="hero-cta">
        <a href="/login" class="btn-primary btn-large">
          Start for free <ArrowRight :size="16" />
        </a>
        <a href="#features" class="btn-ghost btn-large">See what it can do</a>
      </div>

      <!-- Floating capability pills -->
      <div class="hero-pills">
        <span class="pill"><Globe :size="13" /> Web browsing</span>
        <span class="pill"><Terminal :size="13" /> Code execution</span>
        <span class="pill"><FolderOpen :size="13" /> File management</span>
        <span class="pill"><Search :size="13" /> Web search</span>
        <span class="pill"><Cpu :size="13" /> Multi-LLM</span>
      </div>
    </section>

    <!-- Features -->
    <section id="features" class="features">
      <div class="section-label">Capabilities</div>
      <h2 class="section-title">Everything your agent needs</h2>
      <p class="section-subtitle">Dzeck combines a powerful planner with an executor that uses real tools to get your work done.</p>

      <div class="features-grid">
        <div class="feature-card feature-card--accent">
          <div class="feature-icon"><Globe :size="22" /></div>
          <h3>Browser Automation</h3>
          <p>Dzeck controls a real Chromium browser — it navigates pages, fills forms, clicks buttons, and extracts data just like a human would.</p>
        </div>

        <div class="feature-card">
          <div class="feature-icon"><Terminal :size="22" /></div>
          <h3>Shell &amp; Code Execution</h3>
          <p>Run Python, JavaScript, Bash and more inside a sandboxed environment. Dzeck can install packages, debug errors, and iterate automatically.</p>
        </div>

        <div class="feature-card">
          <div class="feature-icon"><FolderOpen :size="22" /></div>
          <h3>File Management</h3>
          <p>Read, write, create, and organize files in the workspace. Download results, generate reports, and export data in any format.</p>
        </div>

        <div class="feature-card">
          <div class="feature-icon"><Search :size="22" /></div>
          <h3>Multi-Source Search</h3>
          <p>Search the web using Tavily, Bing, Google, or Baidu. Dzeck synthesizes results and uses them to make informed decisions.</p>
        </div>

        <div class="feature-card">
          <div class="feature-icon"><Layers :size="22" /></div>
          <h3>Plan-Act Loop</h3>
          <p>A dedicated Planner agent designs a step-by-step strategy. An Executor agent carries it out — breaking down complex goals automatically.</p>
        </div>

        <div class="feature-card">
          <div class="feature-icon"><Cpu :size="22" /></div>
          <h3>Multi-LLM Support</h3>
          <p>Connect any OpenAI-compatible model — Qwen, GPT-4, Claude, DeepSeek, Ollama, and more. Switch models without changing your workflow.</p>
        </div>
      </div>
    </section>

    <!-- How it works -->
    <section class="how-it-works">
      <div class="section-label">How it works</div>
      <h2 class="section-title">From task to result in seconds</h2>

      <div class="steps">
        <div class="step">
          <div class="step-number">01</div>
          <div class="step-content">
            <h3>Describe your task</h3>
            <p>Tell Dzeck what you need in plain language — no commands, no code required.</p>
          </div>
        </div>
        <div class="step-divider"><ArrowRight :size="18" /></div>
        <div class="step">
          <div class="step-number">02</div>
          <div class="step-content">
            <h3>Dzeck plans &amp; acts</h3>
            <p>The AI breaks your goal into steps and executes them using real tools — browser, shell, search, and more.</p>
          </div>
        </div>
        <div class="step-divider"><ArrowRight :size="18" /></div>
        <div class="step">
          <div class="step-number">03</div>
          <div class="step-content">
            <h3>Get your result</h3>
            <p>Watch the agent work live, then receive your deliverable — file, report, code, or answer.</p>
          </div>
        </div>
      </div>
    </section>

    <!-- CTA Banner -->
    <section class="cta-banner">
      <h2>Ready to delegate your work?</h2>
      <p>Join thousands of users who let Dzeck handle the heavy lifting.</p>
      <a href="/login" class="btn-primary btn-large">
        Get started free <ArrowRight :size="16" />
      </a>
    </section>

    <!-- Footer -->
    <footer class="landing-footer">
      <div class="footer-inner">
        <div class="footer-brand">
          <Bot :size="20" />
          <span>Dzeck</span>
        </div>
        <p class="footer-copy">© {{ currentYear }} Dzeck. Autonomous AI agent platform.</p>
        <div class="footer-links">
          <a href="/login">Sign in</a>
          <a href="/login">Register</a>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  Bot, Sun, Moon, Sparkles, ArrowRight,
  Globe, Terminal, FolderOpen, Search, Cpu, Layers
} from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'

const { theme, toggleTheme } = useTheme()
const currentYear = computed(() => new Date().getFullYear())
</script>

<style scoped>
/* ── Root / theming ── */
.landing-page {
  min-height: 100vh;
  background: var(--background-gray-main);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
}

/* ── Navbar ── */
.landing-nav {
  position: sticky;
  top: 0;
  z-index: 50;
  border-bottom: 1px solid var(--border-main);
  background: var(--background-gray-main);
  backdrop-filter: blur(12px);
}
.nav-inner {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 24px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.nav-logo {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: var(--text-primary);
}
.nav-logo-text {
  font-family: ui-serif, Georgia, 'Times New Roman', serif;
  font-size: 20px;
  font-weight: 500;
  letter-spacing: -0.5px;
  color: var(--logo-color);
}
.nav-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.theme-toggle {
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
.theme-toggle:hover { background: var(--fill-tsp-white-main); }

/* ── Buttons ── */
.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border-radius: 8px;
  background: var(--Button-primary-black);
  color: var(--text-onblack);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-primary:hover { opacity: 0.85; }
.btn-primary.btn-large { padding: 12px 24px; font-size: 15px; border-radius: 10px; }

.btn-outline {
  display: inline-flex;
  align-items: center;
  padding: 7px 16px;
  border-radius: 8px;
  border: 1px solid var(--border-btn-main);
  background: transparent;
  color: var(--text-primary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
}
.btn-outline:hover { background: var(--fill-tsp-white-main); }

.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 12px 20px;
  border-radius: 10px;
  border: 1px solid var(--border-btn-main);
  background: transparent;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 15px;
  font-weight: 500;
}
.btn-ghost:hover { background: var(--fill-tsp-white-main); color: var(--text-primary); }

/* ── Hero ── */
.hero {
  max-width: 760px;
  margin: 0 auto;
  padding: 80px 24px 100px;
  text-align: center;
}
.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 99px;
  border: 1px solid var(--border-btn-main);
  background: var(--background-card);
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 28px;
}
.hero-title {
  font-size: clamp(36px, 6vw, 62px);
  font-weight: 700;
  line-height: 1.12;
  letter-spacing: -0.03em;
  color: var(--text-primary);
  margin: 0 0 20px;
}
.hero-accent {
  color: var(--text-brand);
}
.hero-subtitle {
  font-size: 18px;
  line-height: 1.7;
  color: var(--text-secondary);
  max-width: 560px;
  margin: 0 auto 36px;
}
.hero-cta {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 48px;
}
.hero-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
.pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 99px;
  border: 1px solid var(--border-main);
  background: var(--background-card);
  font-size: 13px;
  color: var(--text-secondary);
}

/* ── Section shared ── */
.section-label {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-brand);
  margin-bottom: 12px;
}
.section-title {
  font-size: clamp(24px, 4vw, 38px);
  font-weight: 700;
  letter-spacing: -0.025em;
  color: var(--text-primary);
  margin: 0 0 12px;
}
.section-subtitle {
  font-size: 16px;
  line-height: 1.65;
  color: var(--text-secondary);
  max-width: 520px;
  margin: 0 auto 56px;
}

/* ── Features ── */
.features {
  max-width: 1100px;
  margin: 0 auto;
  padding: 80px 24px;
  text-align: center;
}
.features-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  text-align: left;
}
.feature-card {
  padding: 28px;
  border-radius: 14px;
  border: 1px solid var(--border-main);
  background: var(--background-card);
}
.feature-card--accent {
  border-color: var(--border-input-active);
  background: var(--fill-blue);
}
.feature-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--fill-tsp-white-main);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-brand);
  margin-bottom: 16px;
}
.feature-card h3 {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 8px;
  color: var(--text-primary);
}
.feature-card p {
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-secondary);
  margin: 0;
}

/* ── How it works ── */
.how-it-works {
  max-width: 960px;
  margin: 0 auto;
  padding: 80px 24px;
  text-align: center;
  border-top: 1px solid var(--border-main);
}
.steps {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 48px;
}
.step {
  flex: 1;
  min-width: 200px;
  max-width: 260px;
  text-align: left;
}
.step-number {
  font-size: 28px;
  font-weight: 700;
  color: var(--border-btn-main);
  margin-bottom: 12px;
  letter-spacing: -0.05em;
}
.step-content h3 {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 8px;
  color: var(--text-primary);
}
.step-content p {
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-secondary);
  margin: 0;
}
.step-divider {
  color: var(--text-disable);
  padding-top: 8px;
  flex-shrink: 0;
}

/* ── CTA Banner ── */
.cta-banner {
  margin: 0 24px 60px;
  max-width: 760px;
  margin-left: auto;
  margin-right: auto;
  padding: 60px 40px;
  border-radius: 20px;
  background: var(--Button-primary-black);
  text-align: center;
  color: var(--text-onblack);
}
.cta-banner h2 {
  font-size: clamp(22px, 3.5vw, 34px);
  font-weight: 700;
  letter-spacing: -0.025em;
  margin: 0 0 12px;
  color: #fff;
}
.cta-banner p {
  font-size: 16px;
  color: rgba(255,255,255,0.65);
  margin: 0 0 28px;
}
.cta-banner .btn-primary {
  background: #fff;
  color: #1a1a19;
}
.cta-banner .btn-primary:hover { opacity: 0.9; }

/* ── Footer ── */
.landing-footer {
  border-top: 1px solid var(--border-main);
  padding: 32px 24px;
}
.footer-inner {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.footer-brand {
  display: flex;
  align-items: center;
  gap: 7px;
  font-weight: 600;
  font-size: 15px;
  color: var(--text-primary);
}
.footer-copy {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0;
}
.footer-links {
  display: flex;
  gap: 20px;
}
.footer-links a {
  font-size: 13px;
  color: var(--text-secondary);
  text-decoration: none;
}
.footer-links a:hover { color: var(--text-primary); }

/* ── Responsive ── */
@media (max-width: 640px) {
  .hero { padding: 60px 20px 80px; }
  .features, .how-it-works { padding: 60px 20px; }
  .steps { flex-direction: column; align-items: center; }
  .step-divider { transform: rotate(90deg); }
  .cta-banner { padding: 40px 24px; margin: 0 16px 48px; }
  .nav-actions .btn-outline { display: none; }
  .footer-inner { flex-direction: column; text-align: center; }
}
</style>
