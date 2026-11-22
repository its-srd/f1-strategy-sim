# F1 Strategy Simulator

**Live site:** https://its-srd.github.io/f1-strategy-sim/

A static website for technical F1 fans. Pick a track, a driver, any 2026 car,
a grid slot, a strategy (stops, compounds, pit laps, pace mode) and the
weather. Once a race's qualifying has run, switch to "After qualifying": the
real grid and qualifying times are loaded automatically (from Jolpica-F1, in
the browser, only when you choose that mode), and you can still move your
driver for a what-if. This is the backtested, more accurate mode. A Monte Carlo engine in a Web Worker then simulates 10,000 races and
shows:
- win, podium, points and retirement probability for every driver
- the median race trace (gap to the leader)
- a tyre stint map
- where your strategy gains or loses time against the best alternative the
  model finds, with a paired ± error

Parameters are fitted from 2018–2026 race data where the data allows. The
structural choices and the few settings tuned on the backtest are listed,
with the reason for each, in [docs/assumptions.md](docs/assumptions.md).
Tested on races it had never seen: it beats a grid-only baseline on podium
and points chances and on the full finishing order, and is level on win
chances. The strategy comparison is not yet validated. Details in
[docs/backtest.md](docs/backtest.md), also shown on the site's
"Track record" tab. An independent review of the whole project (kept
locally, not published) and what was done about each of its points are
summarised in [docs/assumptions.md](docs/assumptions.md).
Structural choices and every sample size are in
[docs/assumptions.md](docs/assumptions.md), which the site shows on its
"Model & assumptions" tab.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Data export | Done 2026-11-22: 193 races, 2018 R1 to 2026 R20 |
| 2 | Model fitting (Python) | Done: `data/params/*.json` |
| 3 | Simulation engine (TypeScript, Web Worker) | Done: `web/src/engine/` |
| 4 | Website | Done: `web/` (static build in `web/dist/`) |
| – | Backtest | Done: 18 practice races (2025) + 13 exam races (2026), see [docs/backtest.md](docs/backtest.md); 13 wet races (2022–2026): the rain model gets tyre choices broadly right but predicts the order no better than ignoring rain |
| – | Claude explanation panel | Optional proxy in `web/server/`; off unless configured |

## Layout

```
data/cache/      FastF1 schedule cache (set explicitly; never the default location)
data/raw/        per-race exports, data/raw/<year>/ (laps, results, source JSON, meta)
data/processed/  combined laps / results / races tables; fits/ = intermediate fits
data/params/     fitted parameters (JSON) consumed by the website
scripts/         export_races.py, build_processed.py
model/           fitting code; fit_all.py runs everything, report.py writes the doc tables
web/             Vite + Preact site; src/engine = Monte Carlo engine
web/server/      optional Claude explanation proxy (keeps the API key server-side)
docs/            assumptions.md (structural assumptions + generated results)
```

## Rebuild from scratch

Everything installs inside this folder. Python uses `.venv`. Node is the
existing install at `~/.local/node/bin`, with npm's cache and logs set to
`web/.npm-cache` by `web/.npmrc`.

```bash
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt

# After every race weekend, one command adds the new race and qualifying,
# retrains and rebuilds the site (a few minutes):
./scripts/update.sh

# Or step by step:
# 1. data (about 15 min the first time; resumable; rerun to add new races)
.venv/bin/python scripts/export_races.py
.venv/bin/python scripts/build_processed.py

.venv/bin/python scripts/export_quali.py      # qualifying lap times (used by the pace blend)
.venv/bin/python scripts/build_processed.py   # rerun so quali.csv is included

# 2. model (about 2.5 min) -> data/params/*.json and the results section of docs/assumptions.md
.venv/bin/python model/fit_all.py
.venv/bin/python model/report.py

# 3 + 4. website
cd web
PATH="$HOME/.local/node/bin:$PATH" npm install
PATH="$HOME/.local/node/bin:$PATH" npm run dev      # http://localhost:5178
PATH="$HOME/.local/node/bin:$PATH" npm run build    # static site in web/dist/
PATH="$HOME/.local/node/bin:$PATH" npm test         # headless engine check (Monza, 2,000 races)
```

Backtest (about 25 min in total): see the "Reproduce" section of
[docs/backtest.md](docs/backtest.md). `data/params/calibration.json` holds the
two settings chosen on the 2025 practice races.

To republish the website by hand after a change: `./scripts/publish_site.sh`
(builds the site and pushes it to the `gh-pages` branch, which GitHub Pages
serves).

`web/dist/` is plain static files (relative paths), so any free static host
works (GitHub Pages, Cloudflare Pages, Netlify).

## Race-weekend automation (live track record)

`scripts/weekend.py` is safe to run any time and does only what is due:
1. **Forecast:** once the next race's official starting grid (penalties
   applied, from OpenF1) is published and before the race starts, it
   simulates the race with the current model and saves the forecast
   untouched in `data/forecasts/`. It never forecasts from the bare
   qualifying order.
2. **Score:** when the result is published, it compares the forecast with
   what happened and with the grid-only baseline.
3. **Retrain:** it runs `scripts/update.sh` once a finished race isn't in
   the model yet.
4. **Publish:** it rewrites `docs/live_record.md`, shown first on the site's
   Track record tab. If anything changed, it commits the results to this
   repository and republishes the site (`scripts/publish_site.sh`). Set
   `F1SIM_PUBLISH=0` to keep a run local.

A scheduled task in the Claude desktop app (`f1-race-weekend`) runs it every
4 hours, Friday to Monday. It runs only while the app is open and the Mac is
awake; a missed run happens on the next launch. The current setup covers the
2026 season. The 2027 season needs the target year moved forward (`TARGET` in
`model/fit_all.py` and the 2026 calendar file).

## Data sources

| Data | Source | Notes |
|---|---|---|
| Lap timing, tyres, track status, per-lap weather, race control | [TracingInsights season repos](https://github.com/TracingInsights) (`github.com/TracingInsights/<year>`) | FastF1 output published on GitHub. Each season is pinned to a git commit, recorded in each race's `_meta.json`. |
| Results, grid, points, calendar, circuit identity | [Jolpica-F1](https://api.jolpi.ca) (Ergast successor) | The track key everywhere is Jolpica's `circuitId`. |
| Event names (to locate folders) | FastF1 schedule | Cached in `data/cache/`. |

Why not FastF1 directly: since October 2026, Formula 1's timing archive
requires an F1 TV Access login, and FastF1 3.9 needs Python ≥ 3.10.

**Licensing:** the repo licences cover TracingInsights' code, not Formula 1's
timing data. The site ships only fitted parameters, never raw laps.

## Optional: Claude explanation panel

Claude only interprets the simulator's output; it never makes the prediction.
The browser never sees an API key.

```bash
cd web/server
PATH="$HOME/.local/node/bin:$PATH" npm install
ALLOWED_ORIGIN=http://localhost:5178 PATH="$HOME/.local/node/bin:$PATH" npm start   # needs ANTHROPIC_API_KEY or an `ant auth login` profile
```

Then build or run the site with `VITE_EXPLAIN_URL=http://localhost:8787/explain`
and an "Explain these results" panel appears under the results. The proxy uses
`claude-opus-5-5` at low effort with server-side refusal fallbacks, limits
request size, allows one origin, and rate-limits per IP.
