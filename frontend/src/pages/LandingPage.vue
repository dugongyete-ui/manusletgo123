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

    <!-- Main -->
    <main class="main">
      <h1 class="headline">What can I do for you?</h1>

      <!-- Input box -->
      <div class="input-wrap">
        <div class="input-box" :class="{ focused: isFocused }">
          <!-- Active category tag -->
          <div v-if="activeCategory" class="category-tag">
            <component :is="activeCategory.icon" :size="12" />
            {{ activeCategory.label }}
            <button class="tag-remove" @click.stop="clearCategory">
              <X :size="11" />
            </button>
          </div>

          <textarea
            ref="textareaRef"
            v-model="message"
            class="input-textarea"
            :placeholder="activeCategory ? activeCategory.placeholder : 'Assign a task or ask anything'"
            rows="1"
            @focus="isFocused = true"
            @blur="isFocused = false"
            @input="autoResize"
            @keydown.enter.exact.prevent="handleSend"
          />
          <div class="input-actions">
            <button class="attach-btn" title="Attach">
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

        <!-- Contextual sub-options — shown when a category is selected -->
        <transition name="slide-down">
          <div v-if="activeCategory && activeCategory.subOptions" class="sub-panel">
            <div class="sub-label">{{ activeCategory.subLabel }}</div>
            <div class="sub-options">
              <button
                v-for="opt in activeCategory.subOptions"
                :key="opt.value"
                class="sub-option"
                :class="{ selected: selectedSub === opt.value }"
                @click="selectSub(opt)"
              >
                <component :is="opt.icon" :size="13" />
                {{ opt.label }}
              </button>
            </div>

            <div v-if="activeCategory.ideas" class="explore-section">
              <div class="sub-label">Explore ideas</div>
              <div class="ideas">
                <button
                  v-for="idea in activeCategory.ideas"
                  :key="idea"
                  class="idea-chip"
                  @click="fillIdea(idea)"
                >
                  {{ idea }}
                  <ArrowUpRight :size="11" />
                </button>
              </div>
            </div>
          </div>
        </transition>
      </div>

      <!-- Main suggestion pills -->
      <div class="suggestions" v-if="!activeCategory">
        <button
          v-for="cat in categories"
          :key="cat.id"
          class="suggestion-pill"
          @click="selectCategory(cat)"
        >
          <component :is="cat.icon" :size="14" />
          {{ cat.label }}
        </button>
      </div>

      <!-- When category active, show change category pills -->
      <div class="suggestions" v-else>
        <button
          v-for="cat in categories"
          :key="cat.id"
          class="suggestion-pill"
          :class="{ 'pill-active': activeCategory?.id === cat.id }"
          @click="selectCategory(cat)"
        >
          <component :is="cat.icon" :size="14" />
          {{ cat.label }}
        </button>
      </div>
    </main>

  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, markRaw } from 'vue'
import { useRouter } from 'vue-router'
import {
  Bot, Sun, Moon, Plus, ArrowUp, ArrowUpRight, X,
  Globe, Monitor, Terminal, Palette, MoreHorizontal,
  Presentation, ShoppingCart, LayoutDashboard, Image,
  Code2, FileSearch, Database, Smartphone, Cpu
} from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'

const { theme, toggleTheme } = useTheme()
const router = useRouter()

const message = ref('')
const isFocused = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const selectedSub = ref<string | null>(null)

interface SubOption {
  label: string
  value: string
  icon: any
  prompt?: string
}

interface Category {
  id: string
  label: string
  icon: any
  placeholder: string
  subLabel?: string
  subOptions?: SubOption[]
  ideas?: string[]
  defaultPrompt: string
}

const categories: Category[] = [
  {
    id: 'slides',
    label: 'Create slides',
    icon: markRaw(Presentation),
    placeholder: 'Describe your presentation topic…',
    defaultPrompt: 'Create a professional presentation on ',
    subLabel: 'What type of presentation?',
    subOptions: [
      { label: 'Business Pitch', value: 'pitch', icon: markRaw(Presentation), prompt: 'Create a compelling business pitch deck that includes executive summary, problem statement, solution, market opportunity, business model, traction, team, and funding ask.' },
      { label: 'Tutorial / How-to', value: 'tutorial', icon: markRaw(Code2), prompt: 'Create a clear step-by-step tutorial presentation with introduction, prerequisites, detailed steps with visuals, and a summary slide.' },
      { label: 'Report / Analysis', value: 'report', icon: markRaw(FileSearch), prompt: 'Create a professional report presentation with executive summary, key findings, data visualizations, insights, and actionable recommendations.' },
      { label: 'Keynote / Talk', value: 'keynote', icon: markRaw(Cpu), prompt: 'Create an engaging keynote-style presentation with a compelling narrative, strong opening hook, clear story arc, impactful visuals, and memorable closing.' },
    ],
    ideas: [
      'AI industry trends 2025',
      'Product launch deck',
      'Quarterly business review',
    ]
  },
  {
    id: 'website',
    label: 'Build website',
    icon: markRaw(Globe),
    placeholder: 'Describe the website you want to build…',
    defaultPrompt: 'Build a website for ',
    subLabel: 'What would you like to build?',
    subOptions: [
      { label: 'Landing Page', value: 'landing', icon: markRaw(Globe), prompt: 'Build a modern, conversion-optimized landing page with hero section, features, testimonials, pricing, FAQ, and CTA. Make it visually stunning with smooth animations.' },
      { label: 'E-commerce', value: 'ecommerce', icon: markRaw(ShoppingCart), prompt: 'Build a full e-commerce website with product catalog, shopping cart, product detail pages, checkout flow, and order confirmation.' },
      { label: 'Dashboard', value: 'dashboard', icon: markRaw(LayoutDashboard), prompt: 'Build a professional analytics dashboard with charts, KPI cards, data tables, filters, and a clean sidebar navigation.' },
      { label: 'Portfolio', value: 'portfolio', icon: markRaw(Image), prompt: 'Build a sleek personal portfolio website with about section, projects showcase, skills, work experience timeline, and contact form.' },
    ],
    ideas: [
      'Event registration landing page',
      'Product launch page',
      'Build waitlist landing page',
    ]
  },
  {
    id: 'desktop',
    label: 'Develop desktop apps',
    icon: markRaw(Monitor),
    placeholder: 'Describe the desktop app you want…',
    defaultPrompt: 'Develop a desktop application that ',
    subLabel: 'What type of app?',
    subOptions: [
      { label: 'Productivity Tool', value: 'productivity', icon: markRaw(Cpu), prompt: 'Develop a productivity desktop application with a clean UI, local data storage, keyboard shortcuts, and system tray support.' },
      { label: 'Data Tool', value: 'data', icon: markRaw(Database), prompt: 'Develop a data management desktop app that can import/export CSV and Excel files, visualize data with charts, and perform analysis.' },
      { label: 'Mobile App', value: 'mobile', icon: markRaw(Smartphone), prompt: 'Develop a cross-platform mobile application with intuitive navigation, offline support, push notifications, and a polished UI.' },
    ],
    ideas: [
      'File organizer app',
      'System monitor dashboard',
      'Note-taking app with sync',
    ]
  },
  {
    id: 'design',
    label: 'Design',
    icon: markRaw(Palette),
    placeholder: 'Describe what you want to design…',
    defaultPrompt: 'Design a ',
    subLabel: 'What would you like to design?',
    subOptions: [
      { label: 'UI / Interface', value: 'ui', icon: markRaw(LayoutDashboard), prompt: 'Design a modern, accessible UI with a clear visual hierarchy, consistent spacing, proper color contrast, and a clean component system.' },
      { label: 'Logo / Brand', value: 'brand', icon: markRaw(Image), prompt: 'Design a professional brand identity including logo, color palette, typography, and brand guidelines document.' },
      { label: 'Infographic', value: 'infographic', icon: markRaw(FileSearch), prompt: 'Design a visually compelling infographic that presents data and information in a clear, engaging, and shareable format.' },
    ],
    ideas: [
      'SaaS product UI design',
      'Mobile app icon set',
      'Social media kit',
    ]
  },
  {
    id: 'code',
    label: 'Run code',
    icon: markRaw(Terminal),
    placeholder: 'Describe what you want to build or run…',
    defaultPrompt: 'Write and execute code that ',
    subLabel: 'What would you like to do?',
    subOptions: [
      { label: 'Data Analysis', value: 'data', icon: markRaw(Database), prompt: 'Write Python code to analyze a dataset: load the data, clean it, compute statistics, generate visualizations, and summarize the key insights.' },
      { label: 'Web Scraping', value: 'scraping', icon: markRaw(Globe), prompt: 'Write a web scraper that extracts structured data from a website, handles pagination, saves the results to CSV, and includes error handling.' },
      { label: 'Automation', value: 'automation', icon: markRaw(Cpu), prompt: 'Write an automation script that performs repetitive tasks automatically, includes logging, error recovery, and produces a results report.' },
      { label: 'API / Backend', value: 'api', icon: markRaw(Code2), prompt: 'Build a REST API with proper endpoints, request validation, error handling, authentication, and clear documentation.' },
    ],
    ideas: [
      'Analyze sales data from CSV',
      'Scrape and summarize news',
      'Automate file organization',
    ]
  },
  {
    id: 'more',
    label: 'More',
    icon: markRaw(MoreHorizontal),
    placeholder: 'Assign a task or ask anything…',
    defaultPrompt: '',
    ideas: [
      'Research a topic in depth',
      'Summarize a document',
      'Translate text to another language',
    ]
  },
]

const activeCategory = ref<Category | null>(null)

const autoResize = () => {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

const selectCategory = async (cat: Category) => {
  activeCategory.value = cat
  selectedSub.value = null
  message.value = cat.defaultPrompt
  await nextTick()
  autoResize()
  textareaRef.value?.focus()
  const end = message.value.length
  textareaRef.value?.setSelectionRange(end, end)
}

const clearCategory = async () => {
  activeCategory.value = null
  selectedSub.value = null
  message.value = ''
  await nextTick()
  autoResize()
}

const selectSub = async (opt: SubOption) => {
  selectedSub.value = opt.value
  if (opt.prompt) {
    message.value = opt.prompt
    await nextTick()
    autoResize()
    textareaRef.value?.focus()
  }
}

const fillIdea = async (idea: string) => {
  const prefix = activeCategory.value?.defaultPrompt ?? ''
  message.value = prefix ? `${prefix}${idea.toLowerCase()}` : idea
  await nextTick()
  autoResize()
  textareaRef.value?.focus()
}

const PENDING_KEY = 'dzeck_pending_prompt'

const handleSend = () => {
  if (!message.value.trim()) return
  localStorage.setItem(PENDING_KEY, message.value.trim())
  router.push('/login')
}
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
.nav-right { display: flex; align-items: center; gap: 8px; }

.icon-btn {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: 8px;
  border: none; background: transparent;
  color: var(--text-secondary); cursor: pointer;
}
.icon-btn:hover { background: var(--fill-tsp-white-main); }

.btn-primary {
  padding: 7px 16px; border-radius: 8px;
  background: var(--Button-primary-black); color: var(--text-onblack);
  font-size: 14px; font-weight: 500;
  text-decoration: none; border: none; cursor: pointer;
}
.btn-primary:hover { opacity: 0.85; }

.btn-secondary {
  padding: 7px 16px; border-radius: 8px; background: transparent;
  color: var(--text-primary); font-size: 14px; font-weight: 500;
  text-decoration: none; border: 1px solid var(--border-btn-main); cursor: pointer;
}
.btn-secondary:hover { background: var(--fill-tsp-white-main); }

/* ── Main ── */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px 100px;
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

/* ── Input wrap + box ── */
.input-wrap {
  width: 100%;
  max-width: 680px;
  margin-bottom: 16px;
}

.input-box {
  background: var(--background-card);
  border: 1px solid var(--border-dark);
  border-radius: 16px;
  padding: 14px 14px 11px 18px;
  cursor: text;
  box-shadow: 0 1px 4px var(--shadow-XS);
  transition: box-shadow 0.18s, border-color 0.18s;
}
.input-box:hover { border-color: var(--border-input-active); box-shadow: 0 2px 12px var(--shadow-S); }
.input-box.focused { border-color: var(--border-input-active); box-shadow: 0 0 0 3px var(--fill-blue), 0 2px 12px var(--shadow-S); }

/* ── Category tag ── */
.category-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px 3px 7px;
  border-radius: 99px;
  background: var(--fill-blue);
  border: 1px solid var(--border-input-active);
  color: var(--text-brand);
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 10px;
}
.tag-remove {
  display: flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border-radius: 99px;
  border: none; background: transparent;
  color: var(--text-brand); cursor: pointer; padding: 0;
  opacity: 0.7;
}
.tag-remove:hover { opacity: 1; background: var(--Button-secondary-brand); }

.input-textarea {
  width: 100%;
  min-height: 24px;
  max-height: 200px;
  background: transparent;
  border: none; outline: none; resize: none;
  font-size: 15px; line-height: 1.6;
  color: var(--text-primary); font-family: inherit;
  margin-bottom: 10px;
  overflow-y: auto;
}
.input-textarea::placeholder { color: var(--text-disable); }

.input-actions {
  display: flex; align-items: center; justify-content: space-between;
}
.attach-btn {
  display: flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 8px;
  border: 1px solid var(--border-btn-main);
  background: transparent; color: var(--text-secondary); cursor: pointer;
}
.attach-btn:hover { background: var(--fill-tsp-white-main); }

.send-btn {
  display: flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 8px;
  border: none; background: var(--Button-primary-black);
  color: var(--text-onblack); cursor: pointer; opacity: 0.3;
  transition: opacity 0.15s;
}
.send-btn.active { opacity: 1; }
.send-btn.active:hover { opacity: 0.85; }

/* ── Sub panel ── */
.sub-panel {
  border: 1px solid var(--border-main);
  border-top: none;
  border-radius: 0 0 14px 14px;
  padding: 14px 16px 16px;
  background: var(--background-card);
  box-shadow: 0 4px 12px var(--shadow-XS);
  margin-top: -2px;
}
.sub-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin-bottom: 10px;
}
.sub-options {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-bottom: 16px;
}
.sub-option {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--border-btn-main);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 450;
  cursor: pointer;
  transition: background 0.1s, color 0.1s, border-color 0.1s;
}
.sub-option:hover {
  background: var(--fill-tsp-white-main);
  color: var(--text-primary);
}
.sub-option.selected {
  background: var(--fill-blue);
  border-color: var(--border-input-active);
  color: var(--text-brand);
}

.explore-section { margin-top: 4px; }
.ideas {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.idea-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 11px;
  border-radius: 99px;
  border: 1px solid var(--border-main);
  background: var(--background-gray-main);
  color: var(--text-secondary);
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.idea-chip:hover { background: var(--fill-tsp-white-main); color: var(--text-primary); }

/* ── Suggestion pills ── */
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  max-width: 680px;
}
.suggestion-pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: 99px;
  border: 1px solid var(--border-btn-main);
  background: var(--background-card);
  color: var(--text-secondary);
  font-size: 13px; font-weight: 450; cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.suggestion-pill:hover { background: var(--fill-tsp-white-main); color: var(--text-primary); }
.suggestion-pill.pill-active {
  background: var(--fill-blue);
  border-color: var(--border-input-active);
  color: var(--text-brand);
}

/* ── Transition ── */
.slide-down-enter-active { transition: all 0.18s ease; }
.slide-down-leave-active { transition: all 0.14s ease; }
.slide-down-enter-from { opacity: 0; transform: translateY(-6px); }
.slide-down-leave-to { opacity: 0; transform: translateY(-4px); }

/* ── Responsive ── */
@media (max-width: 480px) {
  .headline { font-size: 22px; }
  .nav-right .btn-secondary { display: none; }
  .main { padding: 40px 16px 80px; }
}
</style>
