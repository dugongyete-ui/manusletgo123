# Tables

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Wrapper

- Horizontal scroll overflow
- Background: neutral-primary-soft
- Radius: 0px (`base`) — hard rectangle
- Border: 2px solid `border-default` (the magazine outline)
- Shadow: the brand ring shadow from `cards.md` is OPTIONAL on top-level data tables (omit when nested inside a card to avoid stacking ring shadows)

## Table Element

- Full width, left-aligned text (right-aligned for RTL)
- Font: 18px (VT323), body color

## Table Head

- Font: 16px (VT323), heading color, normal weight, ALL CAPS (magazine convention for column labels)
- Background: brand-softer
- Bottom border: 2px solid `border-default`
- Cell padding: 24px horizontal, 16px vertical

## Table Body

- Row background: neutral-primary
- Row bottom border: 1px solid `border-default` (omit on last row to avoid doubling with the wrapper border)
- Row hover: brand-softer background (optional)
- Row header: heading color, no-wrap, normal weight (VT323 already reads as bold)
- Cell padding: 24px horizontal, 16px vertical

### Striped Variant (optional editorial alternative)
- Even rows: neutral-secondary-soft background
- Odd rows: neutral-primary background

## Rules

- Wrapper must have horizontal scroll overflow for responsive scrolling
- Last row: omit bottom border to avoid doubling with wrapper border
- Row headers: always `scope="row"` for semantic structure
- Hover on rows is optional
- Radius is ALWAYS 0px on the wrapper and on all cells
- No arbitrary hex codes — use token colors only

---