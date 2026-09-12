# Cards

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `typography.md`

## Core Specs

- **Radius:** 0px (`base`) — cards are crisp rectangles, never rounded
- **Border:** 1px solid `border-default` (the hard, near-black outline that grounds the magazine aesthetic)
- **Shadow:** the **brand ring shadow** — a layered, zero-blur stack of concentric solid rings using the four brand colors plus an outer accent. See `shadows.md` ("Brand Ring Shadow"). This is non-negotiable: every card MUST use this layered ring effect.

### Brand Ring Shadow recipe (agnostic)
A stack of solid concentric rings, no blur, each one offset 3px farther out than the previous:

- Ring 1: 3px ring in `brand` color
- Ring 2: 6px ring in `secondary-brand` color
- Ring 3: 9px ring in `tertiary-brand` color
- Ring 4: 12px ring in `quaternary-brand` color
- Ring 5: 15px ring in `danger` color (final accent stop)

Implementations may stack multiple zero-blur ring shadows or equivalent layered outlines. The visual outcome MUST be five colored concentric rings escalating outward from the card edge.

## Card Background Rule (depends on parent section)

Cards take a *lighter derivative of the section color they sit on*. They never default to plain neutral white when placed on a colored section. Map:

| Parent section background | Card background |
|---|---|
| `brand` | `brand-softer` |
| `secondary-brand` | `secondary-brand-softer` |
| `tertiary-brand` | `tertiary-brand-softer` |
| `quaternary-brand` | `quaternary-brand-softer` |
| `neutral-primary-soft` (rare) | `neutral-primary-medium` |

This keeps each card visually anchored to the hue of its host section while still reading as a raised surface.

## Card Heading

- Desktop: 28px, normal weight (VT323), heading color
- Mobile: 22px, normal weight, heading color
- Never skip heading levels — the page hierarchy must logically arrive at the card heading level
- Optional eyebrow kicker above heading: 14px, ALL CAPS, body-subtle color, 8px bottom margin

## Padding

- Compact card: 24px
- Standard card: 32px
- Spacious / feature card: 48px

The padding must visually clear the inner ring stack so the layered shadow remains fully visible around all four edges. Always leave at least 24px gap between adjacent cards in a grid so their ring shadows do not collide.

## States

### Static Card (no interactivity)
- Background: section-derivative softer color (per the Background Rule above)
- Border: 1px solid `border-default`
- Radius: 0px
- Shadow: brand ring shadow
- No hover styles. Non-interactive cards must NOT change appearance on hover.

### Interactive Card (clickable / linked)
- Same base styles as static card
- Hover: shift the card 4px upward (translate the body, not the shadow) — the ring stack stays anchored, the body lifts off it
- Cursor: pointer
- Transition: transform 200ms

## Rules

- Radius is ALWAYS 0px on cards — never softened
- Border is ALWAYS 1px solid `border-default` — the hard outline is part of the look
- Shadow is ALWAYS the brand ring shadow — single-color shadows are forbidden on card surfaces
- Card background is ALWAYS a lighter derivative of the parent section color
- Maintain at least 24px gap between cards in any grid so ring shadows can breathe
- Never combine the brand ring shadow with a colored offset block (offset blocks are reserved for buttons)

---