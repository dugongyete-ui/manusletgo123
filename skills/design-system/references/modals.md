# Modals

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `buttons.md`, `inputs.md`

## Core Specs

### Overlay (Backdrop)
- Fixed, covers full screen
- Z-index: 40
- Background: dark color at 60% opacity
- Backdrop blur: small amount (optional)

### Content Container
- Background: neutral-primary
- Radius: 0px (`base`) — hard rectangle, never softened
- Border: 2px solid `border-default` (the hard outline)
- Shadow: the **brand ring shadow** from `cards.md` / `shadows.md` (layered concentric rings in brand → secondary → tertiary → quaternary → accent)
- Padding: 32px

## Anatomy

### Header
- Bottom border: 2px solid `border-default`
- 0px corners on the header (matches container)
- Title: 28px (VT323), normal weight, heading color
- Optional ALL-CAPS kicker above title: 14px, body-subtle
- Close button: Ghost variant from `buttons.md`, square 32x32px, 0px radius

### Body
- Vertical padding: 32px
- Vertical spacing between elements: 24px
- Text: 18px (VT323), 1.6 line-height, body color

### Footer
- Top border: 2px solid `border-default`
- 0px corners on the footer (matches container)
- Padding: 24px
- Layout: flex, end-aligned for action button group

## Variants

### Default (Information)
Standard header + body + footer with primary/secondary action buttons.

### Pop-up (Confirmation)
Centered text, prominent icon, reduced padding:
- Body: 32px padding, text centered
- Icon: centered, 24px bottom margin, 64x64px, 0px radius square in a brand-softer background tile

### Form Modal
Body contains inputs following `inputs.md`. Vertical spacing between form elements: 20px.

## Rules

- Backdrop covers full screen with fixed positioning
- Content: neutral-primary background, 0px radius, 2px solid `border-default`, brand ring shadow
- Header/Footer separated by 2px solid `border-default`
- Close button must be present and functional
- Accessibility: `role="dialog"`, implement focus trap in code
- Dark mode automatic via the design tokens

---