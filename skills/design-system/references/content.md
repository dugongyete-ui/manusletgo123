# Content & Grid System

> Dependencies: `layout.md`, `typography.md`

## Containers

| Type | Max width | Horizontal padding |
|---|---|---|
| Standard | 1200px | 32px |
| Internal (reading column) | 720px | — (45–62 char line length, magazine measure) |

## Vertical Padding

| Breakpoint | Vertical padding |
|---|---|
| Mobile | 64px |
| Tablet (≥768px) | 96px |
| Desktop (≥1024px) | 128px (hero/feature sections may extend to 160px) |

## Grid System

Mobile-first with flexible desktop configurations. All grid gaps must be wide enough to clear the brand ring shadow on cards (see `cards.md`).

| Context | Gap |
|---|---|
| Standard content/cards | 32px |
| Compact widgets/metadata | 24px |
| Editorial column layouts | 48px |

### Responsive Columns

| Breakpoint | Columns |
|---|---|
| Mobile (default) | 1 |
| Small/Tablet (≥640px) | 2 |
| Desktop (≥1024px) | 2–4 (magazine layouts favor 2 and 3 column compositions) |

Six+ column grids are reserved for compact metadata strips and footer link blocks.

## Breakpoints

| Name | Width |
|---|---|
| Small | 640px |
| Medium | 768px |
| Large | 1024px |
| Extra large | 1280px |
| 2x Extra large | 1536px |

## Rules

- Always design mobile-first
- Use layout shifts (column → row) to accommodate horizontal space
- Lists: 24px indentation, 12px vertical gap between items
- Body copy: 18px (VT323), 1.6 line-height
- All interactive links follow brand underline / hover protocol from `typography.md`
- Card grids must use a minimum 32px gap so the brand ring shadows can breathe

---