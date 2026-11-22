// Strategy check, part 2: for each teammate pair with different strategies
// (data/backtest/strategy_pairs.json), simulate the race from the real grid
// twice on the same random numbers:
//   actual: each teammate runs the strategy they really ran
//   blind:  both run teammate A's strategy (the model knows nothing of the difference)
// and record the predicted finishing-time gap (B - A). If the strategy model
// is right, "actual" should predict the real gap better than "blind".
//   node --experimental-strip-types scripts/strategy-check.ts [sims]
import { readFileSync, writeFileSync } from "node:fs";
import { makeSetup } from "../src/engine/setup.ts";
import { prepare, simulateRace } from "../src/engine/race.ts";
import type { Dry, Params, Scenario, Strategy } from "../src/engine/types.ts";

const root = new URL("../../data/backtest/", import.meta.url);
const SIMS = Number(process.argv[2] ?? 1000);
type Side = { driver: string; grid: number; time: number; pos: number; stints: { compound: Dry; laps: number }[] };
const pairs: { race: string; team: string; a: Side; b: Side }[] = JSON.parse(readFileSync(new URL("strategy_pairs.json", root), "utf8"));

const median = (v: number[]) => { const s = [...v].sort((x, y) => x - y); return s.length ? s[s.length >> 1] : NaN; };
const fit = (s: Side["stints"], n: number): Strategy => {
  // Make the stints add up to the race length (lap counts from timing can be off by one).
  const st = s.map((x) => ({ ...x }));
  st[st.length - 1].laps += n - st.reduce((a, x) => a + x.laps, 0);
  return { stints: st };
};

const out = [];
for (const pr of pairs) {
  const dir = new URL(`${pr.race}/`, root);
  const L = (f: string) => JSON.parse(readFileSync(new URL(`params/${f}`, dir), "utf8"));
  const race = JSON.parse(readFileSync(new URL("race.json", dir), "utf8"));
  const params: Params = { tracks: L("tracks.json"), teams: L("teams.json"), drivers: L("drivers.json"),
    global: L("global.json"), grid: L("grid_2026.json"), meta: L("meta.json"),
    calibration: JSON.parse(readFileSync(new URL("../../data/params/calibration.json", import.meta.url), "utf8")) };
  const N = params.tracks[race.track].total_laps!;
  const sa = fit(pr.a.stints, N), sb = fit(pr.b.stints, N);
  const run = (planB: Strategy) => {
    const sc: Scenario = { track: race.track, driver: pr.a.driver, team: pr.team, grid: 1, strategy: sa,
      paceMode: "normal", reactToSC: true, weather: { kind: "dry" }, sims: SIMS, seed: 5, listedGrid: true, gridImpliesPace: true,
      fixedPlans: { [pr.a.driver]: sa, [pr.b.driver]: planB } };
    const setup = makeSetup(params, sc), prep = prepare(setup);
    const ia = setup.cars.findIndex((c) => c.driverId === pr.a.driver), ib = setup.cars.findIndex((c) => c.driverId === pr.b.driver);
    const gaps: number[] = [];
    for (let k = 0; k < SIMS; k++) {
      const r = simulateRace(setup, prep, 4242 + k * 7919, sa);
      if (!r.cars[ia].dnf && !r.cars[ib].dnf) gaps.push(r.cars[ib].time - r.cars[ia].time);
    }
    return median(gaps);
  };
  const actualGap = pr.b.time - pr.a.time;
  const predActual = run(sb), predBlind = run(sa);
  const label = (s: Strategy) => s.stints.map((x) => `${x.compound[0]}${x.laps}`).join("-");
  out.push({ race: pr.race, team: pr.team, a: pr.a.driver, b: pr.b.driver, strategy_a: label(sa), strategy_b: label(sb),
    actual_gap_s: actualGap, predicted_gap_with_strategies_s: predActual, predicted_gap_strategy_blind_s: predBlind,
    predicted_strategy_effect_s: predActual - predBlind });
  console.log(`${pr.race} ${pr.team.padEnd(13)} ${label(sa).padEnd(12)} vs ${label(sb).padEnd(12)} real gap ${actualGap.toFixed(1).padStart(6)} s | model ${predActual.toFixed(1).padStart(6)} s (blind ${predBlind.toFixed(1)})`);
}
writeFileSync(new URL("strategy_check.json", root), JSON.stringify(out, null, 1));
