// Live forecast of one race from its official starting grid.
//   node --experimental-strip-types scripts/forecast.ts <in.json> <out.json> [sims]
// in.json: { track, grid: GridEntry[] in starting order, with quali_gap_pct }
// Uses the current fitted parameters (public/params), the backtested
// after-qualifying mode, and observed strategies for every car.
import { readFileSync, writeFileSync } from "node:fs";
import { makeSetup } from "../src/engine/setup.ts";
import { POINTS, prepare, simulateRace } from "../src/engine/race.ts";
import type { GridEntry, Params, Scenario } from "../src/engine/types.ts";

const [inPath, outPath, simsArg] = process.argv.slice(2);
const SIMS = Number(simsArg ?? 10000);
const input = JSON.parse(readFileSync(inPath, "utf8")) as { track: string; grid: GridEntry[] };
const dir = new URL("../public/params/", import.meta.url);
const L = (f: string) => JSON.parse(readFileSync(new URL(f, dir), "utf8"));
const params: Params = { tracks: L("tracks.json"), teams: L("teams.json"), drivers: L("drivers.json"),
  global: L("global.json"), grid: L("grid_2026.json"), meta: L("meta.json"), calibration: L("calibration.json") };

const t = params.tracks[input.track];
if (!t?.has_dry_data) throw new Error(`no dry-race parameters for ${input.track}`);
const g0 = input.grid[0];
const sc: Scenario = { track: input.track, driver: g0.driver_id, team: g0.team_id, grid: 1,
  strategy: { stints: [{ compound: "MEDIUM", laps: 1 }, { compound: "HARD", laps: (t.total_laps ?? 2) - 1 }] },
  paceMode: "normal", reactToSC: true, weather: { kind: "dry" }, sims: SIMS, seed: 2026,
  listedGrid: true, gridImpliesPace: true, sampleUserStrategy: true, gridEntries: input.grid };
const setup = makeSetup(params, sc), prep = prepare(setup);
const n = setup.cars.length;
const hist = setup.cars.map(() => new Float64Array(n + 1));
for (let k = 0; k < SIMS; k++) {
  const r = simulateRace(setup, prep, 31337 + k * 7919, sc.strategy);
  r.cars.forEach((c, i) => { hist[i][c.dnf ? n : c.pos - 1]++; });
}
const drivers = setup.cars.map((c, i) => {
  const h = Array.from(hist[i], (x) => x / SIMS);
  return { code: c.code, driver_id: c.driverId, team_id: c.teamId, grid: i + 1,
    win: h[0], podium: h[0] + h[1] + h[2], points: h.slice(0, 10).reduce((a, b) => a + b, 0), dnf: h[n],
    exp_points: h.slice(0, 10).reduce((a, p, j) => a + p * POINTS[j], 0),
    exp_pos: h.reduce((a, p, j) => a + p * (j + 1), 0), pos_hist: h };
});
writeFileSync(outPath, JSON.stringify({ sims: SIMS, model_data_through: params.meta.data_through, drivers }, null, 1));
const fav = [...drivers].sort((a, b) => b.win - a.win).slice(0, 3);
console.log(`forecast ${input.track}: ${fav.map((d) => `${d.code} ${(100 * d.win).toFixed(0)}%`).join(", ")}`);
