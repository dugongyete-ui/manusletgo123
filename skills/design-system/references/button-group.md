# Button Groups

> Dependencies: `buttons.md`, `colors.md`, `radius.md`

Button groups combine multiple pill buttons into a single connected control. Because every button in this system is a pill with a 6px border and an 8px offset shadow, button groups in this design system are *not* a tightly-merged segmented control — they are a row of pills with their offset shadows preserved, separated by a small gap.

## Core Specs

- **Wrapper:** inline-flex, 12px gap between buttons (so each pill keeps its full offset shadow visible)
- **No wrapper shadow** — every button keeps its own offset block shadow from `buttons.md`
- **No border collapse** — buttons do NOT overlap; their thick 6px borders and pill radii (9999px) are preserved on every button

## Anatomy

### Wrapper
- Display: inline-flex
- Gap: 12px between children
- Align items: center
- No background, no border, no radius, no shadow on the wrapper itself

### Children
- Each button retains its full pill shape, 6px border, and offset block shadow per `buttons.md`
- All buttons in the group MUST be the same size (xs/sm/base/lg/xl)
- Mixing variants (e.g., one Brand pill and one Secondary pill) is allowed and encouraged for primary + secondary action pairs

## Toggle / Segmented Variant

When the group acts as a single-select segmented control:

- All buttons in the group share the same variant in their inactive state (typically `Tertiary` or `Quaternary`)
- The active button switches to the `Brand` variant
- Selecting a button triggers the canonical press effect from `buttons.md`

## Rules

- Buttons inside groups follow ALL styles from `buttons.md` (background, border, offset shadow, focus rings, press effect) — no exceptions
- Icon-only buttons: icon size matches the button font size (use `1em`), pill radius preserved
- Never collapse borders or radii to make buttons merge — the chunky pill silhouette must be preserved on every button

---