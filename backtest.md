# Backtest: how well does the simulator predict real races?

Run 2026-11-22, updated the same day after a second independent review (summarised in `docs/assumptions.md`). Numbers come from `data/backtest/scores_tune.json`, `scores_dev.json`, `scores_holdout.json`, `strategy_scores.json`, `param_forecast_*.json` and `lap_tyre_check_*.json`.

## How the test works

Each test race is predicted the way it would be in real life, before the race:

1. **Learn only from the past.** Every fitted number (car pace, driver skill,
   tyre wear, safety-car rates, and so on) is refitted using only races
   before the test race.
2. **Start from the real grid.** Qualifying happens before the race, so its
   grid order and lap-time gaps are fair to use.
3. **Simulate 10,000 races**, then compare the predicted odds with what
   actually happened.
4. **Compare with a simple baseline that only knows the grid**: how often
   each grid slot has won, made the podium or scored points in the past.
   If the model can't beat "where did they start", it isn't adding anything.

The races are split in two:

| Set | Races | Used for |
|---|---|---|
| Tuning (added after the review) | 18 dry races of 2024 (rounds 4–24) | Fitting the pace blend on as-of priors, testing the overtaking model, choosing the spread |
| Practice | 18 dry races of 2025 (rounds 5–24) | Trying improvements; kept only if the score improved |
| Final exam | 2026 dry races from round 4 (13 at first, 14 once Las Vegas was raced) | Scored at the end of each round of improvements, to check the gains are real |

Wet races are left out because every test race is simulated as dry. Early
rounds are left out because a team needs a few races of a season before its
car can be measured. 2026 Madrid is left out because there was no earlier dry
race at that circuit.

**Known leaks (small):**
- The 2022/2026 "keep or reset" decisions (V1/V2) were made on all the data.
- The structure of the model (filters, equations) was designed while looking
  at all the data.

## How to read the scores

- **Skill vs grid** compares the predicted chances with what happened, using
  the Brier score (average squared error of the probabilities). +10% means
  10% less error than the grid baseline, 0 means equal, negative means worse.
- **Winner score** is how surprised the model was by the real winner
  (log-loss). Lower is better.
- **Full order** is how well the predicted finishing order matches the real
  one (rank correlation; 1 = perfect).
- **PIT inside 80%** checks that the predicted position distributions are
  calibrated: it should be 80%. Below 80% means overconfident, above means
  too cautious. (An earlier "80% range" check used whole-position ranges
  that really hold about 93% of the model's own probability, so its "95%"
  readings did not mean the model was too cautious. The review caught this.)
- **Two harder baselines** for the full order: the pace forecast alone (the
  number the engine is fed, no simulation) and the average of grid rank and
  pace rank. The simulation earns its keep only if it beats the second.

## Results

### Practice races (2025), as the model improved

| Step | Win | Podium | Points | Winner score | Full order | 80% range | Favourite won |
|---|---|---|---|---|---|---|---|
| Grid-only baseline | 0 | 0 | 0 | 1.125 | 0.661 | – | pole: 67% |
| Starting model | −31% | −16% | −3% | 1.46 | 0.634 | 95% | 28% |
| + recent races count more | −30% | −15% | −3% | 1.43 | 0.638 | 95% | 28% |
| + grid slot read as weekend pace | −21% | −9% | +2% | 1.31 | 0.656 | 95% | 33% |
| + qualifying lap-time gaps | −18% | −11% | +1% | 1.29 | 0.652 | 96% | 44% |
| + rival strategies depend on grid slot | −16% | −8% | +1% | 1.27 | 0.649 | 94% | 44% |
| + rivals pick the quickest of 5 nearby strategies, randomness × 0.35 | −7% | −2% | +2% | 1.12 | 0.647 | 93% | 50% |
| + second-review changes (below), randomness × 0.7 | **−3%** | **+2%** | 0% | **1.03** | 0.648 | PIT 80% | **61%** |

The "80% range" column up to the last row uses the old, faulty measure.
The second-review changes: car pace shared by teammates, tyre values that
fade back to the pooled average, stint caps from what teams usually run, the
pace blend fitted on as-of priors, grid penalties no longer read as slow
pace, three missing safety cars found, and the randomness scale re-chosen
with a proper calibration check.

### Final exam (2026)

| | Win | Podium | Points | Winner score | Full order | PIT inside 80% | Favourite won |
|---|---|---|---|---|---|---|---|
| First scoring (13 races) | −3% | +3% | +6% | 1.21 | 0.703 | – | 69% (9 of 13) |
| After the second review (14 races) | −7% | **+7%** | **+8%** | **1.21** | **0.705** | 76% | **71%** (10 of 14) |
| The same, on the original 13 races | −4% | +8% | +6% | 1.22 | – | – | – |
| Grid-only baseline (14 races) | 0 | 0 | 0 | 1.55 | 0.646 | – | pole: 71% |

**In plain English:**
- On races it had never seen, the model **beats the grid on podium and
  points chances, on how surprised it is by the winner, and on the full
  order.** The full-order gain is clear of luck; the others are positive but
  within what luck could produce over 14 races.
- **Win chances are level with the baseline**, slightly behind on the
  Brier score. Las Vegas hurt most: Verstappen won from pole with the model
  at 35%, while pole has historically won 53% of the time.
- The exam has now been scored three times with different engine
  versions; the scores barely moved, but it is no longer a pure one-shot
  exam. Every change was chosen on 2024 and 2025 only.
- In 2026 the model is slightly **over**confident (76% inside its central
  80%), the opposite of what the old measure said.

### Is the simulation better than its inputs?

The review's sharpest question. Rank correlation with the real finishing
order:

| Predictor | 2024 (tuning) | 2025 (practice) | 2026 (exam) |
|---|---|---|---|
| Grid only | 0.752 | 0.661 | 0.646 |
| Pace forecast only (no simulation) | 0.791 | 0.629 | 0.714 |
| Grid rank and pace rank, averaged | 0.802 | **0.666** | 0.695 |
| Full simulation | **0.810** | 0.648 | **0.705** |
| Among finishers only: average vs simulation | 0.861 vs **0.869** | **0.791** vs 0.778 | 0.828 vs **0.841** |

In two of three seasons the simulation beats the simple average (in 2026
clear of luck among finishers: +0.003 to +0.022); in 2025 the average beats
it (−0.025 to −0.004). Part of the review's gap came from the measure: the
model's expected position mixes in retirement risk, which the baselines
ignore, so finishers are compared separately.

**Track position.** How strongly the grid order survives to the flag
(classified finishers): real 0.80 / 0.76 / 0.77 in 2024 / 2025 / 2026,
simulated 0.80 / 0.79 / 0.85. The review suspected the engine turns pace into
places too readily; the data says the opposite in 2025–2026: the engine
keeps grid order a little more than real races. Making overtaking easier
(tested on 2024) changed nothing beyond noise, so the fitted pass model
stands. What makes real races shuffle more is still open.

### Strategy "what if" check (rebuilt after the review)

Same car, same race, different plans: teammates who ran different
strategies, now including same-compound pairs with stops at least 3 laps
apart. The engine predicts their gap with the real strategies and "blind"
(both on teammate A's plan). Gain = how much closer knowing the strategies
gets to the real gap. Ranges now resample whole races, since pairs from one
race share its safety cars. Three ways of simulating:

| Mode | 2025 (66 pairs, 17 races) | 2026 (29 pairs, 11 races) |
|---|---|---|
| Random safety cars (as on the website) | +0.5 s (−0.6 to +2.0) | −0.8 s (−3.2 to +1.7) |
| The race's real safety cars replayed | +0.3 s (−0.9 to +1.7) | +0.2 s (−2.5 to +2.9) |
| Real safety cars + that race's true tyre values ("oracle") | +0.2 s (−0.8 to +1.3) | +0.9 s (−1.4 to +3.3) |

**In plain English:** knowing the strategies does not measurably improve
the prediction, in either year, **even with perfect tyre knowledge**. The
earlier "worse in 2026" (−2.7 s, range −6.0 to −0.3) does not survive fair
resampling and real safety cars. The honest reading is "no evidence either
way": teammate gaps vary by 17–25 s for reasons the model cannot see
(form, traffic, team orders), while the strategy effects are about 5 s, so
a few dozen pairs cannot settle it. The strategy comparison stays labelled
experimental.

**A test with far more data: lap by lap.** Whenever two teammates both set
a clean lap on the same lap but on different tyres (compound or age), the
as-of tyre model predicts their gap from the tyres alone. Each pair's
average gap is removed, so this measures how well the model tracks the gap
as tyres differ:

| | 2025 (2,782 laps) | 2026 (1,768 laps) |
|---|---|---|
| Error predicting no tyre effect | 0.80 s | 0.90 s |
| Error of the tyre model, before the review | 0.71 s | 0.78 s |
| Error of the tyre model, after | **0.68 s** | **0.77 s** |
| Real gap per second of predicted gap (1 = right) | 0.73 | 0.87 |

So the tyre model does carry real information (it explains about 28% of
the lap-to-lap variation of the gap), and the review's changes improved it,
but it overstates tyre differences by about 15–25%.

**Tyre parameter forecasts** (as-of forecast vs the value the race then
showed, % of lap time; "pool" = the cross-track average):

| | 2025 before | 2025 after | 2026 before | 2026 after (same 13 races) |
|---|---|---|---|---|
| Compound offsets: track / pool | 0.446 / 0.357 | **0.358** / 0.361 | 0.373 / 0.278 | **0.291** / 0.292 |
| Wear slopes: track / pool | 0.045 / 0.040 | **0.040** / 0.042 | **0.067** / 0.080 | 0.077 / 0.083 |
| Race-average wear: track | 0.037 | **0.034** | **0.062** | 0.074 |

The track's own history now forecasts offsets as well as the pool (before
it was worse). Wear improved in 2025 and got worse in 2026, where race-to-race
wear varies far more than in any earlier season. A race's overall wear level
remains the weak point (±0.03–0.08% of lap time, about ±10–20 s over a
one-stop vs two-stop choice). The review points to the only data that could
fix it: the same weekend's practice long runs, which the model does not use
yet.

### Wet races (2022–2026)

The tests above use dry races only. This one asks whether the rain model
helps or hurts. It uses the 13 wet races since 2022 that can be tested: not a
season opener, and with an earlier dry race at the same circuit. As before,
every race is predicted by a model fitted only on races before it, from the
real grid with qualifying gaps (4,000 simulations per race and mode).

Each race is simulated three ways:

- **Ignore rain:** the model is told nothing about the weather.
- **Rain window:** what a user would enter. The window is the main spell of
  rain falling, read from the weather station. It starts on lap 1 if the
  race started on wet tyres, and is just lap 1 when the track was wet only
  from rain before the start. The model then dries the track by itself.
- **Real conditions:** hindsight. The real lap-by-lap conditions (the best
  tyre's lap time compared with dry pace) are replayed.

**First run: the rain model made predictions worse.** With the rain window the
rank correlation fell to 0.557 (the grid alone gets 0.589), winner score
1.92 (grid 1.74), and the model's favourite won 2 of 13 races. Replaying the
real conditions was worse still (0.535, 2.10).

**Cause: the driver wet-skill effects.** Each driver's wet effect is measured
against their team-mate only, so a pair that stayed together gets equal and
opposite values. Verstappen came out 0.8% slower in the wet than his dry pace
says, and Pérez 0.8% faster. That is about the gap between two teams, and it
is contradicted by these very races (Verstappen won 6 of the 13). Switched off,
the rain model recovers. Keeping a random wet effect per driver, without the
measured values, was also worse than none. So the engine no longer uses
driver wet effects (`wet_driver_effects: false` in
`data/params/calibration.json`, rule W1b).

**Results after the fixes** (rerun with the final engine after the second
review):

| Mode | Win (vs grid) | Points (vs grid) | Full order (grid 0.589) | Winner score (grid 1.74) | Favourite won |
|---|---|---|---|---|---|
| Ignore rain | +9% | +3% | 0.628 | 1.43 | 6 of 13 |
| Rain window | +8% | +2% | 0.620 | 1.50 | 6 of 13 |
| Real conditions | +9% | +3% | 0.614 | 1.44 | 6 of 13 |

The 95% ranges are wide (win from about −8% to +25%; full order −0.02 to
+0.08 vs the grid). With 13 races, **the rain model predicts the finishing
order about as well as ignoring rain: no better, no worse.** All three modes
beat the grid baseline slightly, and none of those gaps is statistically
clear. Note these fixes were chosen on the same 13 races (there are no
others), so treat them as a development result, not an exam.

**Tyre behaviour against reality** (rain window mode):

- Going onto wet tyres: right in 11 of 12 races with a switch, because cars
  now start on wet tyres when the track is wet at the start (rule W8). The
  exception is Silverstone 2024: drizzle was flagged from lap 18, but the
  field switched on lap 27 (model: lap 19).
- Back to slicks: off by about 9 laps on average (median 8; from 25 laps
  early at Silverstone 2025, where a second shower kept the real field on
  intermediates, to 10 laps late at Zandvoort 2023). The model has one
  drying rate for every track.
- Swaps between intermediates and full wets: real drivers made 0.28 per car on
  average. Before the fix the model made about 1 per car, swapping back and
  forth every few laps in steady rain. Now it requires a swap to pay for its
  pit stop (rule W9): 0.26 per car.

**Your wet-weather call (switch early or late)** can only be checked
indirectly. Over 23 field-wide tyre changes in real wet races (401 driver
switches since 2018), each lap later than the field cost about 0.5 places
(95% CI 0.03 to 1.0). Real teams also spread their switches over several laps
(half on the median lap, standard deviation 1.1 laps). The model's effect is
about 5 times larger (at least 2.4 times, given that range): from P3 at
Silverstone with rain on laps 15–30, one lap early gains 1.7 places (+4.3
points) and one lap late loses 3.3 places (−4.0 points). The cause is the
assumed rate at which slicks lose time once the track is past the crossover
(rule W3: the data could not fit it). Giving rivals the real spread of switch
laps (rule W10) made predictions slightly worse on top of that too-steep penalty,
so it stays off until that slope is calibrated. The website shows the
real-race figure next to the model's number.

## What the improvements were

| Code | Change | Why the data supported it |
|---|---|---|
| I1 | Within a season, a team's recent races count more (car pace drifts race to race). | Predicting each next race improved by 35 log-likelihood units over equal weights (91 team-seasons). |
| I2 | Qualifying behind where a car's pace says it should is slower race pace that weekend: 0.042% of lap time per place. Uses the qualifying position, so grid penalties and pit-lane starts no longer count as slowness. | Refitted after the review on the priors the engine really has (687 driver-races, 2024–2025). |
| I4 | When dry qualifying times are known, race pace = 0.63 × season form + 0.36 × qualifying gap. | Refitted after the review the same way; the weights barely moved. |
| A1b | Rival strategies are drawn from drivers who started within 2 places (widened until at least 5 examples). | Teams choose strategies by grid position. |
| A1c | Each rival draws 5 such strategies and runs the quickest under this year's tyre model. | Practice score improved from best-of-1 up to 5; 8 and 12 were no better. |
| I3 | With qualifying known, pace randomness is scaled by 0.7 (0.35 before the review). Without it, the full fitted spread is kept. | Re-chosen on 2024 + 2025 with proper scores after the review found the old coverage check was faulty. |
| E1 | Teammates share one car-pace draw. | The car is one team quantity; the old per-car draw doubled the noise in the teammate gap. |
| M6 | Tyre values per track fade back to the cross-track average (mean-reverting) instead of drifting freely. | The track's own history forecast compound offsets worse than the average; now level with it, and lap-level tyre predictions improved in both seasons. |

## What this means for the website

- The website has two modes. **After qualifying** (paste the real grid and
  best laps) is the mode tested here. **Before qualifying** (you set the
  grid, and the model doesn't know this weekend's pace) was much weaker in
  the practice test: win −27% vs grid, winner score 1.35. Use it for
  "what if I started P5" questions, not for predicting a real race.
- Treat win and podium odds as honest but modest: over 14 unseen races they
  matched (win) or beat (podium, points, winner score) simply trusting the
  grid. The full predicted order beat the grid clearly.
- Treat strategy comparisons as experimental, especially differences under
  about 5 seconds.
- In the wet, the rain model gets tyre choices broadly right but does not
  predict the order better than ignoring rain. Its wet-weather call advice
  points the right way (earlier is better, as in real races) but overstates
  the effect about 5 times.
- The wet-race work left dry races exactly as they were (checked by
  rerunning the exam with and without it).

## Reproduce

```bash
.venv/bin/python scripts/export_quali.py                   # qualifying times (once)
.venv/bin/python scripts/build_processed.py
.venv/bin/python model/backtest.py fit 2024                 # tuning fits (~10 min each season)
.venv/bin/python model/backtest.py fit 2025 --redo
.venv/bin/python model/calibrate_pace.py                    # pace blend on as-of priors (I2, I4)
cd web && PATH="$HOME/.local/node/bin:$PATH" node --experimental-strip-types scripts/backtest-sim.ts 5000 2025
cd .. && .venv/bin/python model/score_backtest.py dev       # `tune` for 2024
# final exam: the same with 2026 and `score_backtest.py holdout`
.venv/bin/python model/param_forecast_check.py              # tyre parameter forecasts vs what each race showed
.venv/bin/python model/lap_tyre_check.py                    # lap-level teammate tyre test
.venv/bin/python model/strategy_pairs.py
cd web && PATH="$HOME/.local/node/bin:$PATH" node --experimental-strip-types scripts/strategy-check.ts 1000
cd .. && .venv/bin/python model/score_strategy.py
# wet races
cd .. && .venv/bin/python model/backtest.py wet             # as-of fits, ~1 min per race
.venv/bin/python model/backtest.py wet-races                # real conditions, rain windows, switch timing
cd web && PATH="$HOME/.local/node/bin:$PATH" node --experimental-strip-types scripts/backtest-wet.ts 4000
cd .. && .venv/bin/python model/score_backtest.py wet
.venv/bin/python model/wet_switch.py                        # real switch timing and its effect
```
