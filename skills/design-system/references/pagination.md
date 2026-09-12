# Pagination

> Dependencies: `colors.md`, `radius.md`

## Container

Font: 18px (VT323). Items displayed as flex with **8px gap** between items — each item keeps its own outline; pagination items are NOT collapsed into a segmented strip.

## Pagination Item

- Layout: flex, centered both axes
- Size: 44x44px
- Text: heading color, normal weight (VT323)
- Background: neutral-primary-soft
- Border: 2px solid `border-default`
- Radius: 0px — hard rectangle, never softened
- Hover: brand-softer background, fg-brand-strong text
- Focus: no outline, 2px outline in `border-brand` color, offset 2px

## Previous / Next Buttons

- Horizontal padding: 16px, height: 44px
- Same 2px solid `border-default`, 0px radius rectangle as numeric items
- ALL-CAPS labels (PREV / NEXT) in 16px VT323

## Active Page Item

- Text: white
- Background: brand
- Border: 2px solid `border-brand`
- Hover: stays in active state — no transition out

## Rules

- Display as flex with 8px gap (no -1px overlap, no border collapse)
- Items: neutral-primary-soft background, 2px solid `border-default`, heading text, 0px radius
- Active: white text on `brand` background, 2px solid `border-brand`
- All items need hover and focus states
- No arbitrary hex codes — use token colors only

---