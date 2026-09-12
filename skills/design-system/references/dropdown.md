# Dropdown

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `inputs.md`

## Core Specs

### Chevron Icon
- Size: 16x16px
- Spacing: 8px left margin, 0 right margin
- Color: inherits from trigger button

### Menu Container
- Background: neutral-primary-soft
- Border: 1px solid `border-default` (the hard, near-black outline)
- Radius: 0px (`base`) — hard rectangle
- Shadow: shadow-md (offset solid block, no blur)
- Z-index: elevated above content

### Menu List
- Padding: 8px
- Font: 18px (VT323), body color, normal weight

### Menu Item
- Layout: inline-flex, vertically centered, full width
- Padding: 12px horizontal, 10px vertical
- Radius: 0px (hard rectangle, consistent with the system)
- Hover: brand-softer background, fg-brand-strong text
- Transition: colors, 150ms

## Trigger Sizes

Triggers follow `buttons.md` specs (pill, 6px border, offset shadow, press effect). Sizes:

| Size | Font size | Horizontal padding | Vertical padding |
|---|---|---|---|
| Small | 16px | 1.8em | 0.6em |
| Base | 18px | 2.2em | 0.8em |
| Large | 20px | 2.6em | 0.9em |

## Icon-only Trigger

- Padding: 0.8em (matches button base)
- Min size: 48x48px
- Icon: 20x20px
- Pill radius (9999px) preserved

## Variants

### Default
- Menu min-width: 200px, items have 0px radius

### With Divider
- Top border (1px solid `border-default`) between child groups, skip first group

### With Header
- Header padding: 16px horizontal, 12px vertical
- Bottom border: 1px solid `border-default`
- Name: heading color, 18px (VT323), normal weight
- Email: body-subtle color, 16px (VT323), truncated

### With Icons
- Icon before label: 16x16px, 8px right margin, body color
- On hover, icon color changes to fg-brand-strong

### With Checkbox / Radio
- Inputs: 18x18px, 0px radius, focus outline 2px in `border-brand`
- Helper text: 14px (VT323), body-subtle color, 4px top margin

### With Search
- Search input at top of menu following `inputs.md` specs
- Left icon: 12px left padding, input 36px left padding

### Scrollable
- Max height: 240px, vertical scroll overflow

## States

| State | Appearance |
|---|---|
| Focused trigger | press effect from `buttons.md` + 2px outline in `border-brand` color |
| Hover item | brand-softer background, fg-brand-strong text |
| Active/open item | brand-soft background, fg-brand-strong text |
| Disabled item | fg-disabled text, not-allowed cursor, no pointer events |

---