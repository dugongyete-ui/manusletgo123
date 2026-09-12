# Shadows

The system uses crisp, offset, color-rich shadows instead of blurred ambient shadows. Every shadow is a solid offset (or a layered ring stack) — never a soft blur. This produces the print-style, magazine-poster depth.

| Token | Value (agnostic) |
|---|---|
| shadow-2xs | offset 0/2px solid `dark` color, no blur |
| shadow-xs | offset 0/4px solid `dark` color, no blur |
| shadow-sm | offset 0/6px solid `dark` color, no blur |
| shadow-md | offset 0/8px solid `dark` color, no blur |
| shadow-lg | offset 0/8px solid `brand` color, no blur (used as the button "press" base) |
| shadow-xl | layered concentric ring stack — see "Brand Ring Shadow" below |
| shadow-2xl | layered concentric ring stack at 5 stops — see "Brand Ring Shadow" below |

## Brand Ring Shadow (signature card shadow)

A layered, zero-blur ring shadow built from the four brand colors. Apply concentric rings, each one offset 3px farther from the surface than the previous, with no blur. The order MUST be brand → secondary-brand → tertiary-brand → quaternary-brand → an outer accent color from the same family.

Recipe (agnostic, top-to-bottom rings):
- Ring 1: 3px ring in `brand` color
- Ring 2: 6px ring in `secondary-brand` color
- Ring 3: 9px ring in `tertiary-brand` color
- Ring 4: 12px ring in `quaternary-brand` color
- Ring 5: 15px ring in `danger` color (used as the final accent stop)

This stack is the canonical card shadow. It MUST be used on every card and on hero/feature surfaces. See `cards.md` for the implementation rule.

## Component Mapping

| Component type | Token |
|---|---|
| Subtle separators, tiny UI details | shadow-2xs |
| Inputs, small controls | shadow-xs |
| Lightweight cards, list rows on colored sections | shadow-sm |
| Dropdowns, popovers | shadow-md |
| Buttons (the offset block under the body) | shadow-lg |
| Cards (the brand ring stack) | shadow-xl |
| Modals, hero overlays, top-level emphasis | shadow-2xl |

## Rules

- Use only these tokens — no custom box-shadow values in component code
- Shadows are SOLID and OFFSET — never blurred. Blur radius must be 0
- Cards always use the brand ring shadow (`shadow-xl`) — never substitute a single-color shadow
- Buttons always use a colored offset block (`shadow-lg`) and the press effect from `buttons.md`
- Components in the same family share the same baseline shadow
- Hover/focus on interactive elevated elements: shift offset, do not introduce blur
- Never stack multiple shadow tokens on one element

---