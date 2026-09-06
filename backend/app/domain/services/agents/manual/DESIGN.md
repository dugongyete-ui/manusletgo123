# DESIGN.md

Visual quality rules for anything the user will LOOK at: pages, components,
charts, document layout.

## Baseline for web UI
- One idea per screen. Hierarchy: what's the ONE thing this page is for?
- Real spacing: 8pt rhythm, breathing room around content, no cramped
  4px-everything grids.
- Typography: a system font stack is fine (system-ui); sizes in a scale
  (e.g. 14/16/20/28/40), one accent color, high contrast text.
- States matter: loading, empty, error. A button that can't show "disabled"
  will lie to the user.
- Mobile is not optional: layouts flex below 480px, tap targets ≥ 40px.

## Charts
- Title, axis labels, units, and the source line. A chart without units is
  a decoration.
- One chart per question. If you need 6 charts, you have 2 questions.
- Color with meaning, consistent across the whole report.

## Documents
- Cover/title, TOC for anything over ~1500 words, headings every few
  paragraphs, tables for comparative facts, code blocks monospaced.

## The 10-second test
Open the artifact, look for 10 seconds, look away: if you can't say what it
is and what to do next, the design isn't done. Fix before delivering.

## Web design bar (v0 doctrine)
- Exactly 3-5 colors (1 primary + neutrals + 1 accent) as semantic tokens
  (HSL variables) — themed everywhere, no raw text-white/bg-black in
  components. Max 2 font families; body line-height 1.4-1.6; body >= 14px.
- Tailwind spacing scale (p-4, not p-[16px]); flex/grid layouts;
  mobile-first with md:/lg: enhancements; tap targets >= 40px.
- Every interactive element: hover + focus + disabled. Every async
  surface: loading + empty + error. First impression = product, not
  tutorial (the v0/Lovable bar).
- No placeholder images, no lorem ipsum — generate real images with the
  image tool; no console errors in the delivered app.
