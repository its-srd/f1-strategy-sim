# Design system: "Race-control timing document"

The site's visual language, written down so it can be rebuilt anywhere
(Figma, another front end). Source of truth in code: `web/src/styles.css`
(tokens at the top) and the components in `web/src/ui/`.

This replaces the dark "pit wall at night" look (violet accent, glows,
rounded cards, a ring gauge). That look read as machine-made because it is
the default of a thousand dashboards. This one borrows from something real
that the audience already reads: the printed classification, lap chart and
tyre-history sheets published after every race.

## Principles

1. **Look like a document, not a dashboard.** Warm paper, black ink, firm
   printed rules, square corners. Sections are titled like timing sheets
   (Classification forecast, Gap chart, Tyre history, Lap chart, Track data
   sheet), with a reference line in mono on the right.
2. **One signal colour.** Marshal orange marks your car, the primary action
   and the selected state. Nothing else is orange.
3. **Keep the timing screens' colour meanings.** Purple = best value in a
   column; green ▲ = places gained; red ▼ = places lost; yellow = SC / VSC;
   red = red flag; chequered = finished.
4. **Interaction you can touch.** Pick a grid box, drag a pit stop, click a
   stint to change tyre, scrub the replay, hover any driver to find them in
   every chart.
5. **Motion borrowed from the sport.** Start lights for progress, rolling
   timing-board digits, a timing tower whose rows slide, a lap chart that
   draws as the replay runs, a chequered sweep for the winner. All of it
   stops for visitors who ask their system for reduced motion.

## Colour tokens

### Paper and ink

| Token | Value | Use |
|---|---|---|
| `--paper` | `#F2EFE7` | Page, with a faint printed grain |
| `--sheet` | `#FBFAF6` | Panels (the "sheets"), setup column |
| `--ink` | `#141414` | Text, rules, bars, the timing tower, hero block (17.6:1 on sheet) |
| `--ink-2` | `#3E3B35` | Body text (10.7:1) |
| `--ink-3` | `#6B6860` | Labels, axis text, hints (5.3:1) |
| `--rule` | ink at 14% | Hairlines inside a sheet; sheet edges are full ink |

### Signal and timing colours

| Token | Value | Use |
|---|---|---|
| `--signal` | `#E8501F` | Your car, primary button, selected grid box, tab underline. Fills only: ink on it is 4.9:1; never used as text on paper (3.3:1) |
| `--signal-ink` | `#B23A12` | Orange used as text |
| `--purple` | `#6D2FD0` | Best value in a column (6.2:1) |
| `--gain` / `--loss` | `#0F7537` / `#B3261E` | Places gained / lost |

### Data

Chart series, validated with the dataviz skill's `validate_palette.js`
against the sheet (`#FBFAF6`, light mode): all checks pass (worst adjacent
pair colour-blind ΔE 19.9, normal vision 24.0). Slots 2 and 4 are below 3:1
against the sheet, so their lines always carry a direct label (the driver
code) and the numbers are also in the classification table:

| Slot | Value |
|---|---|
| You | `#E8501F` |
| 1 | `#2A78D6` |
| 2 | `#1BAF7A` |
| 3 | `#6250D6` |
| 4 | `#E87BA4` |
| others | ink at 20% |

Colour follows the driver, not the rank, and is the same in the gap chart,
the lap chart and the legend.

Tyres keep the Pirelli colours. Yellow and white cannot stand on paper by
colour alone (medium fails the contrast check), so every tyre mark has an
ink outline and its letter:

| Compound | Value | Letter |
|---|---|---|
| Soft | `#E0302B` | S |
| Medium | `#F2B705` | M |
| Hard | `#FFFFFF` | H |
| Intermediate | `#1F9E4A` | I |
| Wet | `#1F6FD1` | W |

On the black timing tower a tyre is a ring in its colour with the letter
inside, as on the broadcast graphics.

The finishing-position strip uses one ink ramp (light = rare, dark =
likely), never a hue.

## Type

IBM Plex, bundled with the site through `@fontsource` (SIL Open Font
Licence), Latin subsets only.

| Role | Face / size |
|---|---|
| Wordmark, hero figure, stat values, lap counter | Plex Sans Condensed 600–700 *italic*, 22–68 px |
| Section and panel titles | Plex Sans Condensed 700, uppercase, 15–18 px |
| Labels, reference lines, tables, axes | Plex Mono 400–600, 10–12.5 px, uppercase for labels |
| Body and hints | Plex Sans 400, 14 / 12 px |

Tables use tabular figures. There are no numbered chips and no gradient
text.

## Shape and space

- Square corners everywhere (tyre dots and start lamps are the only circles).
- Sheets: 1 px ink border, no shadow. The empty sheet, start lights and
  primary button use a hard 4–6 px offset shadow, like a stacked print.
- Primary button: orange block with an ink offset shadow that presses in
  (`translate(4px, 4px)`); while busy it turns ink and fills with orange as
  progress.
- Spacing on a 4-point grid; 18 px inside sheets, 18 px between them.

## Motion

| Token | Value | Used for |
|---|---|---|
| `--ease` | `cubic-bezier(0.2, 0.8, 0.2, 1)` | Things that settle |
| `--snap` | `cubic-bezier(0.7, 0, 0.2, 1)` | Things that move with intent (indicators, rows, wipes) |
| `--t1` | 120 ms | Hover, press |
| `--t2` | 240 ms | Indicators sliding, rows dimming |
| `--t3` | 650 ms | Bars growing |

| Moment | Behaviour |
|---|---|
| Page load | The masthead's top rule and every section rule wipe in from the left |
| Running | Start lights: five columns of red lamps light one by one with progress; the previous result greys out underneath |
| Result arrives | Lights out, then the gantry lifts away; sheets wipe in left to right in sequence; hero and stats roll in digit by digit; table rows slide in and bars grow from zero; the hero's finishing-position histogram rises |
| Grid picker | The chosen box fills orange; after qualifying the other cars visibly shuffle back |
| Strategy strip | Pit markers drag (pointer or arrow keys, Shift = 5 laps) with a live "PIT Lnn" tag; a stint flashes when its tyre changes; hatched when past the cap |
| Replay | Plays once when scrolled into view: tower rows slide to new places, ▲ / ▼ count places since lap 1, PIT tags pop, a flag badge shows SC / VSC / red laps; the lap chart is revealed up to the current lap with each code riding the front of its line; on the last lap a chequered band sweeps the winner's row |
| Focus | Hovering a driver anywhere (table, legend, tyre history, tower, lap chart) brings that driver forward in every chart |
| Reduced motion | All of the above is off: numbers show their value, lights simply appear and go, the replay waits at the last lap |

## Components

- **Masthead**: 4 px ink top rule; wordmark `F1 STRATEGY/SIM` with an orange
  slash; model stamp in mono; text tabs with a sliding orange underline.
- **Starting grid** (`ui/gridpicker.tsx`): the grid from above in two
  staggered columns, pole top left. Each box is a button; after qualifying
  it shows the car in it and a `Q` on your real slot.
- **Strategy strip** (`ui/stintstrip.tsx`): stints as tyre-coloured blocks
  across the race distance; pit markers are ARIA sliders.
- **Start lights** (`ui/startlights.tsx`): the progress indicator.
- **Rolling digits** (`ui/rolling.tsx`): each digit is a 0–9 strip that
  slides to its value.
- **Classification header**: an ink hero block (win %, driver and team, and
  a histogram of where they finish, P1 in orange, podium bright, DNF
  outlined) followed by a strip of four stats split by rules, not cards.
- **Classification table**: forecast order, timing-sheet mono numerals,
  thin ink bars (yours orange), purple for the best in a column, the
  finishing-position strip on the right.
- **Race replay** (`ui/replay.tsx`, `ui/lapchart.tsx`): play / pause, lap
  counter, scrubber with SC / VSC / red laps, 1× / 2× / 4×; the black
  timing tower and the lap chart share a row height so each position lines
  up across both.

## Accessibility checks

- Text contrast on the sheet: ink 17.6:1, ink-2 10.7:1, ink-3 5.3:1, purple
  6.2:1; orange is never used for small text on paper.
- Chart palette validated against `#FBFAF6`; tyres carry outline and letter;
  the position strip is a single ink ramp.
- Keyboard: grid boxes and stints are buttons, pit markers are sliders
  (arrow keys), every other control is a native button, select or range;
  orange focus ring; `⌘↵` / `Ctrl+↵` runs a simulation.
- Rolling numbers expose their value through `aria-label`; start lights are
  a live status region.
- `prefers-reduced-motion` disables all animation and auto-play.
