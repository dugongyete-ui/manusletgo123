# Borders

## Width Scale

| Context | Width |
|---|---|
| Default (inputs, cards, containers) | 1px |
| Emphasis / focus | 2px |
| Buttons (the chunky pill outline) | 6px |
| Heavy editorial dividers, section rules | 4px |

## Rules

- Use solid borders by default — the hard, near-black `border-default` line is the magazine-print baseline of this system
- Dashed borders only for special cases like file dropzones
- Components in the same family must use matching border widths
- Never mix 1px and 2px borders within a single component (the 6px button border is its own family)
- The thick 6px button border is non-negotiable — it is the signature of the system and must never be reduced

## Usage

| Context | Width |
|---|---|
| Inputs / selects / textareas | 1px default; 2px on focus or error |
| Buttons | 6px solid (always — pill outline) |
| Cards / containers | 1px solid `border-default` (the hard outline) |
| Section dividers / hairlines | 4px solid `border-default` for editorial rules; 1px for hairlines |

---