# Inputs

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Display:** block, full width
- **Radius:** 0px (`base`) — hard rectangle, never softened
- **Border:** 2px solid `border-default` (the hard, near-black outline that anchors the magazine system)
- **Background:** neutral-primary-soft
- **Shadow:** none on idle (the thick border carries the visual weight); the offset block shadow appears only on focus
- **Font:** 18px (VT323), heading color
- **Padding:** 14px horizontal, 12px vertical
- **Placeholder:** body-subtle color
- **Transition:** all properties, 200ms

## Label

- Display: block
- Font: 16px (VT323), normal weight, heading color, ALL CAPS optional for the magazine kicker style
- Margin bottom: 8px
- Label `htmlFor` must match the input `id`

## States

### Default
- Border: 2px solid `border-default`
- Background: neutral-primary-soft
- Shadow: none

### Hover
- Border: 2px solid `border-brand-light`

### Focus
- No outline
- Border: 2px solid `border-brand`
- Shadow: 4px solid offset in `brand` color (no blur), positioned bottom-right (matching the button shadow language)

### Success
- Border: 2px solid `border-success`
- Focus shadow: 4px solid offset in `success` color

### Error / Danger
- Border: 2px solid `border-danger`
- Focus shadow: 4px solid offset in `danger` color

### Disabled
- Background: disabled
- Border: 2px solid `border-light`
- Text: fg-disabled
- Cursor: not-allowed

## Input with Icons

- Icon size: 18x18px
- Icon color: body
- Container: relative positioned wrapper
- Start icon: absolutely positioned left, 14px left padding — input gets 44px left padding
- End icon: absolutely positioned right, 14px right padding — input gets 44px right padding
- Icons vertically centered within the wrapper

## Rules

- Every input must have a unique `id`
- Every label must have a matching `htmlFor`
- Padding: 14px horizontal, 12px vertical unless overridden for icon variants
- Radius is ALWAYS 0px — inputs are never rounded
- Border is ALWAYS 2px solid — inputs read as labeled, framed fields
- No arbitrary hex or hardcoded colors

---