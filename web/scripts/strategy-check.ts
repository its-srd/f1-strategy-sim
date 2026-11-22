// Strategy check, part 2: for each teammate pair with different strategies
// (data/backtest/strategy_pairs.json), simulate the race from the real grid
// twice on the same random numbers:
//   actual: each teammate runs the strategy they really ran
//   blind:  both run teammate A's strategy (the model knows nothing of the difference)
// and record the predicted finishing-time gap (B - A). If the strategy model
// is right, "actual" should predict the real gap better than "blind".
// Three modes (review section 4):
//   random  safety cars drawn at random, as the website does
//   replay  the race's real track status lap by lap; the pair's real stops
//           already contain their safety-car reactions, so they do not react again
//   oracle  replay, plus the tyre parameters this race actually showed: if
//           the engine still cannot beat "blind" with the true tyres, the
//           problem is in the race mechanics, not in the tyre forecast
//   node --experimental-strip-types scripts/strategy-check.ts [sims]
// Scored by model/score_strategy.py.
import { readFileSync, writeFileSync } from "node:fs";
import { makeSetup } from "../src/engine/setup.ts";
import { prepare, simulateRace } from "../src/engine/race.ts";
import type { Dry, Params, Scenario, Strategy } from "../src/engine/types.ts";

const root = new URL("../../data/backtest/", import.meta.url);
const SIMS = Number(process.argv[2] ?? 1000);
type Side = { driver: string; grid: number; time: number; pos: number; stints: { compound: Dry; laps: number }[] };
type Pair = { race: string; team: string; kind: string; reactive: boolean; status: number[];
  oracle: Record<string, { mean_s: number; sd_s: number }>; a: Side; b: Side };
const pairs: Pair[] = JSON.parse(readFileSync(new URL("strategy_pairs.json", root), "utf8"));
const calibration = JSON.parse(readFileSync(new URL("../../data/params/calibration.json", import.meta.url), "utf8"));

const median = (v: number[]) => { const s = [...v].sort((x, y) => x - y); return s.length ? s[s.length >> 1] : NaN; };
const fit = (s: Side["stints"], n: number): Strategy => {
  // Make the stints add up to the race length (lap counts from timing can be off by one).
  const st = s.map((x) => ({ compound: x.compound, laps: x.laps }));
  st[st.length - 1].laps += n - st.reduce((a, x) => a + x.laps, 0);
  return { stints: st };
};
const label = (s: Strategy) => s.stints.map((x) => `${x.compound[0]}${x.laps}`).join("-");

const out = [];
for (const pr of pairs) {
  const dir = new URL(`${pr.race}/`, root);
  const L = (f: string) => JSON.parse(readFileSync(new URL(`params/${f}`, dir), "utf8"));
  const race = JSON.parse(readFileSync(new URL("race.json", dir), "utf8"));
  const load = (): Params => ({ tracks: L("tracks.json"), teams: L("teams.json"), drivers: L("drivers.json"),
    global: L("global.json"), grid: L("grid_2026.json"), meta: L("meta.json"),
    calibration: { ...calibration, pace_blend: calibration.pace_blend_forward?.[pr.race.slice(0, 4)] ?? calibration.pace_blend,
      season_form_ratio: calibration.season_form?.per_race?.[pr.race]?.ratio ?? 1 } });
  const N = L("tracks.json")[race.track].total_laps;
  const sa = fit(pr.a.stints, N), sb = fit(pr.b.stints, N);
  const run = (params: Params, planB: Strategy, replay: boolean) => {
    const sc: Scenario = { track: race.track, driver: pr.a.driver, team: pr.team, grid: 1, strategy: sa,
      paceMode: "normal", reactToSC: true, weather: { kind: "dry" }, sims: SIMS, seed: 5, listedGrid: true, gridImpliesPace: true,
      fixedPlans: { [pr.a.driver]: sa, [pr.b.driver]: planB }, statusTrace: replay ? pr.status : undefined };
    const setup = makeSetup(params, sc), prep = prepare(setup);
    const ia = setup.cars.findIndex((c) => c.driverId === pr.a.driver), ib = setup.cars.findIndex((c) => c.driverId === pr.b.driver);
    const gaps: number[] = [];
    for (let k = 0; k < SIMS; k++) {
      const r = simulateRace(setup, prep, 4242 + k * 7919, sa);
      if (!r.cars[ia].dnf && !r.cars[ib].dnf) gaps.push(r.cars[ib].time - r.cars[ia].time);
    }
    return median(gaps);
  };
  const oracleParams = load();
  const pace = oracleParams.tracks[race.track].pace!;
  for (const [k, v] of Object.entries(pr.oracle)) if (pace[k]) pace[k] = { ...pace[k], mean_s: v.mean_s, sd_s: v.sd_s };
  const modes: Record<string, { actual: number; blind: number }> = {};
  for (const [mode, params, replay] of [["random", load(), false], ["replay", load(), true], ["oracle", oracleParams, true]] as const)
    modes[mode] = { actual: run(params, sb, replay), blind: run(params, sa, replay) };
  const actualGap = pr.b.time - pr.a.time;
  out.push({ race: pr.race, team: pr.team, kind: pr.kind, reactive: pr.reactive, a: pr.a.driver, b: pr.b.driver,
    strategy_a: label(sa), strategy_b: label(sb), actual_gap_s: actualGap, oracle_params: Object.keys(pr.oracle), modes });
  console.log(`${pr.race} ${pr.team.padEnd(13)} ${label(sa).padEnd(12)} vs ${label(sb).padEnd(12)} real ${actualGap.toFixed(1).padStart(6)} s | ` +
    Object.entries(modes).map(([m, v]) => `${m} ${v.actual.toFixed(1)} (blind ${v.blind.toFixed(1)})`).join(" | "));
}
writeFileSync(new URL("strategy_check.json", root), JSON.stringify(out, null, 1));
