# Layout & Spacing

## Spacing Rhythm

Base unit: **8px**. All spacing values should be multiples of 8px. The magazine aesthetic favors generous, decisive whitespace — never cramped layouts.

| Context | Value |
|---|---|
| Section vertical padding | 128px |
| Section header → content | 64px or 80px |
| Heading → paragraph | 24px |
| Container horizontal padding | 32px |
| Flex/grid row gap | 24px |
| Card grid gap | 32px (minimum — required to clear card ring shadows) |
| Wide component grid gap | 48px |
| Column layout gap | 64px |

## Container

Standard section container: max-width 1200px, centered, 32px horizontal padding.

Every major section wraps content in this container.

## Content Composition Order

Inside each section, follow this magazine-style order:
1. ALL-CAPS kicker (eyebrow label, optional)
2. Heading (`h1`–`h3`)
3. Leading paragraph
4. Normal paragraph(s)
5. Lists, CTA links, or component grids

## Section Pattern

Each section has:
- 128px vertical padding
- A background color drawn from the **section alternation palette** (see below)
- A centered container (max-width 1200px, 32px horizontal padding)
- A section header area with 64px bottom margin
- Section content below

### Section Alternation Palette (mandatory)

The page MUST cycle through the four brand colors as section backgrounds in a playful, magazine-style rotation. Consecutive sections never repeat the same background:

1. Section A → `brand` background, white text
2. Section B → `secondary-brand` background, white text
3. Section C → `tertiary-brand` background, heading text
4. Section D → `quaternary-brand` background, heading text

Use `neutral-primary-soft` only as an occasional palate cleanser between vivid blocks (no more than once per page). The hero, feature blocks, and CTA must each pick a different swatch from the cycle.

Cards placed on top of each section must use the *softer* derivative of the parent section color for their background — see `cards.md` and `colors.md` ("Surface Cards on Colored Sections").

## Motion & Animation

- Prefer CSS-native: `transition`, `animation`, `@keyframes`. Use a motion library only when CSS cannot achieve the behavior.
- Prioritize high-impact orchestrated moments over scattered micro-interactions. A single well-sequenced page-load animation using staggered `animation-delay` delivers more perceived quality than many isolated effects.
- Reserve scroll-triggered and hover transitions for moments that reinforce hierarchy or reward attention.
- The button "press" effect (see `buttons.md`) is the canonical micro-interaction — use it consistently.

## Backgrounds & Visual Depth

- Backgrounds are **flat, vivid, brand-colored fields** — not gradients, not gradient meshes, not noise textures
- Depth comes from layered borders, offset solid block shadows on buttons, and the concentric ring shadow on cards
- Magazine-style decorative elements are encouraged: ALL-CAPS kickers, hard horizontal rules, oversized pull quotes, drop caps
- Every decorative element must serve a compositional purpose (depth, separation, or emphasis); no purely ornamental effects competing with content

## Must

- All sections: consistent 128px vertical padding
- All containers: max-width 1200px, centered, 32px horizontal padding
- Section headers: 64px bottom margin
- Sections rotate through `brand`, `secondary-brand`, `tertiary-brand`, `quaternary-brand` per the alternation palette
- Card grids: minimum 32px gap so the brand ring shadow has room to breathe
- Layouts readable and properly spaced on both desktop and mobile

---