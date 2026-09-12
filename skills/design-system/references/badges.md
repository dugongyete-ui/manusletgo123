# Badges

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Border:** 2px solid (heavier than default — badges are tiny editorial labels and the thick outline keeps them legible)
- **Default radius:** 0px (`default`) — hard rectangle
- **Pill radius:** 9999px (`full`)
- **Font:** VT323 (inherits global), uppercase by convention for status labels

## Sizes

| Size | Font size | Horizontal padding | Vertical padding |
|---|---|---|---|
| Default (small) | 14px | 8px | 2px |
| Large | 16px | 10px | 4px |

## Variants

### Brand
- **Background:** brand-softer
- **Border:** 2px solid `border-brand`
- **Text:** fg-brand-strong

### Secondary
- **Background:** secondary-brand-softer
- **Border:** 2px solid `border-purple`
- **Text:** fg-purple-strong

### Tertiary
- **Background:** tertiary-brand-softer
- **Border:** 2px solid `tertiary-brand-strong`
- **Text:** heading

### Quaternary
- **Background:** quaternary-brand-softer
- **Border:** 2px solid `quaternary-brand-strong`
- **Text:** heading

### Alternative (Neutral Soft)
- **Background:** neutral-primary-soft
- **Border:** 2px solid `border-default`
- **Text:** heading

### Gray (Neutral Medium)
- **Background:** neutral-secondary-medium
- **Border:** 2px solid `border-default`
- **Text:** heading

### Danger
- **Background:** danger-soft
- **Border:** 2px solid `border-danger`
- **Text:** fg-danger-strong

### Success
- **Background:** success-soft
- **Border:** 2px solid `border-success`
- **Text:** fg-success-strong

### Warning
- **Background:** warning-soft
- **Border:** 2px solid `border-warning`
- **Text:** fg-warning

### Dark
- **Background:** dark
- **Border:** 2px solid `border-dark`
- **Text:** white

## Pill Badges

Use 9999px radius (`full`) instead of 0px on any variant. Use sparingly — the default magazine convention is the hard rectangle badge.

## Badges with Icons

- Icon size (default): 14x14px
- Icon size (large): 16x16px
- Icon spacing: 4px margin next to label

## Icon-only Badge

Square shape — equalize dimensions to 28x28px, no horizontal text padding, 0px radius.

## Dismissible Badges

Badge content + a close button. Close button hover backgrounds per variant:

| Variant | Close button hover background |
|---|---|
| Brand | brand-soft |
| Secondary | secondary-brand-soft |
| Tertiary | tertiary-brand-soft |
| Quaternary | quaternary-brand-soft |
| Alternative | neutral-tertiary |
| Gray | neutral-quaternary |
| Danger | danger-medium |
| Success | success-medium |
| Warning | warning-medium |

## Dot / Notification Badge

- Positioned absolutely: -4px top, -4px right
- Size: 12x12px, fully rounded
- 2px solid border in `border-buffer` color
- Background: danger

---