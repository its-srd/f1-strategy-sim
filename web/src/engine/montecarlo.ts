// Monte Carlo runner: many races, aggregated into the probabilities and
// charts the site shows, plus the search for the best alternative strategy.

import { POINTS, prepare, simulateRace, GREEN, type RaceResult } from "./race.ts";
import { checkStrategy, enumerateStrategies, expectedTime, makeSetup, strategyLabel, type RaceSetup } from "./setup.ts";
import type { Params, Scenario, Strategy, WetCall } from "./types.ts";

export interface DriverSummary {
  driverId: string; code: string; name: string; teamId: string; teamName: string; isUser: boolean;
  win: number; podium: number; points: number; dnf: number; meanPos: number; expPoints: number;
  posHist: number[];             // share finishing in each position (index 0 = P1), DNF last
  medianGap: number[];           // median gap to leader per lap (from recorded sims)
  carPct: number; carSd: number; carSource: string; skillPct: number; skillSd: number;
}

export interface StrategyEval {
  label: string; strategy: Strategy; sims: number;
  win: number; podium: number; points: number; expPoints: number; meanPos: number; dnf: number;
  medianTime: number | null; expectedTime: number;
  dExpPts?: number; dExpPtsSE?: number;      // vs your strategy on the same races (paired)
  ptsPerSim?: Float32Array;
  parts: { pit: number; tyre: number; traffic: number; held: number; neutral: number; weather: number };
}

export interface MCResult {
  scenario: Scenario; laps: number; trackName: string; sims: number; elapsedMs: number;
  drivers: DriverSummary[];
  chosen: StrategyEval; alternative: StrategyEval | null; candidates: StrategyEval[];
  deltaByLap: { p25: number[]; p50: number[]; p75: number[] } | null;   // chosen - alternative, s (positive = chosen behind)
  representative: { stints: { code: string; stints: RaceResult["cars"][number]["stints"]; pos: number; dnf: boolean }[]; status: number[]; wetness: number[] | null };
  neutralShare: { sc: number; vsc: number; red: number; wet: number };
  wetCallEval: { label: string; yoursExpPts: number; defaultExpPts: number; dExpPts: number; dExpPtsSE: number; dMedianTime: number | null; sims: number } | null;
  warnings: string[];
  userIdx: number;
}

const median = (a: number[]) => { if (!a.length) return NaN; const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const quant = (s: number[], q: number) => s.length ? s[Math.min(s.length - 1, Math.max(0, Math.round(q * (s.length - 1))))] : NaN;

type Progress = (done: number, total: number, phase: string) => void;

function evalStrategy(setup: RaceSetup, prep: ReturnType<typeof prepare>, strat: Strategy, seeds: number[], fallback: Strategy, label = strategyLabel(strat), wetCall?: WetCall): StrategyEval {
  const u = setup.userIdx;
  let win = 0, pod = 0, pts = 0, ep = 0, pos = 0, dnf = 0;
  const times: number[] = [];
  const parts = { pit: 0, tyre: 0, traffic: 0, held: 0, neutral: 0, weather: 0 };
  const ptsPerSim = new Float32Array(seeds.length);
  let j = 0;
  for (const sd of seeds) {
    const r = simulateRace(setup, prep, sd, fallback, { userStrategy: strat, wetCall });
    const c = r.cars[u];
    if (c.pos === 1) win++;
    if (c.pos <= 3) pod++;
    if (c.pos <= 10 && !c.dnf) { pts++; ep += POINTS[c.pos - 1]; ptsPerSim[j] = POINTS[c.pos - 1]; }
    j++;
    pos += c.pos;
    if (c.dnf) dnf++; else times.push(c.time);
    for (const k of Object.keys(parts) as (keyof typeof parts)[]) parts[k] += c.parts[k];
  }
  const n = seeds.length;
  for (const k of Object.keys(parts) as (keyof typeof parts)[]) parts[k] /= n;
  const pacePct = setup.cars[u].carPct + setup.cars[u].skillPct;
  return { label, strategy: strat, sims: n, win: win / n, podium: pod / n, points: pts / n, expPoints: ep / n,
    meanPos: pos / n, dnf: dnf / n, medianTime: times.length ? median(times) : null,
    expectedTime: expectedTime(setup.track, strat, pacePct), parts, ptsPerSim };
}

export function runMonteCarlo(params: Params, sc: Scenario, onProgress: Progress = () => {}): MCResult {
  const t0 = Date.now();
  const setup = makeSetup(params, sc);
  const prep = prepare(setup);
  const T = setup.track, n = setup.cars.length, N = T.laps, u = setup.userIdx;
  const warnings: string[] = [];
  const rules = sc.applyRules !== false;
  const chk = checkStrategy(sc.strategy, T, sc.weather.kind === "window", rules);
  if (!chk.ok) throw new Error(chk.errors.join(" "));
  warnings.push(...chk.warnings);
  if (!prep.strategyPool.length) warnings.push("No observed strategies at this track since 2022: rival cars use the fastest deterministic strategy.");

  // Fallback strategy for rivals with no observed pool: best deterministic.
  const pacePct = setup.cars[u].carPct + setup.cars[u].skillPct;
  const cands = enumerateStrategies(T, 3, 2, rules).map((s) => ({ s, t: expectedTime(T, s, pacePct) })).sort((a, b) => a.t - b.t);
  const fallback = cands[0]?.s ?? sc.strategy;

  // ---- main run
  const REC = Math.min(400, sc.sims);
  const pos = Array.from({ length: n }, () => new Float64Array(n + 1));
  const win = new Float64Array(n), pod = new Float64Array(n), pts = new Float64Array(n), ep = new Float64Array(n), dnf = new Float64Array(n), sumPos = new Float64Array(n);
  const traces: Float32Array[][] = [];
  const userPos: number[] = [];
  let sumStatus = { sc: 0, vsc: 0, red: 0, wet: 0 };
  const seeds: number[] = [];
  let rep: RaceResult | null = null;
  const parts = { pit: 0, tyre: 0, traffic: 0, held: 0, neutral: 0, weather: 0 };
  const times: number[] = [];
  let uWin = 0, uPod = 0, uPts = 0, uEp = 0, uPos = 0, uDnf = 0;
  const recorded: RaceResult[] = [];
  for (let k = 0; k < sc.sims; k++) {
    const seed = (sc.seed * 1000003 + k * 7919) >>> 0;
    seeds.push(seed);
    const r = simulateRace(setup, prep, seed, fallback, { record: k < REC });
    for (let i = 0; i < n; i++) {
      const c = r.cars[i];
      pos[i][c.dnf ? n : c.pos - 1]++;
      sumPos[i] += c.pos;
      if (c.dnf) dnf[i]++;
      if (c.pos === 1 && !c.dnf) win[i]++;
      if (c.pos <= 3 && !c.dnf) pod[i]++;
      if (c.pos <= 10 && !c.dnf) { pts[i]++; ep[i] += POINTS[c.pos - 1]; }
    }
    const c = r.cars[u];
    userPos.push(c.pos);
    if (c.pos === 1 && !c.dnf) uWin++;
    if (c.pos <= 3 && !c.dnf) uPod++;
    if (c.pos <= 10 && !c.dnf) { uPts++; uEp += POINTS[c.pos - 1]; }
    uPos += c.pos; if (c.dnf) uDnf++; else times.push(c.time);
    for (const key of Object.keys(parts) as (keyof typeof parts)[]) parts[key] += c.parts[key];
    let s1 = 0, v1 = 0, r1 = 0;
    for (let L = 1; L <= N; L++) { if (r.status[L] === 1) s1 = 1; if (r.status[L] === 2) v1 = 1; if (r.status[L] === 3) r1 = 1; }
    sumStatus = { sc: sumStatus.sc + s1, vsc: sumStatus.vsc + v1, red: sumStatus.red + r1, wet: sumStatus.wet + (r.wetness ? 1 : 0) };
    if (r.trace) { traces.push(r.trace); recorded.push(r); }
    if (k % 250 === 0) onProgress(k, sc.sims, "Simulating your strategy");
  }
  const S = sc.sims;

  // Representative race: the recorded sim whose user position is the median
  // and whose field order is closest to the mean positions.
  const medPos = median(userPos);
  let best = Infinity;
  for (const r of recorded) {
    if (Math.abs(r.cars[u].pos - medPos) > 0.5) continue;
    let d = 0;
    for (let i = 0; i < n; i++) d += (r.cars[i].pos - sumPos[i] / S) ** 2;
    if (d < best) { best = d; rep = r; }
  }
  rep = rep ?? recorded[0];

  const drivers: DriverSummary[] = setup.cars.map((c, i) => {
    const medianGap: number[] = [];
    for (let L = 1; L <= N; L++) {
      const v = traces.map((tr) => tr[i][L]).filter((x) => Number.isFinite(x));
      medianGap.push(v.length > traces.length / 2 ? median(v) : NaN);
    }
    return { driverId: c.driverId, code: c.code, name: c.name, teamId: c.teamId, teamName: c.teamName, isUser: c.isUser,
      win: win[i] / S, podium: pod[i] / S, points: pts[i] / S, dnf: dnf[i] / S, meanPos: sumPos[i] / S, expPoints: ep[i] / S,
      posHist: Array.from(pos[i], (x) => x / S), medianGap,
      carPct: c.carPct, carSd: c.carSd, carSource: c.carSource, skillPct: c.skillPct, skillSd: c.skillSd };
  });
  drivers.sort((a, b) => b.expPoints - a.expPoints || a.meanPos - b.meanPos);
  for (const key of Object.keys(parts) as (keyof typeof parts)[]) parts[key] /= S;
  const chosen: StrategyEval = { label: strategyLabel(sc.strategy), strategy: sc.strategy, sims: S,
    win: uWin / S, podium: uPod / S, points: uPts / S, expPoints: uEp / S, meanPos: uPos / S, dnf: uDnf / S,
    medianTime: times.length ? median(times) : null, expectedTime: expectedTime(T, sc.strategy, pacePct), parts };

  // ---- alternative search: rank by expected time, then Monte Carlo the top
  // distinct candidates on the same random numbers (paired comparison).
  const ALT = Math.min(1500, S);
  const altSeeds = seeds.slice(0, ALT);
  const chosenLabel = strategyLabel(sc.strategy);
  const picked: Strategy[] = [];
  const byShape = new Set<string>();
  for (const c of cands) {
    const shape = c.s.stints.map((x) => x.compound).join("-");
    if (byShape.has(shape) || strategyLabel(c.s) === chosenLabel) continue;
    byShape.add(shape); picked.push(c.s);
    if (picked.length >= 6) break;
  }
  const candidates: StrategyEval[] = [];
  picked.forEach((s, j) => {
    onProgress(j, picked.length, "Testing alternative strategies");
    candidates.push(evalStrategy(setup, prep, s, altSeeds, fallback));
  });
  const chosenPaired = evalStrategy(setup, prep, sc.strategy, altSeeds, fallback, chosenLabel);
  for (const c of [chosenPaired, ...candidates]) {
    const a = c.ptsPerSim!, b = chosenPaired.ptsPerSim!;
    let m = 0, m2 = 0;
    for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; m += d; m2 += d * d; }
    m /= a.length;
    c.dExpPts = m;
    c.dExpPtsSE = Math.sqrt(Math.max(0, m2 / a.length - m * m) / a.length);
  }
  // W7: your wet-weather call against the model's default call, paired.
  let wetCallEval: MCResult["wetCallEval"] = null;
  const call = sc.wetCall;
  if (sc.weather.kind !== "dry" && call && (call.timing !== 0 || call.interOnly)) {
    const dflt = evalStrategy(setup, prep, sc.strategy, altSeeds, fallback, chosenLabel, { timing: 0, interOnly: false });
    const a = chosenPaired.ptsPerSim!, b = dflt.ptsPerSim!;
    let m = 0, m2 = 0;
    for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; m += d; m2 += d * d; }
    m /= a.length;
    const parts: string[] = [];
    if (call.timing) parts.push(`switch ${Math.abs(call.timing)} lap${Math.abs(call.timing) > 1 ? "s" : ""} ${call.timing < 0 ? "early" : "late"}`);
    if (call.interOnly) parts.push("intermediates only");
    wetCallEval = { label: parts.join(", "), yoursExpPts: chosenPaired.expPoints, defaultExpPts: dflt.expPoints, dExpPts: m,
      dExpPtsSE: Math.sqrt(Math.max(0, m2 / a.length - m * m) / a.length),
      dMedianTime: chosenPaired.medianTime !== null && dflt.medianTime !== null ? chosenPaired.medianTime - dflt.medianTime : null, sims: a.length };
  }
  for (const c of [chosenPaired, ...candidates]) delete c.ptsPerSim;
  candidates.sort((a, b) => b.expPoints - a.expPoints || a.meanPos - b.meanPos);
  const alternative = candidates[0] ?? null;

  // ---- lap-by-lap delta, chosen vs alternative, on paired seeds
  let deltaByLap: MCResult["deltaByLap"] = null;
  if (alternative) {
    const K = Math.min(300, S);
    const per: number[][] = Array.from({ length: N + 1 }, () => []);
    for (let k = 0; k < K; k++) {
      const a = simulateRace(setup, prep, seeds[k], fallback, { record: true, userStrategy: sc.strategy });
      const b = simulateRace(setup, prep, seeds[k], fallback, { record: true, userStrategy: alternative.strategy });
      if (a.cars[u].dnf || b.cars[u].dnf) continue;
      for (let L = 1; L <= N; L++) per[L].push(a.userCum![L] - b.userCum![L]);
    }
    const p25: number[] = [], p50: number[] = [], p75: number[] = [];
    for (let L = 1; L <= N; L++) { const s = per[L].sort((x, y) => x - y); p25.push(quant(s, 0.25)); p50.push(quant(s, 0.5)); p75.push(quant(s, 0.75)); }
    deltaByLap = { p25, p50, p75 };
  }
  void chosenPaired; void GREEN;

  onProgress(1, 1, "Done");
  return {
    scenario: sc, laps: N, trackName: T.name, sims: S, elapsedMs: Date.now() - t0,
    drivers, chosen, alternative, candidates: [chosenPaired, ...candidates], deltaByLap,
    representative: {
      stints: setup.cars.map((c, i) => ({ code: c.code, stints: rep!.cars[i].stints, pos: rep!.cars[i].pos, dnf: rep!.cars[i].dnf })).sort((a, b) => a.pos - b.pos),
      status: Array.from(rep!.status).slice(1, N + 1), wetness: rep!.wetness ? Array.from(rep!.wetness).slice(1, N + 1) : null,
    },
    neutralShare: { sc: sumStatus.sc / S, vsc: sumStatus.vsc / S, red: sumStatus.red / S, wet: sumStatus.wet / S },
    wetCallEval,
    warnings, userIdx: u,
  };
}

export { makeSetup, checkStrategy, enumerateStrategies, expectedTime, strategyLabel };
