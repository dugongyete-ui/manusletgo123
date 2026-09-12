# Radios, Checkboxes & Toggles

> Dependencies: `colors.md`, `radius.md`

## Checkbox

- Size: 20x20px
- Radius: 0px (`sm`) — hard rectangle, never softened
- Border: 2px solid `border-default`
- Background: neutral-primary-soft
- Focus outline: 2px solid `border-brand`, offset 2px
- Checked: brand background, white check mark

### Disabled
- Border: 2px solid `border-light`
- Text: fg-disabled
- Background: disabled

## Radio

- Size: 20x20px
- Radius: fully rounded (9999px) — radios remain circular for affordance
- Border: 2px solid `border-default`
- Background: neutral-primary-soft
- Focus outline: 2px solid `border-brand`, offset 2px
- Checked: 2px solid `border-brand`, indicator: brand-color filled inner circle (8px)

### Disabled
- Border: 2px solid `border-light`
- Text: fg-disabled

Group all radio items under the same `name` attribute.

## Toggle

### Track
- Radius: 0px — the toggle is a hard rectangle (this system favors squared switches over round pill switches)
- Width: 48px, Height: 24px
- Background: neutral-quaternary
- Border: 2px solid `border-default`
- Focus-within outline: 2px solid `border-brand`, offset 2px
- Checked track: brand background
- Disabled track: neutral-tertiary background

### Thumb
- Radius: 0px (square thumb, sized to 16x16px)
- Background: white
- Border: 2px solid `border-default`
- Translates from inline-start to inline-end on toggle (16px travel)

### Disabled
- Track: neutral-tertiary background
- Label: fg-disabled text

## Rules

- All selection inputs must have `id` matching label `htmlFor`
- Focus states use a 2px solid `border-brand` outline offset 2px from the control
- Disabled states: no hover/focus interaction
- Checkboxes and toggles are square (0px radius); only radios remain circular

---