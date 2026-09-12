# Tabs

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Core Specs

- Typography: 18px (VT323), normal weight, body color
- Transitions: all properties, 200ms

## Variants

### 1. Underline (Default)

**Wrapper:** bottom border, 2px solid `border-default`

**Tab Item:**
- Padding: 20px horizontal, 16px vertical
- Bottom border: 4px solid transparent (the active rule is heavy and editorial)
- Top corners: 0px radius
- Transition: colors, 150ms

| State | Appearance |
|---|---|
| Active | fg-brand text, 4px solid `border-brand` bottom border |
| Inactive | transparent bottom border; hover → heading text, 4px solid `border-default-medium` bottom border |
| Disabled | fg-disabled text, not-allowed cursor |

### 2. Pills

**Tab Item:**
- Padding: 1.4em horizontal, 0.6em vertical (em-based to scale with font)
- Radius: 9999px (`full`) — pill shape, matching button style
- Border: 4px solid `border-default-subtle` (lighter than buttons but still chunky)
- Font weight: normal (VT323)
- Transition: all, 200ms

| State | Appearance |
|---|---|
| Active | brand background, white text, 4px solid `border-brand` |
| Inactive | neutral-primary-soft background, body text; hover → brand-softer background, fg-brand-strong text |
| Disabled | fg-disabled text, not-allowed cursor |

### 3. Full Width

Children sit side-by-side with **8px gap** (no border collapse — each tab keeps its own outline).

**Tab Item:**
- Full width, centered text
- Padding: 20px horizontal, 16px vertical
- Background: neutral-primary-soft
- Border: 2px solid `border-default`
- Radius: 0px — hard rectangle
- Transition: colors, 150ms
- Hover: brand-softer background, fg-brand-strong text

| State | Appearance |
|---|---|
| Active | brand background, white text, 2px solid `border-brand` |
| First / Last item | 0px radius (no rounding) |

## Tabs with Icons

- Icon size: 18x18px or 22x22px
- Spacing: 8px right margin
- Layout: inline-flex, centered
- Icons inherit the text color of the tab state

---