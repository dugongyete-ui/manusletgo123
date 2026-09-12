# Tooltips & Popovers

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Tooltips

### Core Specs
- Padding: 12px horizontal, 8px vertical
- Font: 16px (VT323), normal weight
- Radius: 0px (`default`) — hard rectangle, never softened
- Border: 2px solid (matches the magazine outline language)
- Shadow: shadow-xs (a small solid offset block, no blur)
- Transition: opacity, 300ms

### Dark (Default)
- Background: dark
- Text: white
- Border: 2px solid `border-dark`

### Light
- Background: neutral-primary-soft
- Text: heading color
- Border: 2px solid `border-default`

### Brand
- Background: brand-softer
- Text: fg-brand-strong
- Border: 2px solid `border-brand`

## Popovers

### Core Specs
- Background: neutral-primary
- Radius: 0px (`base`) — hard rectangle
- Border: 2px solid `border-default`
- Shadow: shadow-md (offset solid block, no blur). For prominent popovers (e.g., onboarding callouts), upgrade to the brand ring shadow from `cards.md`.
- Transition: opacity, 300ms

### Header / Title
- Padding: 16px horizontal, 12px vertical
- Background: brand-softer
- Bottom border: 2px solid `border-default`
- Font: 18px (VT323), normal weight, fg-brand-strong text

### Body / Content
- Standard: 16px horizontal, 12px vertical padding; 18px (VT323), body color
- Rich: 24px padding; 18px (VT323), body color

## Arrows

- Size: 12x12px rotated 45deg
- Color must match the background of the tooltip/popover variant
- Border: 2px solid (matches the parent's border, on the two outward-facing edges)

## Rules

- Tooltips: 0px radius — hard rectangle
- Popovers: 0px radius — hard rectangle
- Dark tooltips: dark background, white text, 2px solid `border-dark`
- Light tooltips/popovers: semantic neutral background + 2px `border-default`
- Brand tooltips: brand-softer background, fg-brand-strong text, 2px `border-brand`
- Arrows match parent background and border color
- Shadows are SOLID offset blocks — never blurred

---