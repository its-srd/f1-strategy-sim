// Simulate every backtest race (data/backtest/<race>/params) from its real
// starting grid and write predictions.json next to it.
//   node --experimental-strip-types scripts/backtest-sim.ts [sims] [season]
// season: only races of that year (2025 = practice set, 2026 = final exam).
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { makeSetup } from "../src/engine/setup.ts";
import { POINTS, paceForecast, prepare, simulateRace } from "../src/engine/race.ts";
import type { Params, Scenario } from "../src/engine/types.ts";

const root = new URL("../../data/backtest/", import.meta.url);
const SIMS = Number(process.argv[2] ?? 5000);
const SEASON = process.argv[3] ?? "";
const SPREAD = process.argv[4] ? Number(process.argv[4]) : undefined;   // override the calibration scale
const CHOICES = process.argv[5] ? Number(process.argv[5]) : undefined;  // override rival strategy choices
const NO_WEEKEND_INFO = process.argv[6] === "nogridpace";             // ignore what the grid/qualifying say about pace
const PASS_SHIFT = process.argv[7] ? Number(process.argv[7]) : undefined;   // override the pass model shift (O3)
for (const key of readdirSync(root).filter((k) => /^\d{4}_\d{2}$/.test(k) && k.startsWith(SEASON)).sort()) {
  const dir = new URL(`${key}/`, root);
  if (!existsSync(new URL("params/meta.json", dir)) || !existsSync(new URL("race.json", dir))) continue;
  const L = (f: string) => JSON.parse(readFileSync(new URL(`params/${f}`, dir), "utf8"));
  const race = JSON.parse(readFileSync(new URL("race.json", dir), "utf8"));
  const params: Params = { tracks: L("tracks.json"), teams: L("teams.json"), drivers: L("drivers.json"),
    global: L("global.json"), grid: L("grid_2026.json"), meta: L("meta.json"),
    calibration: JSON.parse(readFileSync(new URL("../../data/params/calibration.json", import.meta.url), "utf8")) };
  // A season is scored with the pace blend fitted on earlier seasons only.
  const fwd = params.calibration?.pace_blend_forward?.[key.slice(0, 4)];
  if (params.calibration && fwd) params.calibration = { ...params.calibration, pace_blend: fwd };
  else if (params.calibration && key.slice(0, 4) !== "2026") delete params.calibration.pace_blend;
  // I5: the season's form spread as it stood before this race.
  if (params.calibration) params.calibration.season_form_ratio = params.calibration.season_form?.per_race?.[key]?.ratio ?? 1;
  const t = params.tracks[race.track];
  if (!t?.has_dry_data) { console.log(`${key} ${race.event}: no dry params, skipped`); continue; }
  const missing = params.grid.grid.filter((g) => !params.teams[g.team_id]).map((g) => g.team_id);
  if (missing.length) { console.log(`${key}: no ${missing.join(",")} car data yet, skipped`); continue; }
  const g0 = params.grid.grid[0];
  const sc: Scenario = { track: race.track, driver: g0.driver_id, team: g0.team_id, grid: 1,
    strategy: { stints: [{ compound: "MEDIUM", laps: 1 }, { compound: "HARD", laps: (t.total_laps ?? 2) - 1 }] },
    paceMode: "normal", reactToSC: true, weather: { kind: "dry" }, sims: SIMS, seed: 1, listedGrid: true, gridImpliesPace: !NO_WEEKEND_INFO, paceSpread: SPREAD, strategyChoices: CHOICES, sampleUserStrategy: true, passShift: PASS_SHIFT };
  const setup = makeSetup(params, sc), prep = prepare(setup);
  const n = setup.cars.length;
  const hist = setup.cars.map(() => new Float64Array(n + 1));
  const t0 = Date.now();
  // Track-position diagnostic (review 2.1): rank correlation of grid slot and
  // finishing position among classified cars, and mean places moved, per
  // simulated race; model/score_backtest.py compares them with the real race.
  let rhoSum = 0, movedSum = 0;
  for (let k = 0; k < SIMS; k++) {
    const r = simulateRace(setup, prep, 90001 + k * 7919, sc.strategy);
    r.cars.forEach((c, i) => { hist[i][c.dnf ? n : c.pos - 1]++; });
    const fin = r.cars.map((c, i) => ({ g: i + 1, p: c.pos, dnf: c.dnf })).filter((x) => !x.dnf);
    const gRank = new Map([...fin].sort((a, b) => a.g - b.g).map((x, j) => [x.g, j + 1]));
    const m = fin.length;
    let d2 = 0, moved = 0;
    for (const x of fin) { d2 += (gRank.get(x.g)! - x.p) ** 2; moved += Math.abs(gRank.get(x.g)! - x.p); }
    rhoSum += 1 - (6 * d2) / (m * (m * m - 1));
    movedSum += moved / m;
  }
  const paceF = paceForecast(setup);
  const out = setup.cars.map((c, i) => {
    const h = Array.from(hist[i], (x) => x / SIMS);
    const pts = h.slice(0, 10).reduce((a, p, j) => a + p * POINTS[j], 0);
    return { driver: c.driverId, team: c.teamId, grid: i + 1, win: h[0], podium: h[0] + h[1] + h[2],
      points: h.slice(0, 10).reduce((a, b) => a + b, 0), dnf: h[n], exp_points: pts, pace: paceF[i], pos_hist: h };
  });
  writeFileSync(new URL("predictions.json", dir), JSON.stringify({ key, sims: SIMS, drivers: out,
    diag: { grid_finish_rho: rhoSum / SIMS, mean_places_moved: movedSum / SIMS } }));
  const fav = [...out].sort((a, b) => b.win - a.win)[0];
  console.log(`${key} ${race.event.padEnd(28)} ${SIMS} sims ${Date.now() - t0} ms; favourite ${fav.driver} ${(100 * fav.win).toFixed(0)}%`);
}
