# Design System — J Training Console

Match Gauntlet DevSpace's aesthetic exactly so the training console feels like an extension of the IDE, not a separate product.

## Color palette

```
--void      : #0A0E14   /* primary background */
--steel     : #131820   /* card / panel background */
--alloy     : #6B7A8F   /* muted text, dividers */
--gridwhite : #E4E9F0   /* body text */
--cyan      : #7EE1E5   /* primary accent — buttons, active states, headings */
--viridian  : #4ADE80   /* success / running / complete */
--amber     : #F59E0B   /* warning / val_loss / uploading */
--orange    : #F97316   /* error / failed / cancelled */
--rose      : #F43F5E   /* destructive actions (delete, rollback) */
```

**Contrast rule:** never place colored text on colored background. Colored text always sits on `--void` or `--steel`.

## Typography

- **UI type:** `JetBrains Mono`, fallback `IBM Plex Mono`, `SF Mono`, monospace
- **Body:** `Inter` for prose paragraphs only (not labels — labels are mono)
- **All uppercase text** uses `tracking-widest` (letter-spacing: 0.15em)

Scale:
- Page titles: `1.5rem` uppercase widest, cyan
- Section headers: `0.85rem` uppercase widest, alloy
- Table cell text: `0.75rem` mono
- Big numbers (hero cards): `2.5rem` mono cyan
- Muted small text: `0.65rem` alloy

## Spacing

Use these tokens only:
- `2px` (`--space-1`) — icon gaps
- `4px` (`--space-2`) — element padding
- `8px` (`--space-3`) — button padding, tight groups
- `12px` (`--space-4`) — card inner padding
- `16px` (`--space-5`) — section gaps
- `24px` (`--space-6`) — page section gaps
- `48px` (`--space-8`) — header offset

## Borders / dividers

- 1px solid `rgba(126, 225, 229, 0.2)` — subtle cyan tint on all panels
- Never use `border-radius` above `2px`. Sharp corners.
- Never use `box-shadow`. Depth comes from color contrast.

## Iconography

- **Phosphor Icons** only (Bubble has a free Phosphor plugin)
- Weight: `regular` for inline, `fill` for active/selected states
- Size: `12px` inline, `16px` for buttons, `20px` for page titles
- Never use emoji as UI icons

## Buttons

### Primary
```
border: 1px solid cyan
color: cyan
background: transparent
hover: background rgba(cyan, 0.1)
padding: 8px 16px
font: 0.75rem mono uppercase widest
```

### Secondary
```
border: 1px solid alloy
color: alloy
hover: color gridwhite, border cyan
```

### Destructive
```
border: 1px solid rose
color: rose
hover: background rgba(rose, 0.1)
```

Every button includes an arrow (`→`) or icon on the right, `weight="bold"` on hover.

## Cards / panels

```
background: --steel
border: 1px solid rgba(cyan, 0.2)
padding: 16px
```

Never round the corners. Never shadow. Border is the only depth.

## Tables

- Header row: `0.65rem` mono uppercase widest, alloy
- Data rows: `0.75rem` mono
- Row hover: background `rgba(cyan, 0.02)` (barely perceptible)
- Divider between rows: 1px `rgba(cyan, 0.1)`
- Fixed cell padding: `8px 12px`

## Badges

Small, rectangular, uppercase mono.

```
padding: 2px 6px
font-size: 0.6rem
border: 1px solid <status-color>
color: <status-color>
background: transparent
```

Status colors:
- `queued` → alloy
- `running` → cyan (with a subtle pulse animation)
- `uploading` → amber
- `evaluating` → amber
- `complete` → viridian
- `failed` → orange
- `cancelled` → alloy

## Charts

- Background: `--void`, no grid, no axis boxes
- Axis lines: 1px alloy
- Axis labels: `0.6rem` mono alloy
- Data lines: 1.5px, colors from palette (cyan/amber/viridian)
- No smoothing; step interpolation for training curves

## Loading states

Use skeleton rectangles the size of the final content, pulsing between `--steel` and `rgba(cyan, 0.05)`. No spinners.

## Empty states

Muted alloy text in a monospace comment style:
```
// nothing yet. Export a dataset and start your first run.
```

## Micro-interactions

- Buttons: `transition: all 120ms ease-out`
- Table rows: `transition: background 80ms`
- Chart updates: no animation (data changes are meaningful — flashing is distracting)
- Toast: fade in 200ms, hold 5s, fade out 300ms

## Full CSS token export

Paste this into Bubble's app settings → Custom CSS to get all tokens:

```css
:root {
  --void: #0A0E14;
  --steel: #131820;
  --alloy: #6B7A8F;
  --gridwhite: #E4E9F0;
  --cyan: #7EE1E5;
  --viridian: #4ADE80;
  --amber: #F59E0B;
  --orange: #F97316;
  --rose: #F43F5E;
  --border: rgba(126, 225, 229, 0.2);
}
body {
  background: var(--void);
  color: var(--gridwhite);
  font-family: 'JetBrains Mono', 'IBM Plex Mono', 'SF Mono', monospace;
}
.panel {
  background: var(--steel);
  border: 1px solid var(--border);
  padding: 16px;
}
.uppercase-widest {
  text-transform: uppercase;
  letter-spacing: 0.15em;
}
@keyframes pulse-cyan {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.pulse { animation: pulse-cyan 2s ease-in-out infinite; }
```

## Screenshot exemplars

For visual reference, Bubble builder should look at these screenshots from Gauntlet DevSpace itself:
- `docs/design/screenshots/ide-main.png` — cockpit layout, sidebar + main
- `docs/design/screenshots/admin-panel.png` — the abuse dashboard (nearest analog to what Training Console should feel like)
- `docs/design/screenshots/byok-card.png` — form styling, buttons, inputs

If those files don't exist yet, the Emergent side will drop them into `docs/design/screenshots/` before the Bubble handoff.
