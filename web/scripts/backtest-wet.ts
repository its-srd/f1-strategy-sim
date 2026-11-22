// Wet-race backtest: simulate each wet race (data/backtest/wet/<race>/params,
// fitted on earlier races only) three ways and write predictions_<mode>.json.
//   node --experimental-strip-types scripts/backtest-wet.ts [sims] [variant]
// variant (experiments, written as predictions_<mode>_<variant>.json):
//   noskill     driver wet effects switched off (0 mean, 0 spread)
//   spreadonly  no per-driver means, every driver drawn from the pooled spread
// Modes:
//   dry     the model told nothing about rain (what the dry backtest does)
//   window  a rain window, as a user would enter it: from the first lap with
//           rain or a wet-tyre majority to the last such lap (lap 1 if the
//           race started on wet tyres)
//   trace   hindsight: the real lap-by-lap conditions (best-tyre ratio)
// Besides finishing-order predictions, each mode records when the simulated
// field switched: first lap with at least half the running cars on wet
// tyres, and the first lap after that with half back on slicks.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { makeSetup } from "../src/engine/setup.ts";
import { POINTS, prepare, simulateRace } from "../src/engine/race.ts";
import type { Params, Scenario, Weather } from "../src/engine/types.ts";

const root = new URL("../../data/backtest/wet/", import.meta.url);
const SIMS = Number(process.argv[2] ?? 4000);
const VARIANT = process.argv[3] ?? "";
const calibration = JSON.parse(readFileSync(new URL("../../data/params/calibration.json", import.meta.url), "utf8"));
calibration.season_form_ratio = 1;        // I5 is measured on dry backtest races only; wet races keep the long-run spread

const quantile = (xs: number[], q: number) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
};

for (const key of readdirSync(root).filter((k) => /^\d{4}_\d{2}$/.test(k)).sort()) {
  const dir = new URL(`${key}/`, root);
  if (!existsSync(new URL("params/meta.json", dir)) || !existsSync(new URL("race.json", dir))) continue;
  const L = (f: string) => JSON.parse(readFileSync(new URL(`params/${f}`, dir), "utf8"));
  const race = JSON.parse(readFileSync(new URL("race.json", dir), "utf8"));
  const params: Params = { tracks: L("tracks.json"), teams: L("teams.json"), drivers: L("drivers.json"),
    global: L("global.json"), grid: L("grid_2026.json"), meta: L("meta.json"), calibration };
  if (VARIANT === "noskill") {
    for (const d of Object.values(params.drivers) as { wet_extra_pct?: number; wet_extra_sd?: number }[]) { d.wet_extra_pct = 0; d.wet_extra_sd = 0; }
    params.global.wet.driver_wet_skill.between_driver_sd_pct = 0;
  }
  if (VARIANT === "spreadonly") {
    // no driver-specific means; every driver draws from the pooled spread
    const sd = params.global.wet.driver_wet_skill.between_driver_sd_pct;
    for (const d of Object.values(params.drivers) as { wet_extra_pct?: number; wet_extra_sd?: number }[]) { d.wet_extra_pct = 0; d.wet_extra_sd = sd; }
  }
  const t = params.tracks[race.track];
  if (!t?.has_dry_data) { console.log(`${key} ${race.event}: no dry params, skipped`); continue; }
  const missing = params.grid.grid.filter((g) => !params.teams[g.team_id]).map((g) => g.team_id);
  if (missing.length) { console.log(`${key}: no ${missing.join(",")} car data yet, skipped`); continue; }
  const N = t.total_laps ?? race.best_ratio.length;
  const modes: Record<string, Weather> = {
    dry: { kind: "dry" },
    // no lap with rain or a wet-tyre majority: a user would have entered no rain
    window: race.window ? { kind: "window", startLap: race.window[0], endLap: race.window[1] } : { kind: "dry" },
    trace: { kind: "trace", best: race.best_ratio },
  };
  const g0 = params.grid.grid[0];
  const summary: Record<string, unknown> = {};
  for (const [mode, weather] of Object.entries(modes)) {
    const sc: Scenario = { track: race.track, driver: g0.driver_id, team: g0.team_id, grid: 1,
      strategy: { stints: [{ compound: "MEDIUM", laps: 1 }, { compound: "HARD", laps: N - 1 }] },
      paceMode: "normal", reactToSC: true, weather, sims: SIMS, seed: 1, listedGrid: true,
      gridImpliesPace: true, sampleUserStrategy: true };
    const setup = makeSetup(params, sc), prep = prepare(setup);
    const n = setup.cars.length;
    const hist = setup.cars.map(() => new Float64Array(n + 1));
    const onto: number[] = [], back: number[] = [];
    let anyWet = 0, stops = 0, swaps = 0, cars = 0;
    for (let k = 0; k < SIMS; k++) {
      const r = simulateRace(setup, prep, 90001 + k * 7919, sc.strategy);
      r.cars.forEach((c, i) => { hist[i][c.dnf ? n : c.pos - 1]++; });
      // share of running cars on wet tyres, lap by lap
      const wetOn = new Float64Array(N + 1), running = new Float64Array(N + 1);
      for (const c of r.cars) for (const st of c.stints) {
        const to = st.to || N;
        for (let lap = st.from; lap <= Math.min(to, N); lap++) {
          running[lap]++;
          if (st.compound === "INTERMEDIATE" || st.compound === "WET") wetOn[lap]++;
        }
      }
      // stops per finisher, and swaps between intermediates and full wets
      for (const c of r.cars) {
        if (c.dnf) continue;
        cars++; stops += c.stints.length - 1;
        for (let j = 1; j < c.stints.length; j++) {
          const x = c.stints[j - 1].compound, y = c.stints[j].compound;
          if ((x === "INTERMEDIATE" && y === "WET") || (x === "WET" && y === "INTERMEDIATE")) swaps++;
        }
      }
      let a: number | null = null, b: number | null = null;
      for (let lap = 1; lap <= N; lap++) {
        const share = running[lap] ? wetOn[lap] / running[lap] : 0;
        if (a === null && share >= 0.5) a = lap;
        else if (a !== null && b === null && share < 0.5) { b = lap; break; }
      }
      if (a !== null) { anyWet++; onto.push(a); if (b !== null) back.push(b); }
    }
    const drivers = setup.cars.map((c, i) => {
      const h = Array.from(hist[i], (x) => x / SIMS);
      return { driver: c.driverId, team: c.teamId, grid: i + 1, win: h[0], podium: h[0] + h[1] + h[2],
        points: h.slice(0, 10).reduce((x, y) => x + y, 0), dnf: h[n],
        exp_points: h.slice(0, 10).reduce((x, p, j) => x + p * POINTS[j], 0), pos_hist: h };
    });
    const sw = { share_sims_field_on_wet: anyWet / SIMS, stops_per_finisher: stops / cars, inter_wet_swaps_per_finisher: swaps / cars,
      onto_wet_median: quantile(onto, 0.5), onto_wet_p10: quantile(onto, 0.1), onto_wet_p90: quantile(onto, 0.9),
      back_median: quantile(back, 0.5), back_p10: quantile(back, 0.1), back_p90: quantile(back, 0.9) };
    writeFileSync(new URL(`predictions_${mode}${VARIANT ? "_" + VARIANT : ""}.json`, dir), JSON.stringify({ key, mode, sims: SIMS, switch: sw, drivers }));
    const fav = [...drivers].sort((x, y) => y.win - x.win)[0];
    summary[mode] = `${fav.driver} ${(100 * fav.win).toFixed(0)}%, onto wet ${sw.onto_wet_median ?? "-"} back ${sw.back_median ?? "-"}, stops ${sw.stops_per_finisher.toFixed(1)} (I-W swaps ${sw.inter_wet_swaps_per_finisher.toFixed(1)})`;
  }
  console.log(`${key} ${race.event.padEnd(26)} real onto wet ${race.real_onto_wet_lap ?? "-"} back ${race.real_back_to_slicks_lap ?? "-"} | ` +
    Object.entries(summary).map(([m, v]) => `${m}: ${v}`).join(" | "));
}
