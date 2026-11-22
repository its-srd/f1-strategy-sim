// Invariant tests for the race engine (review section 5): things that must
// hold for every simulated race, whatever the parameters say.
//   node --experimental-strip-types scripts/invariants.ts
// Exits with code 1 and lists the failures if any check fails.
import { readFileSync } from "node:fs";
import { makeSetup } from "../src/engine/setup.ts";
import { prepare, simulateRace } from "../src/engine/race.ts";
import type { Params, Scenario, Weather } from "../src/engine/types.ts";
import { validateParams } from "../src/engine/validate.ts";

const dir = new URL("../public/params/", import.meta.url);
const load = (f: string) => JSON.parse(readFileSync(new URL(f, dir), "utf8"));
const params: Params = { tracks: load("tracks.json"), teams: load("teams.json"), drivers: load("drivers.json"),
  global: load("global.json"), grid: load("grid_2026.json"), meta: load("meta.json"), calibration: load("calibration.json") };

const failures: string[] = [];
const check = (ok: boolean, what: string) => { if (!ok && failures.length < 30) failures.push(what); };

// The parameter files must have every value the engine reads.
for (const problem of validateParams(params)) check(false, `parameters: ${problem}`);

const g0 = params.grid.grid[3];
const weathers: Weather[] = [{ kind: "dry" }, { kind: "window", startLap: 1, endLap: 12 }, { kind: "window", startLap: 20, endLap: 35 }, { kind: "probability", p: 0.5 }];
const tracks = ["monza", "monaco", "silverstone", "marina_bay"].filter((t) => params.tracks[t]?.has_dry_data);
let races = 0;
for (const track of tracks) {
  const N = params.tracks[track].total_laps!;
  for (const weather of weathers) {
    const sc: Scenario = { track, driver: g0.driver_id, team: g0.team_id, grid: 4,
      strategy: { stints: [{ compound: "MEDIUM", laps: Math.round(N / 2) }, { compound: "HARD", laps: N - Math.round(N / 2) }] },
      paceMode: "normal", reactToSC: true, weather, sims: 200, seed: 7, sampleUserStrategy: true, applyRules: false };
    const setup = makeSetup(params, sc), prep = prepare(setup);
    const n = setup.cars.length;
    const where = `${track} ${weather.kind}`;
    for (let k = 0; k < 200; k++) {
      const seed = 1000 + k * 7919;
      const r = simulateRace(setup, prep, seed, sc.strategy);
      races++;
      // Positions are a permutation of 1..n, finishers ahead of retirements.
      const pos = r.cars.map((c) => c.pos).sort((a, b) => a - b);
      check(pos.every((p, i) => p === i + 1), `${where} seed ${seed}: positions are not 1..${n}`);
      const lastFinisher = Math.max(0, ...r.cars.filter((c) => !c.dnf).map((c) => c.pos));
      const firstDnf = Math.min(n + 1, ...r.cars.filter((c) => c.dnf).map((c) => c.pos));
      check(lastFinisher < firstDnf, `${where} seed ${seed}: a retirement is classified ahead of a finisher`);
      for (const c of r.cars) {
        // Stints are contiguous and cover the laps the car ran.
        const ran = c.dnf ? c.dnfLap : N;
        check(c.stints[0].from === 1, `${where} seed ${seed}: first stint does not start on lap 1`);
        for (let j = 1; j < c.stints.length; j++)
          check(c.stints[j].from === c.stints[j - 1].to + 1, `${where} seed ${seed}: stints of a car are not contiguous`);
        const last = c.stints[c.stints.length - 1];
        check(!c.dnf ? (last.to === 0 || last.to === N) : true, `${where} seed ${seed}: a finisher's last stint does not reach lap ${N}`);
        check(ran >= 1 && ran <= N, `${where} seed ${seed}: laps run outside 1..${N}`);
        if (!c.dnf) check(Number.isFinite(c.time) && c.time > 0, `${where} seed ${seed}: finisher without a race time`);
        if (weather.kind === "dry") check(c.stints.every((s) => s.compound !== "INTERMEDIATE" && s.compound !== "WET"), `${where}: wet tyres in a dry race`);
      }
      // Finishing order follows race time among finishers.
      const fin = r.cars.filter((c) => !c.dnf).sort((a, b) => a.pos - b.pos);
      for (let j = 1; j < fin.length; j++) check(fin[j].time >= fin[j - 1].time - 1e-6, `${where} seed ${seed}: a finisher is ahead of a faster one`);
    }
    // A fixed seed gives a fixed race.
    const a = simulateRace(setup, prep, 12345, sc.strategy), b = simulateRace(setup, prep, 12345, sc.strategy);
    check(JSON.stringify(a.cars.map((c) => [c.pos, c.time])) === JSON.stringify(b.cars.map((c) => [c.pos, c.time])), `${where}: same seed, different race`);
  }
}
if (failures.length) {
  console.error(`FAILED (${failures.length} shown):\n  ` + failures.join("\n  "));
  process.exit(1);
}
console.log(`invariants hold over ${races.toLocaleString()} simulated races (${tracks.join(", ")}; dry and wet)`);
