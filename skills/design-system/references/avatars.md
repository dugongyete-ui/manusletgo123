# Avatars

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Circular shape:** fully rounded (9999px)
- **Square shape:** 0px radius — hard rectangle, never softened
- **Default size:** 48x48px
- **Image fit:** cover
- **Border:** 2px solid `border-default` on every avatar (the hard outline ties them to the magazine system)

## Sizes

| Size | Dimensions | Radius |
|---|---|---|
| Extra Small | 20x20px | 0px or 9999px |
| Small | 28x28px | 0px or 9999px |
| Base | 36x36px | 0px or 9999px |
| Large | 48x48px | 0px or 9999px |
| XL | 64x64px | 0px or 9999px |
| 2XL | 80x80px | 0px or 9999px |

The default system avatar is the **square 0px** variant — circular avatars are reserved for stacked groups and chat-style contexts.

## Bordered Avatar

- 4px padding
- 2px outline in `border-default` color (always solid, never colored)
- For circular avatars, use a 2px solid ring in `border-default`

## Stacked Avatars

- Displayed in a row (flex)
- Each avatar: 48x48px, fully rounded, 3px solid border in `border-buffer` color
- Overlap: -16px negative margin on all except first

### Stacked Counter
- Same size as avatars (48x48px), fully rounded
- Background: dark-strong, text: white, 16px (VT323), normal weight
- Same overlap margin as other avatars

## Avatar with Text

- Flex row, 12px gap between avatar and text
- Avatar: 48x48px, fully rounded or 0px square, cover fit
- Name: heading color, normal weight, 18px (VT323)
- Subtitle: 16px (VT323), body color

---