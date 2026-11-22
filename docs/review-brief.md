# Independent review brief

Paste this into a new Claude Code session opened in the `f1-strategy-sim`
folder (pick the model in the session's model picker before the first message).

---

You are reviewing an F1 race strategy simulator built in this folder. I want
an independent, critical read: what is wrong, weak, or unsupported by the
data, and what would most improve prediction accuracy. Do not change any code
yet. Deliver a written review; I will take the suggestions back to the
session that built it.

## What the project is

A static website (Vite + Preact, TypeScript Monte Carlo engine in a Web
Worker) for technical F1 fans: pick a track, driver, car, grid slot, strategy
and weather; it simulates about 10,000 races and shows win/podium/points
probabilities, the race trace, stint map, where the strategy gains or loses
time, and the best alternative. The goals, in order: predict the winner,
predict the full finishing order, and give "what if you had pitted
differently" strategy advice.

Principles I set: every model parameter is fitted from data (never
hand-picked); assumptions and sample sizes are documented; uncertainty is
shown; thin data falls back to pooled values and is labelled as such. Tell me
directly when an idea is weak or the data cannot support it.

## Read these first

1. `README.md`: overview, data sources, how to rebuild.
2. `docs/assumptions.md`: every modelling rule, with codes (D, L, R, F, M, B,
   T, S, E, A, G, O, PM, C, I, U, W) and the fitted values.
3. `docs/backtest.md`: how the model was tested against real races and the
   scores (2025 practice set, 2026 final exam, wet races).
4. Code: `model/*.py` (fitting, Python 3.9 venv), `web/src/engine/*.ts`
   (simulation), `web/src/main.tsx` (UI), `scripts/` (data export, weekend
   automation, publishing).

## What I want from the review

1. **Correctness bugs** in the fitting or simulation code (leakage of future
   data into backtests, wrong units, off-by-one laps, sign errors, rules
   applied in the wrong condition). For each: file and line, what goes wrong,
   and how you would confirm it.
2. **Modelling weaknesses** ranked by expected effect on accuracy, with the
   evidence from the code or docs. Say which ones the available data could
   actually fix and which it cannot.
3. **Hand-chosen values or rules** that are presented as fitted, or that could
   be fitted.
4. **The strategy what-if advice failed its validation** (worse in 2026).
   Suggest concrete, testable changes.
5. **Code quality**: anything fragile or hard to maintain, briefly.
6. A short **prioritised list**: the 5 changes you would make first, each with
   how to measure whether it helped (the backtest in `model/backtest.py`,
   `web/scripts/backtest-sim.ts`, `web/scripts/backtest-wet.ts`,
   `model/score_backtest.py`).

Write the review to `docs/review-<date>.md` inside this folder.

## Rules (strict)

- Work only inside this `f1-strategy-sim` folder. Do not write files anywhere
  else on the Mac (no global installs, nothing in the home folder or
  ~/Library/Caches).
- Python only through `.venv/bin/python`. Node is at `~/.local/node/bin`; the
  npm cache is already kept inside the project by `web/.npmrc`.
- Ask before installing anything, before any step that takes more than 30
  minutes, and before any git commit or push.
- Do not publish or upload F1 data (data/raw, data/processed and the backtest
  per-race folders are gitignored on purpose).
- All code changes, when we get to them, use the `human-style-code` skill.
