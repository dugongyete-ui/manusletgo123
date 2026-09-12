# Accordion

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Wrapper:** full width, 1px solid `border-default`, 0px radius — items share a single hard rectangle
- **Item separator:** 1px solid `border-default` bottom border on every item except the last

## Trigger (Button)

- **Layout:** flex, space-between, full width
- **Padding:** 24px horizontal, 20px vertical
- **Font:** 18px (VT323), normal weight
- **Text color:** heading
- **Background:** neutral-secondary-soft
- **Hover:** neutral-tertiary-soft background
- **Focus:** outline none, 2px outline in `border-brand` color, offset 2px
- **Transition:** colors, 150ms
- **Open state:** brand-softer background, fg-brand-strong text

## Panel (Content)

- **Padding:** 24px horizontal, 20px vertical
- **Background:** neutral-primary-soft
- **Top border:** 1px solid `border-default`
- **Font:** 18px (VT323), body color, 1.6 line-height

## Chevron Icon

- Size: 20x20px
- Color: heading text color
- Closed: 0deg rotation
- Open: 180deg rotation
- Transition: transform, 150ms

## Variants

### Default (Collapse)
One panel open at a time. Items stacked inside a single shared bordered wrapper. Radius: 0px.

### Separated Cards
Each item is independent — has its own 1px `border-default` outline, 0px radius, and the **brand ring shadow** from `shadows.md`. 32px bottom margin between items so ring shadows do not collide. No shared outer border.

### Always Open
Multiple panels can expand simultaneously. Same styling as Default.

### Flush
No outer border. Trigger and panel have transparent backgrounds. Only bottom border dividers (1px solid `border-default`) between items. Use inside containers that already provide a background.

## States

| State | Trigger appearance |
|---|---|
| Closed | heading text, neutral-secondary-soft background |
| Open | fg-brand-strong text, brand-softer background |
| Hover | neutral-tertiary-soft background |
| Focus | 2px brand outline, offset 2px |
| Disabled | fg-disabled text, not-allowed cursor, no hover/focus |

---