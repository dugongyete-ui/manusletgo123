# Typography

> Dependencies: `colors.md`

## Core Rules

- **Font:** "VT323", monospace — single typeface for the entire system, configured at app level, never override
- **Headings:** normal weight (400) — VT323 is a fixed-width pixel typeface and renders as a strong display face at any size; do NOT bump weight to bold (it has only one weight)
- **Body copy:** body text color, normal weight, never use brand color for paragraphs longer than one sentence
- **Letter-spacing:** never tighten below 0; the pixel grid of VT323 must stay legible
- **Semantic HTML:** Use `h1`–`h6` in order, never skip levels
- **Magazine voice:** large, decisive headings; generous leading on body copy; short measure for readable columns

## Heading Scale

### Desktop

| Element | Size | Line-height | Letter-spacing | Margin-bottom |
|---|---|---|---|---|
| `h1` | 96px | 0.95 | 0px | 32px |
| `h2` | 64px | 1 | 0px | 24px |
| `h3` | 48px | 1.05 | 0px | 20px |
| `h4` | 36px | 1.1 | 0px | 16px |
| `h5` | 28px | 1.2 | 0px | 12px |
| `h6` | 22px | 1.25 | 0px | 12px |

### Responsive

| Element | Tablet (≥768px) | Mobile (default) |
|---|---|---|
| `h1` | 64px | 48px |
| `h2` | 48px | 36px |
| `h3` | 38px | 30px |
| `h4` | 30px | 26px |
| `h5` | 24px | 22px |
| `h6` | 20px | 20px |

Mobile-first: start with mobile sizes, scale up at tablet and desktop breakpoints.

Never reduce line-height below 0.95 for any heading.

## Paragraphs

### Leading Paragraph
- Size: 24px
- Weight: normal
- Color: body
- Line-height: 1.55
- Max width: ~58 characters

### Normal Paragraph
- Size: 18px
- Weight: normal
- Color: body
- Line-height: 1.6
- Max width: ~62 characters

### Small Supporting Copy
- Size: 16px
- Weight: normal
- Color: body
- Line-height: 1.5
- Use only for helper text, legal text, captions, metadata.

## UI Labels

| Context | Size | Weight |
|---|---|---|
| Button labels | 18px | 400 (normal — VT323 only has one weight) |
| Input labels | 16px or 18px | 400 |
| Captions / meta / badges | 14px or 16px | 400 |

Do not apply paragraph line-height (1.6) to control labels.

## Emphasis

- `<strong>` for high-priority emphasis in body text — render in `heading` color (no weight change, the typeface is single-weight)
- `<em>` for tone emphasis only, not visual hierarchy
- All-caps for short labels, kickers, and section eyebrows: uppercase, 0px letter-spacing, 14px or 16px

## Magazine Conventions

- Pair every section with a small ALL-CAPS kicker (14–16px) above the main heading
- Pull-quotes use `h3` size, set in brand text color, with a 4px `border-default` rule on the inline-start side
- Drop caps optional on opening paragraphs of long-form articles: 4× line-height, brand color, floated start

## Links

- **Inline links:** Same size as surrounding text, fg-brand color, underline, hover → no underline
- **CTA links:** fg-brand color, normal weight, underline, hover → no underline

## Dark Mode

Hierarchy stays identical. Only color tokens change (automatic via design tokens). Size and spacing remain constant.