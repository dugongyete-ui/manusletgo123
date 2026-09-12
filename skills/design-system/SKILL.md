# Design System — Agent Instructions

This skill describes the visual design language for all UI output. Every component, layout, and page should follow the design specs in the module files below. These describe *what the design looks like* — you choose how to implement the styles.

## Style
A playful, arcade-inspired interface for games — built on the VT323 pixel typeface, hard-edged 0px corners, chunky pill buttons that physically press into solid offset blocks, and cards wrapped in rainbow-ringed brand shadows that read like cabinet trim. Sections power-up through four brand colors — vivid purple-blue, lilac, mint, and powder blue — like switching levels, giving the whole product a high-score, joystick-energy feel that stays bold, tactile, and fun at every click.


## Before Writing Any Code

1. **Read every module that applies.** For a landing page, read at minimum: `layout.md`, `typography.md`, `colors.md`, `buttons.md`, `cards.md`, `shadows.md`, `radius.md`, `borders.md`. Do NOT write any markup until you have loaded all relevant modules.

## Critical Rules

- **Tokens are AGNOSTIC, NOT framework classes:** The tokens defined in the `.md` files (like `neutral-primary-soft`, `heading`, `border-default`) are agnostic design system identifiers — NOT literal class names from any framework. Do not assume the existence of pre-built classes that match these names. You must map each token to a real value (CSS variable, theme token, design-token registry, or equivalent) yourself before using it in components.

- **Cross-reference modules.** A card containing buttons must satisfy both `cards.md` AND `buttons.md`.
- **Dark mode is automatic.** The design tokens resolve to different values in light and dark modes through whatever theming layer the project uses. Never manually swap colors in components — always reference the token name and let the theming layer pick the correct light/dark value.
- **Every interactive element needs hover, focus, and disabled states** — defined in the relevant module.
- **Use semantic HTML:** proper heading hierarchy (`h1`→`h6`), `<button>` for actions, `<a>` for navigation, ARIA attributes where needed.

## Module Index

### Foundation (read first for any UI work)
- [colors.md](references/colors.md) — all background, text, and border color tokens
- [typography.md](references/typography.md) — heading scale, paragraphs, labels, links
- [layout.md](references/layout.md) — spacing rhythm, containers, animation, visual depth
- [radius.md](references/radius.md) — border-radius scale
- [shadows.md](references/shadows.md) — elevation tokens
- [borders.md](references/borders.md) — border widths and styles

### Components
- [buttons.md](references/buttons.md) — button variants, sizes, states, glint effect
- [button-group.md](references/button-group.md) — grouped button structure
- [cards.md](references/cards.md) — card structure, background, interactivity
- [inputs.md](references/inputs.md) — form controls, labels, states
- [alerts.md](references/alerts.md) — alert variants
- [badges.md](references/badges.md) — badge variants, sizes, dismissible chips
- [lists.md](references/lists.md) — list components
- [avatars.md](references/avatars.md) — avatar variants, sizes, indicators
- [icon-shapes.md](references/icon-shapes.md) — icon containers

### Complex Components
- [accordion.md](references/accordion.md) — accordion variants
- [dropdown.md](references/dropdown.md) — dropdown menus
- [modals.md](references/modals.md) — modal dialogs
- [tabs.md](references/tabs.md) — tab navigation
- [tables.md](references/tables.md) — table structure
- [pagination.md](references/pagination.md) — pagination components
- [sidebars.md](references/sidebars.md) — sidebar navigation
- [radios-checkboxes-toggle.md](references/radios-checkboxes-toggle.md) — selection controls
- [tooltips-popovers.md](references/tooltips-popovers.md) — tooltips and popovers
- [content.md](references/content.md) — grid system, responsiveness