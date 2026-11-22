# Backtest: how well does the simulator predict real races?

Run 2026-11-22. Numbers come from `data/backtest/scores_dev.json`, `scores_holdout.json` and `strategy_check.json`.

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
| Practice | 18 dry races of 2025 (rounds 5–24) | Trying improvements; kept only if the score improved |
| Final exam | 13 dry races of 2026 (rounds 4–19) | Scored **once**, at the end, to check the gains are real |

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
- **80% range** is the share of drivers who finished inside the range the
  model called 80% likely. It should be about 80%.

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
| + rivals pick the quickest of 5 nearby strategies, randomness × 0.35 | **−7%** | **−2%** | **+2%** | **1.12** | 0.647 | 93% | **50%** |

### Final exam (2026), scored once with the final model

| | Win | Podium | Points | Retirements | Winner score | Full order | 80% range | Favourite won |
|---|---|---|---|---|---|---|---|---|
| Model | −3% | **+3%** | **+6%** | +0.5% | **1.21** | **0.703** | 90% | **69%** (9 of 13) |
| Grid-only baseline | 0 | 0 | 0 | 0 | 1.62 | 0.663 | – | pole: 69% |

**In plain English:**
- On races it had never seen, the model **beats the grid baseline on podium
  and points chances, on how surprised it is by the winner, and on the full
  finishing order.**
- Only the full-order gain is clear of luck: its 95% range, +0.005 to +0.073,
  stays above zero. The other gains are positive but within what luck could
  produce over 13 races.
- **Win chances are level with the baseline.** The model's favourite won 9
  of 13 races, the same rate as the pole-sitter.
- The model is still a bit too cautious: 90% of results fall inside its
  "80% range".

### Strategy "what if" check (teammates on different strategies)

Same car, same race, different plans. The engine predicts the gap between the
two drivers twice: once with the strategies they really ran, and once
ignoring the difference ("blind"). If the strategy model is right, knowing the
strategies should bring the prediction closer to the real gap.

| Set | Pairs | Typical error, with strategies | Typical error, blind | Average gain from knowing strategies | Right direction when the model predicts a > 5 s effect |
|---|---|---|---|---|---|
| Practice (2025) | 47 | 9.0 s | 11.5 s | +0.5 s (95% range −1.9 to +2.7) | 67% (14 of 21) |
| Final exam (2026) | 18 | 12.7 s | 6.9 s | **−2.7 s** (95% range −6.0 to −0.3) | 60% (3 of 5) |

**In plain English:** the strategy comparison is **not validated.** In 2025
it helped a little, within luck. In 2026 it made predictions worse. A likely
reason is that 2026 tyre-wear estimates still lean on older seasons (test V1
kept them). The website labels the strategy comparison as experimental.

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

**Results after the fixes:**

| Mode | Win (vs grid) | Points (vs grid) | Full order (grid 0.589) | Winner score (grid 1.74) | Favourite won |
|---|---|---|---|---|---|
| Ignore rain | +10% | +3% | 0.616 | 1.46 | 6 of 13 |
| Rain window | +8% | +4% | 0.618 | 1.44 | 6 of 13 |
| Real conditions | +13% | +2% | 0.612 | 1.38 | 6 of 13 |

The 95% ranges are wide (win from about −9% to +25%; full order −0.02 to
+0.07 vs the grid). With 13 races, **the rain model predicts the finishing
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
Silverstone with rain on laps 15–30, one lap early gains 1.8 places (+4.3
points) and one lap late loses 3.0 places (−3.4 points). The cause is the
assumed rate at which slicks lose time once the track is past the crossover
(rule W3: the data could not fit it). Giving rivals the real spread of switch
laps (rule W10) made predictions slightly worse on top of that too-steep penalty,
so it stays off until that slope is calibrated. The website shows the
real-race figure next to the model's number.

## What the improvements were

| Code | Change | Why the data supported it |
|---|---|---|
| I1 | Within a season, a team's recent races count more (car pace drifts race to race). | Predicting each next race improved by 35 log-likelihood units over equal weights (91 team-seasons). |
| I2 | A grid slot behind where a car's pace says it should start means slower race pace that weekend: 0.037% of lap time per place (±0.002). | Fitted on 2,695 driver-races. |
| I4 | When dry qualifying times are known, race pace = 0.66 × season form + 0.29 × qualifying gap. | Both weights are many times their uncertainty (2,314 driver-races). |
| A1b | Rival strategies are drawn from drivers who started within 2 places (widened until at least 5 examples). | Teams choose strategies by grid position. |
| A1c | Each rival draws 5 such strategies and runs the quickest under this year's tyre model. | Practice score improved from best-of-1 up to 5; 8 and 12 were no better. |
| I3 | With qualifying known, pace randomness is scaled by 0.35. Without it, the full fitted spread is kept. | Chosen on the practice races. Without qualifying, narrowing gave no consistent gain. |

## What this means for the website

- The website has two modes. **After qualifying** (paste the real grid and
  best laps) is the mode tested here. **Before qualifying** (you set the
  grid, and the model doesn't know this weekend's pace) was much weaker in
  the practice test: win −27% vs grid, winner score 1.35. Use it for
  "what if I started P5" questions, not for predicting a real race.
- Treat win and podium odds as honest but modest: over 13 unseen races they
  matched or slightly beat simply trusting the grid.
- Treat strategy comparisons as experimental, especially differences under
  about 5 seconds.
- In the wet, the rain model gets tyre choices broadly right but does not
  predict the order better than ignoring rain. Its wet-weather call advice
  points the right way (earlier is better, as in real races) but overstates
  the effect about 5 times.
- The final-exam scores above come from the engine as it was on the exam
  day. Rerunning the exam with the current engine gives win −3% and full order
  0.707 (was 0.703). The difference comes from engine changes made before the
  wet-race work; that work itself leaves dry races exactly as they were
  (checked by rerunning the exam with and without it).

## Reproduce

```bash
.venv/bin/python scripts/export_quali.py                   # qualifying times (once)
.venv/bin/python scripts/build_processed.py
.venv/bin/python model/backtest.py fit 2025 --redo         # practice fits (~10 min)
cd web && PATH="$HOME/.local/node/bin:$PATH" node --experimental-strip-types scripts/backtest-sim.ts 10000 2025
cd .. && .venv/bin/python model/score_backtest.py dev
# final exam: the same with 2026 and `score_backtest.py holdout`
.venv/bin/python model/strategy_pairs.py
cd web && PATH="$HOME/.local/node/bin:$PATH" node --experimental-strip-types scripts/strategy-check.ts 1000
# wet races
cd .. && .venv/bin/python model/backtest.py wet             # as-of fits, ~1 min per race
.venv/bin/python model/backtest.py wet-races                # real conditions, rain windows, switch timing
cd web && PATH="$HOME/.local/node/bin:$PATH" node --experimental-strip-types scripts/backtest-wet.ts 4000
cd .. && .venv/bin/python model/score_backtest.py wet
.venv/bin/python model/wet_switch.py                        # real switch timing and its effect
```
