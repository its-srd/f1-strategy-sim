# Design system: "Pit wall at night"

The site's visual language, written down so it can be rebuilt anywhere
(Figma, another front end). Source of truth in code: `web/src/styles.css`
(tokens at the top), `web/src/ui/motion.ts`, `web/src/ui/replay.tsx`.

## Principles

1. **Minimal surfaces, loud data.** Near-black ink planes, hairline
   structure, no decoration. The only saturated colour is in data marks and
   one accent.
2. **One accent that means something.** Violet is the timing-screen colour
   for "fastest". It marks the active control, your car, the hero figure
   and the primary action. Nothing else.
3. **Motion explains, never decorates.** Every animation shows where a
   number or shape comes from (a bar grows from its baseline, a line draws
   along the race, a row slides to its new place). All of it stops for
   visitors who ask their system for reduced motion.
4. **Everything is connected.** Hover a driver anywhere (table, legend,
   stint map, replay) and every chart brings that driver forward.

## Colour tokens

### Surfaces and ink

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0A0B10` | Page plane (with two faint violet/cyan radial glows) |
| `--surface-1` | `#11131A` | Panels, cards, chart surface |
| `--surface-2` | `#161923` | Inputs, segmented controls |
| `--surface-3` | `#1D2130` | Hover, chips, tracks |
| `--line` | `rgba(255,255,255,0.07)` | Hairline borders |
| `--grid` | `#1F2330` | Chart gridlines (solid, 1px) |
| `--axis` | `#343A4C` | Axes, crosshair |
| `--text-primary` | `#F2F3F7` | Headings, values (16.7:1 on panel) |
| `--text-secondary` | `#B3B8C7` | Body, labels (9.4:1) |
| `--text-muted` | `#878EA0` | Hints, axis text (5.6:1) |

### Accent

| Token | Value | Use |
|---|---|---|
| `--accent` | `#7C4DFF` | Primary button, active pills, your car's marker; white text on it 4.8:1 |
| `--accent-text` | `#B9A3FF` | Accent used as text or line on dark (8.6:1) |
| `--accent-soft` | `rgba(124,77,255,0.14)` | Selected-state wash, focus halo |
| `--grad` | `#7C4DFF → #6366F1 → #22D3EE` | Brand mark, progress, win ring (sparingly) |

### Data

Chart series follow the dataviz skill's validated dark palette, checked
against the panel surface `#11131A` (all checks pass; worst adjacent pair
colour-blind ΔE 8.4, normal vision 19.3):

| Slot | Value |
|---|---|
| 1 | `#3987E5` |
| 2 | `#D95926` |
| 3 | `#199E70` |
| 4 | `#C98500` |
| 5 | `#D55181` |
| other | `#3A4050` |

Tyres keep the Pirelli convention, re-stepped so medium and hard stay apart
(worst pair colour-blind ΔE 15.7, normal vision 21.2). Hard is near-white by
convention, so every tyre also carries its letter:

| Compound | Value | Letter |
|---|---|---|
| Soft | `#E5484D` | S |
| Medium | `#F0A20B` | M |
| Hard | `#DFE3EC` | H |
| Intermediate | `#1AA36F` | I |
| Wet | `#3987E5` | W |

Status colours are fixed and never used for data: good `#0CA30C`,
warning `#FAB219`, critical `#D03B3B`.

## Type

System sans (`system-ui, -apple-system, Segoe UI, Roboto`), no display face.
Proportional figures for big standalone numbers, tabular figures in tables.

| Role | Size / weight |
|---|---|
| Hero figure (win probability) | 48 / 650, tracking −0.02em |
| Stat tile value | 26 / 650 |
| Panel title | 14.5 / 650 |
| Body | 13.5 / 400, line height 1.5 |
| Secondary and hints | 12 / 11.5 |
| Section label | 11 / 600, uppercase, tracking 0.09em, numbered `01`–`05` in accent mono |
| Mono (laps, codes, timings) | `ui-monospace`, 11–12 |

## Shape and space

Radius 8 (controls), 14 (panels and cards), full pill (tabs, chips).
Spacing on a 4-point grid; panels 16–18 padding, 14 between panels.
Chart marks per the dataviz skill: 2px lines, bars at most 24px with a 4px
rounded data end, hairline solid grid, 2px surface ring on markers.

## Motion

| Token | Value | Used for |
|---|---|---|
| `--ease` | `cubic-bezier(0.22, 1, 0.36, 1)` | Everything that settles |
| `--ease-io` | `cubic-bezier(0.65, 0, 0.35, 1)` | Loops (empty state) |
| `--t1` | 140 ms | Hover, press, tooltip |
| `--t2` | 260 ms | Pills sliding, panels dimming, rows reordering |
| `--t3` | 700 ms | Data entering (bars, lines) |

| Moment | Behaviour |
|---|---|
| Page load | Brand mark draws its racing line, then the dot pops |
| Results arrive | Panels rise in sequence (70 ms stagger); the win ring and every stat count up; probability bars grow from the left row by row; position strips fade in |
| Charts | Race-trace lines draw along the race (background first, highlighted drivers last); stint bars sweep in row by row; time-breakdown bars grow from zero |
| Re-simulating | The previous results stay and dim to 42% (no skeleton flash, no layout jump); the Simulate button fills with the gradient as progress; a 2px gradient line runs along the top of the results |
| Controls | Segmented controls and tabs slide an indicator to the selected option; buttons lift on hover and press in |
| Focus | Hovering a driver fades the rest of the field in every chart (260 ms) |
| Replay | Auto-plays once when scrolled into view; rows slide to their new positions (420 ms); a PIT tag pops on the stop lap; an SC / VSC / red-flag badge appears on those laps |
| Reduced motion | All of the above is switched off; numbers show their final value and the replay waits at the last lap |

## Components

- **Hero win card**: ring gauge (8px stroke, gradient arc over a surface-3
  track) + 48px figure + driver and team. Exactly one per view.
- **Stat tile**: label (11 uppercase) · value (26) · one line of context.
- **Segmented control**: surface-2 track, accent-soft sliding pill with a
  violet hairline; `--n` options, `--idx` selected.
- **Primary button**: accent fill, soft violet glow, gradient sheen on
  hover, progress fill while busy, `⌘↵` hint.
- **Run dock**: sticks to the bottom of the controls column so Simulate is
  always in reach.
- **Probability table**: tabular numerals; your car marked by a 3px accent
  edge and violet wash; rows highlight on hover and drive the page focus.
- **Race replay**: play/pause, lap read-out, scrubber whose track shows
  SC / VSC / red laps, 1× / 2× / 4×, and a timing tower (position, code,
  tyre chip, gap bar, gap).

## Accessibility checks

- Text contrast on the panel surface: primary 16.7:1, secondary 9.4:1,
  muted 5.6:1, accent text 8.6:1; white on the accent button 4.8:1.
- Chart and tyre palettes validated with the dataviz skill's
  `validate_palette.js` against `#11131A` (results above).
- Keyboard: every control is a native button, select or range; focus ring
  `--accent-text`; `⌘↵` / `Ctrl+↵` runs a simulation.
- `prefers-reduced-motion` disables all animation and auto-play.
