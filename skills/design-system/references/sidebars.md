# Sidebars

> Dependencies: `colors.md`, `radius.md`, `typography.md`, `badges.md`, `alerts.md`

## Core Specs

- Background: neutral-primary-soft
- Right border: 2px solid `border-default` (for left-sidebar); left border for right-sidebar
- Width: 280px

## Anatomy

### Outer Container
Hidden on mobile, visible at small breakpoint. Needs a toggle/trigger for mobile.

### Inner Wrapper
- Full height, vertical scroll overflow
- Padding: 16px horizontal, 24px vertical

### Navigation List
- Vertical spacing: 4px between items
- Font: 18px (VT323), normal weight

### Navigation Item
- Layout: flex, vertically centered
- Padding: 12px horizontal, 10px vertical
- Text: heading color
- Radius: 0px — hard rectangle, consistent with the system
- Hover: brand-softer background, fg-brand-strong text
- Transition: colors, 150ms
- Icon: 22x22px, body color, hover → fg-brand-strong, 75ms transition
- Label: 12px left margin from icon

### Active Item
- Background: brand
- Text: white
- Icon: white
- Inline-start indicator: 4px wide solid bar in `secondary-brand` color flush with the inline-start edge

### Separator
- 24px top padding, 24px top margin
- Top border: 2px solid `border-default`
- 8px vertical spacing below
- Optional ALL-CAPS label above the separated group: 14px (VT323), body-subtle

### Bottom CTA / Card
- Padding: 24px
- Top margin: 32px
- Radius: 0px (hard rectangle)
- Background: brand-softer
- Border: 1px solid `border-default`
- Shadow: the brand ring shadow from `cards.md` (or any alert variant from `alerts.md`)

## Rules

- Responsive: hidden on mobile with a trigger mechanism
- Icons: 22x22px, body color (hover: fg-brand-strong)
- Multi-level menus: indent with 32px left padding
- Spacing follows 8px grid
- All radii are 0px — sidebar items are crisp rectangles
- Only neutral, brand, secondary-brand, tertiary-brand, quaternary-brand, or status tokens — no arbitrary colors

---