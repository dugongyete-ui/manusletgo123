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
