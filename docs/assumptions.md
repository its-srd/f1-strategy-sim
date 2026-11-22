# Modelling assumptions

Every structural assumption the model makes is listed here with the sample
size behind it. The website shows this file. Fitted values live in
`data/params/`. This file records *why*, not *what*. Counts marked (n=…)
are filled in from `data/processed/races.csv` after each export.

## Data scope and sources

| # | Assumption | Basis / sample size |
|---|---|---|
| D1 | Lap data is the TracingInsights copy of FastF1 output, not fetched from F1 directly. | F1 archive requires authentication since Oct 2026. Each race is cross-checked against Jolpica (winner and lap counts), see D6. |
| D2 | Only Grand Prix race sessions are used. Sprints, qualifying and practice are excluded for now. | Sprint stints differ in fuel load and tyre allocation. They may be added later as extra degradation data, labelled. |
| D3 | A track is identified by Jolpica `circuitId`, not by event name. | Event names move between venues (2026 "Bahrain Grand Prix" was run at Sepang). |
| D4 | A race counts as available 6 h after its scheduled start, once Jolpica has results and the lap file is published. | Publication delay. |
| D5 | 2021 Belgian GP is excluded from every fit. | Only safety car laps were run; compound recorded as UNKNOWN. |

## Lap-level definitions

| # | Definition | Basis |
|---|---|---|
| L1 | TrackStatus codes: 1 green, 2 yellow, 4 SC, 5 red, 6 VSC deployed, 7 VSC ending. A lap is flagged if the code appears at any point during it. | FastF1 documentation. |
| L2 | Per-lap weather is the first weather sample (about 1/min) inside the lap window. | FastF1 `Laps.get_weather_data`. |
| L3 | "Ghost" laps (`IsGhostLap`): rows after a driver's last lap with a recorded position, with no lap time and no position. They are flagged, not deleted. | Seen in sample races, for example 2026 Sepang. |
| L4 | A retiree's final in-lap appears in timing data but not in the official lap count, so +1 is accepted for non-classified drivers only. | Sample races 2018 Australia and 2026 Australia. |
| L5 | `GridPosition` 0 means a pit lane start. | Jolpica convention. |
| L6 | 2018 used Pirelli's absolute names (HYPERSOFT…SUPERHARD). From 2019, SOFT/MEDIUM/HARD are relative to each race's three-compound nomination. **Decision (2026-11-22):** 2018 laps are relabelled by rank within each race: the softest dry compound used becomes SOFT, the middle MEDIUM, the hardest HARD. The original label is kept in `CompoundOriginal`. A race is mapped only if exactly three dry compounds appear. Otherwise its laps get no compound and `CompoundMappingOk` = False, and nothing is guessed. Applies to seasons up to 2018 only. Known limitation: at 5 races Pirelli skipped a compound (`NonAdjacentNomination`), so the gap between labels is larger there. Per-track degradation absorbs most of this. | All 21 races in 2018 show exactly 3 dry compounds, all mapped (n = 21,497 dry laps). Non-adjacent: Shanghai, Hockenheim, Hungaroring, Marina Bay, Sochi. |

## Race-level definitions (`races.csv`)

| # | Definition |
|---|---|
| R1 | SC / VSC / red-flag deployments are counted from the session track-status timeline as transitions into code 4 / 6 / 5. |
| R2 | `MixedOrWetRace` = any driver used INTERMEDIATE or WET, or any lap reported rainfall. |
| R3 | Red flag: the race is neutralised and every car on slicks gets a free tyre change. A car with a stop left uses it; others fit a fresh set of the same compound. No pit stop is charged on the red-flag lap. The SC restart after a red flag ("5 → 1 → 4" in the timeline) is not counted as a separate SC deployment in the fitted rates, because the engine adds that restart lap itself. |

## Phase 1 export: what the data contains (export of 2026-11-22)

193 races (2018 R1 to 2026 R20 São Paulo), 213,132 driver-lap rows, 3,898 result rows, 33 circuits.
2026 Las Vegas (R21) was not yet published at export time. Rerun the export to add it.

| Item | Value |
|---|---|
| Laps with `IsAccurate` = True | 85.7% |
| Ghost laps flagged (L3) | 346 |
| Laps with null / UNKNOWN compound | 1,336 / 60 (60 = all of 2021 Spa) |
| Laps deleted by race control | 2,113 |
| Races where a wet compound was used | 23 |
| Races with any rainfall reported | 27 |
| `MixedOrWetRace` (either) | 35 |

### Races where timing data and official results legitimately differ

These are real race events, not data errors. Each one needs a modelling decision:

| Race | What happened | Proposed handling |
|---|---|---|
| 2018 Canada | Chequered flag shown early. Result taken at lap 68 of 70. | Use all laps for pace fitting. Results as official. |
| 2019 Japan | Chequered flag shown early. Result taken at lap 52 of 53. | Same as above. |
| 2019 Canada | Vettel first on the road, 5 s penalty, Hamilton won. | Results as official. Penalties are not simulated. |
| 2024 Belgium | Russell first on the road, disqualified (underweight). | Results as official. |
| 2021 Belgium | Only safety car laps. Official result after 1 lap. Compound UNKNOWN. | **Exclude** from every fit. |
| 2026 Britain | Sainz: 52 timed laps, crossed the line after the winner. Jolpica says "Lapped", 51 laps. | Unexplained. Likely a Jolpica lap count issue. One driver, no effect on fits. |

## Model structure (phase 2)

### Clean-lap filter (dry pace)

| # | Rule | Why |
|---|---|---|
| F1 | Exclude lap 1, pit in-laps and out-laps. | Standing start and pit lane are modelled separately. |
| F2 | Keep laps that were green for the whole lap (TrackStatus exactly "1"), and drop the first lap after any SC/VSC/red. | Neutralised and restart laps are not race pace. |
| F3 | Keep FastF1 `IsAccurate` laps only; drop laps deleted by race control. | Timing sync issues; deleted laps gained time illegally. |
| F4 | Drop every race where wet tyres were used, and any lap with rainfall reported. | Dry pace only. Wet is modelled separately (pooled). |
| F5 | Exclude 2021 Spa entirely (D5). | No green-flag racing. |
| F6 | Dry compounds only, with known tyre age. | |
| F7 | Dirty-air flag: gap to the car ahead at the line under 1.0 s at the start of the lap. | Structural threshold; the size of the penalty is fitted per race. |
| F8 | Outlier laps: one pass removing residuals beyond 4 robust SD of the race fit. | Mistakes, traffic incidents and damage are not representative pace. |
| F9 | Drivers need at least 5 clean laps in a race to get a pace value. | |
| F10 | A compound enters a race fit only with at least 3 driver-stints and 30 laps. | One stint cannot separate tyre pace from driver pace. Found in testing: 3 SOFT laps at 2024 Austin produced a −7.6 s offset. |

### Lap-time equation (per race, stage A)

`lap time = base + driver/car offset + compound offset + compound wear x tyre age + curvature x age^2 + fuel x lap + fuel2 x lap^2 + dirty air + noise`

| # | Assumption |
|---|---|
| M1 | Fuel burn and track rubbering both fall linearly with lap number and **cannot be separated** within a race. One combined "fuel" term carries both. |
| M1b | Fuel + evolution is linear **plus a lap² term** per race. Tested 2026-11-22: with the lap² term the per-race residual SD fell 0.392 → 0.382 s and compound wear came out in physical order on average (soft 0.064 > medium 0.055 > hard 0.043 % of lap per lap; medium > hard in 63% of races, up from 52%). With linear fuel only, early-stint (often SOFT) wear was biased low. |
| M2 | Wear is linear in tyre age per compound, plus one shared quadratic term per race. A tyre "cliff" beyond the observed stint lengths is not modelled. The simulator caps stints at the longest stint observed on that compound at that track. |
| M3 | Wear is the *managed* race wear that teams actually ran, not maximum-attack wear. Race-pace data cannot tell the difference. |
| M4 | Noise is independent lap to lap (SD fitted per race, pooled per track). Standard errors are cluster-robust by driver-stint. |
| M5 | Values are pooled per track in percent of base lap time, then converted to seconds with the track's current base lap. |
| M6 | Recency: each per-track parameter follows a random walk across seasons. Its drift variance is chosen by one-step-ahead predictive likelihood across tracks, so the data sets the recency weighting. Tracks start from the pooled prior, so a track with one race is pulled toward the pool. |
| D6 | A race at a circuit whose base lap is under 85% of that circuit's median is a separate layout (2020 Sakhir outer loop = `bahrain_short`). |
| T1 | Track temperature: tested within track across years for wear and fuel slope. No effect is distinguishable from zero (see results), so none is applied. |
| B1 | Base lap time is the latest dry race at the track. If the track has not been raced in 2026, it is scaled by the fitted season-to-season pace ratio across tracks raced in both years. |

### Driver skill vs car (stage B)

| # | Assumption |
|---|---|
| S1 | Driver-race pace (percent) = car[team, race] + skill[driver, season] + noise. Car pace is free per team per race, so skill is identified only from teammate comparisons, chained through drivers who changed teams. |
| S2 | Skill drifts as a random walk between seasons. Drift, extra noise and initial spread are fitted by marginal likelihood. Skill is clean-air race pace, which includes tyre management and team orders. It is not one-lap speed. |
| S3 | Outlier driver-races (\|z\| > 3) are down-weighted (Huber). |
| S4 | A driver in another team's car = that team's 2026 car value at the track + the driver's 2026 skill, with both uncertainties sampled. Car x driver interaction is assumed zero. |
| S5 | 2026 car pace at a track not yet raced in 2026 = the team's 2026 season mean, with SD including its race-to-race spread. Pre-2026 team-track history is not used (V1: regulation change). |

### Race events

| # | Assumption |
|---|---|
| P1 | Green pit loss = in-lap + out-lap − 2 x the driver's median clean lap within ±5 laps. Under SC/VSC it is measured against cars staying out on the same laps. Per-stop variation is sampled from the empirical residual distribution. |
| R1 | SC / VSC / red rates: Poisson per race with a Gamma prior fitted across all dry races (empirical Bayes). Timing within the race and duration are pooled empirical distributions. A 2026 rate ratio is applied only if its 95% CI excludes 1. |
| R2 | Wet races scale rates by the pooled wet/dry ratio. |
| R3 | Red flag: neutralises the race and allows a free tyre change (2018-present rules). |
| R4 | Retirement probability per car = target-season team rate (beta-binomial EB) x track ratio (EB), spread over race distance by the empirical lap distribution. Mechanical and incident causes are not separated (241 Jolpica statuses are just "Retired"). |
| R5 | Lap-1 position change: empirical distribution by grid slot, with spread scaled per track (EB). |
| R6 | Sporting rules that change legal strategies are coded explicitly (`web/src/engine/setup.ts` `SPORTING_RULES`), not inferred from data: two-stop tracks like Bahrain and Catalunya look the same in the data as a rule would. Currently: Monaco minimum two stops (introduced 2025), on by default with a toggle, because its 2026 status cannot be confirmed from the data. |
| O1 | Overtaking: a pass on a lap is a logistic function of pace advantage, gap (pairs within 3.0 s) and their interaction, with a track intercept (CV-penalised) and era offsets. No pass = the car behind is held up, and pays the dirty-air penalty if within 1 s. |
| W1 | Wet: a single wetness state (inter lap ratio) per lap, pooled across tracks. Driver wet effects are EB-shrunk toward 0. |
| W2 | Comparing compounds on a wet lap needs at least 2 cars on each compound. |
| W3 | Slick pace vs wetness: a line through two fitted points: slicks match dry pace when inters run at their dried-track level, and slicks equal inters at the switch crossover. The fitted slope from laps with both compounds running has the wrong sign and a CI including 0, so it is not used. |
| W4 | Rain onset is not predictable from the rainfall flag (fitted effect not distinguishable from zero), so wetness comes from observed wet races. **Rain chance:** a spell, if it comes, replays a real wet spell lap for lap (its rise, peak and drying), cut off at the flag. **Rain window (W4b):** it rains for exactly those laps. The track gets wet over the observed median ramp (laps from dry to peak in real spells), holds a level drawn from the peaks of real wet spells (rain intensity is not observed) with a smooth AR(1) wobble at the fitted persistence and SD, then dries at the fitted rate after the window. |
| W5 | When the track dries, every car (yours included) switches to the dry compound with the lowest expected time for the remaining laps, adding one stop only if no compound's observed stint cap covers the distance. The two-compound rule does not apply once wet tyres have been used (sporting regulations). |
| W6 | Rain radar: every team sees the next 3 laps of wetness (structural choice). Nobody fits fresh slicks (planned stop, SC stop, back from wet tyres, or a red-flag free change) if wet tyres will be needed within those laps. A tyre switch happens only if the new tyre stays the best choice for the 3-lap window, so there are no pit stops for a 1–2 lap flicker. The default call switches on the lap the other tyre becomes faster: the crossover was measured from when real teams switched, so no extra confirmation lag is added. Retirement rates take the wet multiplier only in races where it actually rains. |
| W7 | Your wet-weather call: switch up to 3 laps early (within the radar) or up to 3 laps late, relative to the default call, and optionally never use full wets. It applies to both directions (onto wet tyres and back to slicks). The site compares your call with the default call on the same simulated races (paired) and shows the difference with ±2 SE. **Not backtested**, and the wet model is pooled from 23 races: the model's slick penalty rises steeply past the crossover, so it rewards early calls strongly (e.g. about +3 expected points for 2 laps early at Silverstone from P3). That size has not been checked against real races. | Pooled wet model; no wet-race backtest yet. |


### Simulation engine (phase 3)

| # | Assumption | Basis |
|---|---|---|
| E1 | Every simulated race draws its own car pace, driver skill, wear, offsets, fuel, dirty-air effect and pit loss from their fitted uncertainty, so the probabilities include parameter uncertainty, not just race luck. Car and skill for a driver in their own 2026 seat are drawn **jointly** with their posterior correlation (about −0.4 to −0.6: they are identified only through teammates); a driver moved to another car is drawn independently. Each car also gets a race-day form draw N(0, tau²), with tau the fitted race-to-race noise of the skill model. | S1–S4 |
| E2 | Rival grid: cars are ordered by sampled race pace (car + skill + form). Qualifying is not modelled. Your car starts at the slot you choose. | No qualifying model fitted. |
| E3 | A grid driver with no dry race in the data gets the prior: average skill, SD = the fitted spread of a first season. Labelled on the page. | e.g. one-off wet start |
| I1 | Within a season, car pace is a level that drifts race to race (random walk) plus track-to-track scatter. Drift and scatter are fitted by how well each race predicts the next across all 91 team-seasons. The website and backtest use the latest level, not the season average. | Predictive score +35 log-likelihood units over equal weights. |
| I2 | When the grid is read as a qualifying result (backtest), each place behind the slot the car's pace predicts costs a fitted 0.038% of lap time (±0.002), and race-day form spread shrinks accordingly. Off on the website, where you set the grid yourself. | 3,047 driver-races. |
| I3 | With real qualifying known, car/skill/form spread is scaled by 0.35. Without it (the website), the full fitted spread is kept. Both chosen on the 2025 practice races (`data/params/calibration.json`). | Outcomes fell inside the 80% range 95% of the time before; 90% in the 2026 exam after. |
| I4 | When dry qualifying gaps are known, race pace = 0.61 × season form + 0.32 × qualifying gap (centred on the field), plus form noise with SD 0.35%. Qualifying gaps beyond 6.5% (crashes, no time set) and wet sessions are ignored. | 2,795 driver-races in 148 races; both weights many times their SE. |
| U1 | Website modes. **Before qualifying:** you set your grid slot, rivals start in order of expected pace, and the model knows season form only (full pace spread). **After qualifying:** the grid is loaded and cross-checked automatically: the official race result's grid once the race has run, otherwise OpenF1's official starting grid (penalties applied), otherwise the qualifying order (flagged "penalties not confirmed"). Every driver moved back from their qualifying position, or starting from the pit lane, is listed on screen. Lap times are each driver's best Q1/Q2/Q3 lap (Jolpica-F1), the same definition the model was fitted on. The engine uses I2/I4 with the backtested spread (0.35). Moving your driver's slot is a what-if that changes **track position only**. For a race already run, the real result is shown next to the prediction, labelled as a genuine forecast or as hindsight, depending on whether the model has learned from that race (`meta.data_through`). | Backtest: after qualifying was far stronger (practice win −7% vs −27%). Las Vegas 2026 showed why the official grid matters: before retraining, the model gave Verstappen 42% from the official grid (he won), but only 22% from the qualifying order, where Antonelli's 5-place penalty was missing. |
| A1 | Rival strategies are sampled from the planned green-flag strategies teams actually ran at the track since 2022 (18-inch tyres). Excluded: sequences with a stop under SC/VSC/red flag (reactions the engine models itself) and sequences with a stint of 2 laps or less (damage, punctures). Optimiser candidates use stints of at least 3 laps for the same reason. | Counts per track in `tracks.json` → `strategies.dropped`. |
| A1b | Rival strategies are drawn from drivers who started within 2 places of the car's grid slot (widened until at least 5 examples). | Backtest: real teams choose strategies by grid position. |
| A1c | Each rival draws 5 such strategies and runs the one with the lowest expected time under this year's tyre model. 5 was chosen on the 2025 practice races. | Backtest: 1 → 5 improved every score; 8 and 12 did not. |
| A2 | SC/VSC reaction: a car pits early under SC/VSC if its next planned stop is within max(3 laps, 35% of the planned stint). **This rule is a structural choice, not fitted.** You can switch it off for your car. | Stop timing under neutralisation was not modelled from data. |
| G1 | After lap 1 the field is spaced by the empirical gap distribution at the line after lap 1. The leader loses the measured median lap-1 time against lap 2. | 3,169 lap-1 gaps; 168 leaders. |
| G2 | A car that fails to pass is placed behind at a gap drawn from the empirical gaps of faster cars that did not pass (within 1.5 s). Under SC/red the field runs as a queue behind the leader, re-compressed every lap at the empirical restart gaps. Cars that stay out keep their order; a car that pits under SC/VSC re-joins by its actual time and can lose places. Quantile tables are sampled across their levels, with linearly extended tails. | 21,000 held pairs. |
| O2 | At most one pass attempt per car per lap, against the car directly ahead. Position changes in pit cycles are resolved by time, not by the pass model. Lapping and blue flags are not modelled. | |
| PM1 | Pace mode: push / conserve shift pace by ±1 SD of teammates' managed stint-pace variation (skill gap removed) and change wear by the measured trade-off. The trade-off is estimated with independent stint halves (pace from the first half, wear from the second), because estimating both from the same laps biases it negative (naive −0.049 vs split −0.018). | 1,496 teammate stint pairs; CI in `global.json`. |
| C1 | Points: 2025+ system (25-18-15-12-10-8-6-4-2-1, no fastest-lap point). | |
| C2 | Retirements are independent of the safety-car process (both are fitted separately), so any link between them is not reproduced. | |

### Independent code review (2026-11-22)

A separate review of the engine and fitting code found nine defects, all fixed:
- Pit stops under SC/VSC lost no places: the queue was built in the pre-stop order.
- Driver-offset SEs were 2-3x too large: they used the raw dummy coefficient, not the contrast against the race mean. Re-fitting raised the fitted race-to-race noise tau from 0.207% to 0.269%.
- Car and skill were drawn independently, and race-day form was missing.
- Wet retirement multiplier was applied in dry races.
- Quantile tails were never sampled (about 0.5 s of pit loss missing).
- Rain at the end of a race was squeezed into the remaining laps instead of cut off.
- Red-flag restarts were counted as SC deployments.
- Two red-flag tyre-change edge cases.
- Rivals fitted fresh slicks just before rain.

## Backtest summary (full report: docs/backtest.md, "Track record" tab)

Predicting races it had never seen, from the real grid and qualifying, with only earlier data. The baseline knows only each grid slot's history.

| Set | Win | Podium | Points | Winner score (grid) | Full order (grid) | Favourite won |
|---|---|---|---|---|---|---|
| Practice: 18 races of 2025, used to choose improvements | −7% | −2% | +2% | 1.12 (1.125) | 0.647 (0.661) | 50% |
| Final exam: 13 races of 2026, scored once | −3% | +3% | +6% | 1.21 (1.62) | 0.703 (0.663) | 69% |

Percentages: Brier skill against the grid baseline (positive = better). The strategy "what if" comparison was **not validated**: knowing the real strategies brought predicted teammate gaps closer to reality in 2025, but not significantly, and made them worse in 2026.

## Validation tests (results in the generated section below)

| # | Test | Why |
|---|---|---|
| V1 | Fit with and without a break at 2026; compare how well each predicts the next season (one-step-ahead) for every per-track parameter, and the marginal likelihood for skill. | 2026 regulation change (new power units, active aero). Not assumed to transfer. |
| V2 | The same with a break at 2022. | 2022 switch from 13-inch to 18-inch tyres. Earlier data is kept or dropped per parameter based on this result. |

<!-- AUTO:START -->

_Generated 2026-11-22T15:12 UTC by `model/report.py` from `data/params/`. Do not edit by hand._

## Fitted results

### Data used

194 races (2018 Australian Grand Prix to 2026 Las Vegas Grand Prix), 214,121 driver-laps. Dry-pace fits use 149,627 clean laps from 170 dry races. 2,674 outlier laps and 848 laps on thinly-run compounds were removed (F8, F10).

| Clean-lap rule (applied in order) | Laps removed |
|---|---|
| excluded race (2021 Spa) | 60 |
| ghost lap | 349 |
| no lap time | 133 |
| lap 1 | 3,757 |
| pit in or out lap | 13,175 |
| not green for the whole lap | 20,114 |
| first lap after SC/VSC/red | 3,460 |
| FastF1 IsAccurate false | 193 |
| deleted by race control | 1,732 |
| race where wet tyres were used | 18,104 |
| rainfall reported on lap | 2,555 |
| not a dry compound / no tyre age | 862 |
| no driver identity | 0 |

### Driver skill vs car pace

Mixed model on 3,272 driver-race pace values. Fitted: extra race-to-race noise tau = 0.269%, year-to-year skill drift omega = 0.092% per season (the recency weighting), spread of skill at a driver's first season sigma0 = 0.213%. 9 outlier driver-races were down-weighted.

Current grid, skill projected to 2026 (negative = faster than the average driver; ±1 SD):

| Driver | Skill % | SD % | Dry races fitted | Wet adj. % (pooled) |
|---|---|---|---|---|
| Max Verstappen | -0.861 | 0.120 | 160 | +0.44 ± 0.19 (14 wet races) |
| Sergio Pérez | -0.392 | 0.143 | 142 | +0.20 ± 0.21 (10 wet races) |
| Lando Norris | -0.352 | 0.170 | 148 | +0.00 ± 0.20 (14 wet races) |
| Pierre Gasly | -0.314 | 0.132 | 159 | +0.36 ± 0.16 (11 wet races) |
| Charles Leclerc | -0.278 | 0.138 | 160 | -0.21 ± 0.23 (12 wet races) |
| Carlos Sainz | -0.230 | 0.136 | 160 | -0.11 ± 0.23 (11 wet races) |
| Isack Hadjar | -0.191 | 0.126 | 35 | +0.46 ± 0.19 (2 wet races) |
| Lewis Hamilton | -0.186 | 0.138 | 165 | -0.18 ± 0.23 (13 wet races) |
| Andrea Kimi Antonelli | -0.181 | 0.150 | 38 | +0.29 ± 0.27 (3 wet races) |
| Fernando Alonso | -0.178 | 0.162 | 129 | -0.59 ± 0.18 (11 wet races) |
| Alexander Albon | -0.177 | 0.136 | 125 | -0.25 ± 0.24 (8 wet races) |
| Nico Hülkenberg | -0.176 | 0.152 | 115 | -0.27 ± 0.19 (8 wet races) |
| Oliver Bearman | -0.116 | 0.131 | 39 | +0.06 ± 0.17 (5 wet races) |
| Oscar Piastri | -0.053 | 0.171 | 76 | -0.08 ± 0.21 (9 wet races) |
| George Russell | -0.032 | 0.148 | 148 | -0.48 ± 0.24 (11 wet races) |
| Gabriel Bortoleto | -0.014 | 0.154 | 35 | -1.20 ± 0.20 (3 wet races) |
| Arvid Lindblad | -0.010 | 0.128 | 18 | +0.92 ± 0.30 (1 wet races) |
| Franco Colapinto | +0.003 | 0.134 | 41 | +0.39 ± 0.20 (2 wet races) |
| Liam Lawson | +0.068 | 0.122 | 46 | +0.35 ± 0.17 (5 wet races) |
| Lance Stroll | +0.077 | 0.162 | 159 | -0.61 ± 0.19 (12 wet races) |
| Rafael Camara | +0.081 | 0.189 | 1 | +0.93 ± 0.33 (1 wet races) |
| Valtteri Bottas | +0.272 | 0.148 | 146 | +0.59 ± 0.37 (10 wet races) |

2026 car pace (team-season mean, percent of lap time; negative = faster):

| Team | Car % | SD % | 2026 races | Retirement rate 2026 (EB) |
|---|---|---|---|---|
| Mercedes | -1.065 | 0.260 | 18 | 0.117 (4/42) |
| Ferrari | -0.936 | 0.260 | 18 | 0.117 (4/42) |
| McLaren | -0.823 | 0.262 | 17 | 0.124 (4/39) |
| Red Bull | -0.371 | 0.259 | 18 | 0.153 (6/42) |
| RB F1 Team | -0.037 | 0.258 | 18 | 0.101 (3/41) |
| Alpine F1 Team | +0.052 | 0.259 | 18 | 0.135 (5/42) |
| Audi | +0.216 | 0.261 | 18 | 0.121 (4/40) |
| Haas F1 Team | +0.568 | 0.259 | 18 | 0.171 (7/42) |
| Williams | +0.946 | 0.263 | 18 | 0.215 (9/40) |
| Aston Martin | +1.531 | 0.268 | 17 | 0.424 (21/42) |
| Cadillac F1 Team | +1.764 | 0.260 | 17 | 0.340 (16/41) |

### Validation V1 (2026 rules) and V2 (2022 18-inch tyres)

Score = one-step-ahead predictive log-likelihood (per-track parameters) or marginal likelihood (skill). A break is used only when it beats carry-over by more than 2 units.

| Quantity | V2: break - carry (2022) | Decision | V1: break - carry (2026) | Decision | n obs after 2026 |
|---|---|---|---|---|---|
| fuel | +2.3 | break | +9.0 | break | 18 |
| fuel2 | +13.2 | break | +10.5 | break | 18 |
| traffic | +10.4 | break | -12.0 | carry_over | 18 |
| curve | +1.7 | carry_over | +3.0 | break | 18 |
| slope_SOFT | +5.2 | break | -0.8 | carry_over | 15 |
| slope_MEDIUM | +5.8 | break | -3.5 | carry_over | 18 |
| slope_HARD | -7.4 | carry_over | +0.1 | carry_over | 14 |
| offset_SOFT | +15.2 | break | +7.5 | break | 15 |
| offset_HARD | -3.9 | carry_over | +4.6 | break | 14 |
| sigma | -0.4 | carry_over | -3.2 | carry_over | 18 |
| driver skill | -7.1 | carry_over | -5.9 | carry_over | – |

Team order correlation with the previous season (team-season mean car pace): 2019: 0.92, 2020: 0.79, 2021: 0.92, 2022: 0.73, 2023: 0.76, 2024: 0.64, 2025: 0.94, 2026: 0.71. Car pace is never carried across seasons. It is fitted per team per race.

### Pooled lap-time parameters

| Parameter | Pooled mean (% of lap) | Between-track SD | Drift per season | Tracks | Breaks used |
|---|---|---|---|---|---|
| fuel | -0.0568 | 0.0328 | 0.0316 | 31 | 2022, 2026 |
| fuel2 | -0.0000 | 0.0005 | 0.0010 | 31 | 2022, 2026 |
| traffic | 0.2907 | 0.1861 | 0.1389 | 31 | 2022 |
| curve | 0.0001 | 0.0007 | 0.0010 | 31 | 2026 |
| slope_SOFT | 0.0552 | 0.0628 | 0.0720 | 31 | 2022 |
| slope_MEDIUM | 0.0619 | 0.0561 | 0.0518 | 31 | 2022 |
| slope_HARD | 0.0411 | 0.0450 | 0.0439 | 31 | – |
| offset_SOFT | -0.1528 | 0.2663 | 0.5179 | 31 | 2022, 2026 |
| offset_HARD | 0.1961 | 0.2122 | 0.3162 | 31 | 2026 |
| sigma | 0.4022 | 0.0884 | 0.1179 | 31 | – |

Track temperature (within-track, across years): slope_SOFT: +0.00031 ± 0.00079 %/°C (n=105); slope_MEDIUM: +0.00039 ± 0.00051 %/°C (n=162); slope_HARD: +0.00056 ± 0.00056 %/°C (n=145); fuel: +0.00043 ± 0.00030 %/°C (n=165). **No effect is distinguishable from zero**, so the simulator applies none (T1).

### 2026 calendar tracks

Wear in seconds per lap of tyre age (net of fuel). Source `track` = fitted at that track and shrunk toward the pool; `pooled` = no data at that track.

| Track | Dry races | Base lap s | Wear S / M / H (s/lap) | Pit loss s | SC / VSC per race | Overtake difficulty | Notes |
|---|---|---|---|---|---|---|---|
| Australian Grand Prix | 6 | 86.19 | +0.063 / +0.021 / +0.051 | 21.8 | 0.74 / 0.69 | -0.28 |  |
| Chinese Grand Prix | 5 | 98.99 | +0.159 / +0.123 / +0.039 | 23.0 | 0.74 / 0.57 | 0.65 |  |
| Japanese Grand Prix | 6 | 96.73 | +0.058 / +0.036 / +0.027 | 23.4 | 0.74 / 0.56 | -0.05 |  |
| Miami Grand Prix | 5 | 94.76 | +0.001 / +0.044 / +0.031 | 19.6 | 0.74 / 0.58 | 0.51 |  |
| Canadian Grand Prix | 5 | 78.23 | +0.044 / +0.079 / +0.015 | 19.7 | 0.74 / 0.59 | -0.50 |  base scaled from 2025 |
| Monaco Grand Prix | 6 | 78.82 | -0.060 / -0.040 / -0.023 | 21.8 | 0.74 / 0.56 | -3.53 | negative net wear: SOFT, MEDIUM, HARD |
| Barcelona Grand Prix | 9 | 83.78 | +0.231 / +0.198 / +0.157 | 23.8 | 0.74 / 0.54 | 0.44 |  |
| Austrian Grand Prix | 11 | 73.61 | +0.047 / +0.058 / +0.039 | 21.3 | 0.74 / 0.58 | 0.62 |  |
| British Grand Prix | 8 | 96.07 | +0.046 / +0.079 / +0.107 | 21.3 | 0.74 / 0.55 | 0.25 |  |
| Belgian Grand Prix | 7 | 111.95 | +0.101 / +0.125 / +0.091 | 19.7 | 0.74 / 0.56 | 0.34 |  |
| Hungarian Grand Prix | 7 | 86.86 | +0.069 / +0.076 / +0.083 | 22.1 | 0.74 / 0.58 | -0.46 |  |
| Dutch Grand Prix | 5 | 77.93 | +0.050 / +0.080 / +0.051 | 19.6 | 0.74 / 0.58 | -0.93 |  |
| Italian Grand Prix | 9 | 87.89 | +0.046 / +0.009 / +0.001 | 25.3 | 0.74 / 0.62 | 0.24 |  |
| Spanish Grand Prix | 1 | 102.68 | +0.028 / +0.061 / -0.010 | 26.6 | 0.74 / 0.60 | -1.26 | negative net wear: HARD |
| Azerbaijan Grand Prix | 8 | 110.56 | -0.037 / -0.022 / +0.027 | 21.4 | 0.74 / 0.58 | -0.29 | negative net wear: SOFT, MEDIUM |
| Bahrain Grand Prix in Malaysia | 0 | – | – | – | – | – | No dry race at this circuit (2026 race was wet). Not simulated. |
| Singapore Grand Prix | 6 | 100.37 | -0.000 / -0.005 / +0.044 | 24.1 | 0.74 / 0.58 | -0.68 | negative net wear: SOFT, MEDIUM |
| United States Grand Prix | 8 | 102.63 | +0.084 / +0.089 / +0.077 | 21.7 | 0.74 / 0.60 | 0.90 |  |
| Mexico City Grand Prix | 8 | 82.37 | +0.032 / +0.036 / +0.024 | 23.5 | 0.74 / 0.66 | 0.24 |  |
| Brazilian Grand Prix | 6 | 75.84 | +0.108 / +0.080 / +0.116 | 22.1 | 0.74 / 0.60 | -0.25 |  base scaled from 2025 |
| Las Vegas Grand Prix | 4 | 100.68 | -0.044 / -0.058 / +0.021 | 22.3 | 0.74 / 0.61 | 0.55 | negative net wear: SOFT, MEDIUM |
| Qatar Grand Prix | 4 | 90.09 | +0.068 / +0.023 / +0.004 | 27.0 | 0.74 / 0.58 | -0.24 |  base scaled from 2025 |
| Abu Dhabi Grand Prix | 8 | 91.57 | +0.157 / +0.117 / +0.077 | 22.7 | 0.74 / 0.57 | 0.92 |  base scaled from 2025 |

\* pooled value. Overtake difficulty = track intercept in the pass model (lower = harder; 0 = pooled average).

### Safety car, VSC, red flag

| Type | Deployments | Rate per dry race | Variance/mean | Between-track difference detected | Wet ratio (95% CI) | 2026 vs earlier (95% CI) | 2026 ratio applied |
|---|---|---|---|---|---|---|---|
| SC | 150 | 0.742 | 0.88 | **no**: every track gets the pooled rate | 1.27 (0.86–1.87) | 0.98 (0.58–1.64) | no |
| VSC | 121 | 0.591 | 1.03 | yes | 1.34 (0.88–2.06) | 2.13 (1.37–3.31) | yes |
| RED | 28 | 0.126 | 1.67 | yes | 1.64 (0.69–3.87) | 1.42 (0.49–4.12) | no |

Lap time under SC = 1.497 x clean lap (n=4,299), under VSC = 1.344 x (n=337). Pit stop cost vs cars staying out: under SC 0.77 x green loss (n=644), under VSC 0.84 x (n=326). Green-flag stops measured: 3,629.

### Retirements and starts

Retirement rate by season: 2018: 0.195 (82/420), 2019: 0.136 (57/419), 2020: 0.165 (56/339), 2021: 0.138 (58/420), 2022: 0.166 (73/439), 2023: 0.136 (59/435), 2024: 0.103 (49/476), 2025: 0.107 (51/476), 2026: 0.183 (83/453). 14% of retirements happen on lap 1. Wet races 0.160 vs dry 0.144. Cause (mechanical vs incident) is not modelled: Jolpica reports 241 retirements as plain 'Retired' (R4).

Lap-1 position change: empirical distribution per grid slot from 3,137 dry starts; per-track spread scaled by an EB-shrunk ratio (between-track SD of log spread = 0.28).

### Overtaking

71,434 close-following pairs (within 3.0 s), 4,042 passes. Pace advantage coefficient 1.94 ± 0.07 per s/lap; gap -4.47 ± 0.11 per s; interaction 0.65 ± 0.08. Track penalty chosen by 5-fold CV: 1. Era offsets: 2018-21 -0.41 ± 0.20, 2022-25 -0.37 ± 0.20, 2026 -0.31 ± 0.20.

Calibration (mean predicted vs observed pass rate by decile of prediction): 0.000/0.001, 0.000/0.001, 0.000/0.001, 0.000/0.001, 0.001/0.004, 0.004/0.005, 0.013/0.009, 0.033/0.026, 0.091/0.082, 0.424/0.436.

### Wet weather (pooled across all tracks; labelled pooled on the site)

23 races used wet tyres; 18 have a dry race at the same track to normalise against.

* Slick/inter crossover from when teams switch tyres: inter lap ratio 1.151 (95% CI 1.106–1.170; 12 races). Fitted from laps with both tyre types running: 1.136 (CI 0.997–1.377; 31 laps). The slope is not identified (W3).
* Inter/full-wet crossover: inter ratio 1.258 (CI 1.134–1.330; 28 laps, 5 races).
* Drying: inter ratio relaxes with rho = 0.925 per lap (CI 0.858–0.962) toward 1.121 (inters on a dried track). Rainfall flag effect: +0.0045 (CI -0.0036–+0.0134): **not distinguishable from zero**, so rain onset is replayed from the 18 observed wet-race trajectories (W4).
* Driver wet skill: 121 teammate pairs in 14 races; between-driver SD beyond dry skill = 0.65%. Per-driver values are heavily shrunk (see table above).

<!-- AUTO:END -->
