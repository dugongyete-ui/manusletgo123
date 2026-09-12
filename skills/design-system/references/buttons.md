# Buttons

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Core Specs (every button except ghost and disabled)

Buttons in this system are **chunky pill buttons** with a thick border, an offset solid block shadow underneath, and a tactile "press" effect on hover and active. The combination of pill radius + thick border + colored offset block is the signature look — preserve it.

- **Radius:** 9999px (`full`) — every button is a pill, regardless of size
- **Border:** 6px solid, `brand-medium` color (the lighter brand tint)
- **Background:** `neutral-primary-medium` (off-white tint)
- **Text color:** `fg-brand` (the strong brand color)
- **Shadow:** `shadow-lg` — a solid 8px vertical offset block in the strong brand color, with no blur
- **Font weight:** 400 (normal — VT323 is single-weight; the typeface itself reads as bold)
- **Font family:** inherit (the global VT323 stack from `typography.md`)
- **Font size:** large (18px+ — see size table)
- **Box sizing:** border-box
- **Cursor:** pointer
- **Transition:** transform and box-shadow on hover/active
- **Position:** relative — required so the press effect can shift the body downward without affecting layout

## The Press Effect (canonical interaction)

On hover AND active, the button "presses down" into its shadow:

- Shift the button body 8px downward (its own height-equal vertical offset, equal to the shadow's offset)
- Collapse the shadow to 0 (the body now sits flush on the surface)
- Tighten the border to a slightly darker tint of the brand color (`border-brand-light`)

Idle ↔ pressed visualization:
- **Idle:** body sits up, 8px solid shadow visible below
- **Hover / Active:** body slides down 8px, shadow disappears, border darkens

This rule applies to every variant except `ghost` and `disabled`.

## Sizes

| Size | Font size | Horizontal padding | Vertical padding |
|---|---|---|---|
| Extra small | 14px | 1.4em | 0.5em |
| Small | 16px | 1.8em | 0.6em |
| Base (default) | 18px | 2.2em | 0.8em |
| Large | 20px | 2.6em | 0.9em |
| Extra large | 22px | 3em | 1em |

Padding is expressed in `em` so it scales with the font size — this keeps the chunky pill proportions consistent at every scale.

## Variants

### Brand (default / primary)
- **Background:** neutral-primary-medium
- **Border:** 6px solid border-brand-subtle
- **Text:** fg-brand
- **Shadow:** 8px solid offset in `brand` color
- **Hover / Active:** press effect — body shifts +8px down, shadow collapses to 0, border darkens to border-brand-light
- **Focus ring:** the offset block shadow doubles as the focus indicator; on focus-visible add a 2px outline in `border-brand` color, 2px outside the body

### Secondary
- **Background:** neutral-primary-medium
- **Border:** 6px solid `secondary-brand-soft`
- **Text:** fg-purple-strong
- **Shadow:** 8px solid offset in `secondary-brand` color
- **Hover / Active:** press effect, border darkens to `secondary-brand`
- **Focus ring:** 2px outline in `border-purple`

### Tertiary
- **Background:** neutral-primary-medium
- **Border:** 6px solid `tertiary-brand-soft`
- **Text:** heading
- **Shadow:** 8px solid offset in `tertiary-brand-strong` color
- **Hover / Active:** press effect, border darkens to `tertiary-brand-strong`
- **Focus ring:** 2px outline in `tertiary-brand-strong`

### Quaternary
- **Background:** neutral-primary-medium
- **Border:** 6px solid `quaternary-brand-soft`
- **Text:** heading
- **Shadow:** 8px solid offset in `quaternary-brand-strong` color
- **Hover / Active:** press effect, border darkens to `quaternary-brand-strong`
- **Focus ring:** 2px outline in `quaternary-brand-strong`

### Success
- **Background:** neutral-primary-medium
- **Border:** 6px solid `success-medium`
- **Text:** fg-success-strong
- **Shadow:** 8px solid offset in `success` color
- **Hover / Active:** press effect, border darkens to `border-success`
- **Focus ring:** 2px outline in `border-success`

### Danger
- **Background:** neutral-primary-medium
- **Border:** 6px solid `danger-medium`
- **Text:** fg-danger-strong
- **Shadow:** 8px solid offset in `danger` color
- **Hover / Active:** press effect, border darkens to `border-danger`
- **Focus ring:** 2px outline in `border-danger`

### Warning
- **Background:** neutral-primary-medium
- **Border:** 6px solid `warning-medium`
- **Text:** fg-warning
- **Shadow:** 8px solid offset in `warning` color
- **Hover / Active:** press effect, border darkens to `border-warning`
- **Focus ring:** 2px outline in `border-warning`

### Dark
- **Background:** dark
- **Border:** 6px solid border-dark-subtle
- **Text:** white
- **Shadow:** 8px solid offset in `dark-strong` color
- **Hover / Active:** press effect
- **Focus ring:** 2px outline in `border-dark`

### Ghost (NO border, NO shadow, NO press effect)
- **Background:** transparent
- **Border:** transparent
- **Text:** heading color
- **Hover:** neutral-secondary-medium background
- **Focus ring:** 2px outline in `border-default`
- **No shadow, no press effect**

### Disabled (NO press effect)
- **Background:** disabled token
- **Border:** 6px solid border-light
- **Text:** fg-disabled color
- **Cursor:** not-allowed
- **Shadow:** none
- **No hover, no focus, no press effect**

## Icons in Buttons

- Icon size: matches the font size of the button (use `1em`)
- Spacing: 0.5em gap between icon and label
- Layout: inline-flex, vertically centered

---