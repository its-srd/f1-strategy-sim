// Headless check of the engine: node --experimental-strip-types scripts/engine-check.ts [track] [sims]
import { readFileSync } from "node:fs";
import { runMonteCarlo } from "../src/engine/montecarlo.ts";
import type { Params, Scenario } from "../src/engine/types.ts";
const dir = new URL("../public/params/", import.meta.url);
const load = (f: string) => JSON.parse(readFileSync(new URL(f, dir), "utf8"));
const params: Params = { tracks: load("tracks.json"), teams: load("teams.json"), drivers: load("drivers.json"),
  global: load("global.json"), grid: load("grid_2026.json"), meta: load("meta.json") };
const track = process.argv[2] ?? "monza", sims = Number(process.argv[3] ?? 2000);
const N = params.tracks[track].total_laps!;
const sc: Scenario = { track, driver: "max_verstappen", team: "red_bull", grid: 4,
  strategy: { stints: [{ compound: "MEDIUM", laps: Math.round(N * 0.45) }, { compound: "HARD", laps: N - Math.round(N * 0.45) }] },
  paceMode: "normal", reactToSC: true, weather: process.argv[4] === "rain" ? { kind: "window", startLap: 15, endLap: 28 } : { kind: "dry" }, sims, seed: 42 };
const r = runMonteCarlo(params, sc);
console.log(`${r.trackName}: ${r.sims} sims in ${r.elapsedMs} ms; SC in ${(100 * r.neutralShare.sc).toFixed(0)}%, VSC ${(100 * r.neutralShare.vsc).toFixed(0)}%, red ${(100 * r.neutralShare.red).toFixed(0)}%, wet ${(100 * r.neutralShare.wet).toFixed(0)}%`);
console.log("driver  team            win%  pod%  pts%  dnf%  meanPos  expPts");
for (const d of r.drivers) console.log(`${d.code.padEnd(6)}${d.isUser ? "*" : " "} ${d.teamName.padEnd(16)} ${(100 * d.win).toFixed(1).padStart(5)} ${(100 * d.podium).toFixed(1).padStart(5)} ${(100 * d.points).toFixed(1).padStart(5)} ${(100 * d.dnf).toFixed(1).padStart(5)} ${d.meanPos.toFixed(2).padStart(7)} ${d.expPoints.toFixed(2).padStart(7)}`);
const fmt = (e: typeof r.chosen) => `${e.label.padEnd(14)} expPts ${e.expPoints.toFixed(2)} win ${(100 * e.win).toFixed(1)}% pod ${(100 * e.podium).toFixed(1)}% meanPos ${e.meanPos.toFixed(2)} stops=${e.strategy.stints.length - 1} pit ${e.parts.pit.toFixed(1)}s tyre ${e.parts.tyre.toFixed(1)}s held ${e.parts.held.toFixed(1)}s traffic ${e.parts.traffic.toFixed(1)}s`;
console.log("chosen  ", fmt(r.chosen));
for (const c of r.candidates) console.log("cand    ", fmt(c));
console.log("delta p50 every 10 laps", r.deltaByLap?.p50.filter((_, i) => i % 10 === 9).map((x) => x.toFixed(1)).join(" "));
console.log("warnings", r.warnings);
console.log("rep stints", r.representative.stints.slice(0, 5).map((s) => `${s.code}:${s.stints.map((x) => `${x.compound[0]}${x.from}-${x.to}`).join(",")}`).join("  "));
