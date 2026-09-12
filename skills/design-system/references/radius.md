# Border Radius

| Token | Value | Default usage |
|---|---|---|
| base | 0px | Buttons (non-pill), cards, inputs, modals, sections, tabs, tables, popovers — the system is hard-edged |
| default | 0px | Badges, tooltips, dropdown items, small controls |
| sm | 0px | Checkboxes, tiny elements |
| full | 9999px | Pill buttons, avatars, toggles, dot indicators, circular badges |

## Rules

- 0px is the default radius across the entire product — surfaces are crisp rectangles, never softened
- The only allowed non-zero radius is `full` (9999px / 50em), reserved for pill buttons, circular avatars, toggles, and dot indicators
- Never use arbitrary radius values outside this scale (no 4px, 8px, 12px corners anywhere)
- Radius must be consistent within each component family
- The combination of 0px corners + thick borders + offset block shadows is intentional — preserve it

---