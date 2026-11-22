// One simulated race, lap by lap. Every probability and magnitude comes from
// data/params via RaceSetup. Structural rules cite docs/assumptions.md.

import { Rng, compileHist, compilePmf, compileQuantiles, sampleHistC, samplePmf, sampleQ, type Pmf, type QTable } from "./rng.ts";
import { bestFamily, compoundRatio, expectedTime, stopLaps, wetModel, wetnessFromBest, type RaceSetup, type WetModel } from "./setup.ts";
import { DRY, type Compound, type Dry, type Strategy } from "./types.ts";

export const POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1];
export const GREEN = 0, SC = 1, VSC = 2, RED = 3;

export interface CarResult {
  pos: number;              // 1-based classified position (DNF cars after finishers)
  dnf: boolean; dnfLap: number;
  time: number;             // total race time (finishers)
  stints: { compound: Compound; from: number; to: number }[];
  parts: { pit: number; tyre: number; traffic: number; held: number; neutral: number; weather: number; stops: number };
}

export interface RaceResult {
  cars: CarResult[];
  status: Uint8Array;                   // per lap (index 1..N)
  wetness: Float32Array | null;         // inter ratio per lap, null if dry
  trace?: Float32Array[];               // per car: gap to leader at end of each lap
  userCum?: Float64Array;               // user's cumulative time per lap
}

export interface SimOptions { record?: boolean; userStrategy?: Strategy; }

// ------------------------------------------------------------ preprocessing

export interface Prepared {
  wm: WetModel;
  wetSegments: number[][];              // observed wetness sequences (W4)
  strategyPool: { compounds: Dry[]; stop_fracs: number[]; grid?: number | null }[];
  q: { pitResid: QTable; lap1Gap: QTable; restartGap: QTable; held: QTable };
  startPmf: Pmf[];                      // by grid slot (index 0 = P1)
  ev: Record<"SC" | "VSC" | "RED", { lap1: number; hist: ReturnType<typeof compileHist>; dur: Pmf }>;
  dnfHist: ReturnType<typeof compileHist>;
}

export function prepare(s: RaceSetup): Prepared {
  const wm = wetModel(s.params);
  const segs: number[][] = [];
  for (const traj of Object.values(s.params.global.wet.trajectories)) {
    const iv = traj.map(([, best]) => wetnessFromBest(wm, best));
    let cur: number[] = [], bestSeg: number[] = [];
    for (const v of iv) {
      if (v > wm.iDry + 0.01) cur.push(v); else { if (cur.length > bestSeg.length) bestSeg = cur; cur = []; }
    }
    if (cur.length > bestSeg.length) bestSeg = cur;
    if (bestSeg.length >= 2) segs.push(bestSeg);
  }
  const t = s.params.tracks[s.track.key];
  const pool = (t.strategies?.sequences ?? []).filter((q) => {
    // keep sequences that respect the stint caps at this race length
    const stops = q.stop_fracs.map((f) => Math.round(f * s.track.laps));
    const ends = [...stops, s.track.laps];
    let prev = 0;
    return ends.every((e, i) => { const ok = e - prev >= 1 && e - prev <= s.track.maxStint[q.compounds[i]]; prev = e; return ok; });
  });
  const G = s.params.global;
  const startPmf: Pmf[] = [];
  for (let g = 1; g <= s.cars.length; g++) startPmf.push(compilePmf(G.start.pmf_by_grid[String(g)]?.pmf ?? { "0": 1 }));
  const ev = {} as Prepared["ev"];
  for (const k of ["SC", "VSC", "RED"] as const) {
    const p = G.safety_car[k];
    ev[k] = { lap1: p.lap1_share, hist: compileHist(p.lap_frac_hist, p.lap_frac_bins), dur: compilePmf(p.duration_laps_pmf) };
  }
  return { wm, wetSegments: segs, strategyPool: pool,
    q: { pitResid: compileQuantiles(G.pit.stop_residual_quantiles_s), lap1Gap: compileQuantiles(G.gaps.lap1_gap_quantiles_s),
         restartGap: compileQuantiles(G.gaps.restart_gap_quantiles_s), held: compileQuantiles(G.gaps.held_gap_quantiles_s) },
    startPmf, ev, dnfHist: compileHist(G.dnf.lap_frac_hist, G.dnf.lap_frac_bins) };
}

// ------------------------------------------------------------ helpers

function wetnessPath(s: RaceSetup, prep: Prepared, rng: Rng): Float32Array | null {
  const w = s.scenario.weather, N = s.track.laps, wm = prep.wm;
  if (w.kind === "dry" || prep.wetSegments.length === 0) return null;
  let start: number, seg: number[], len: number;
  if (w.kind === "probability") {
    if (rng.u() >= w.p) return null;
    seg = prep.wetSegments[rng.int(prep.wetSegments.length)];
    start = 2 + rng.int(Math.max(1, N - 3));
    len = Math.min(seg.length, N - start + 1);
  } else {
    start = Math.max(1, Math.min(N, w.startLap));
    len = Math.max(1, Math.min(N, w.endLap) - start + 1);
    seg = prep.wetSegments[rng.int(prep.wetSegments.length)];
  }
  const path = new Float32Array(N + 2).fill(wm.iDry);
  const stretch = w.kind === "window";
  for (let k = 0; k < len; k++) {
    // W4: a user window stretches the observed sequence over the window; a
    // random spell replays it lap for lap and is cut off at the flag.
    const x = !stretch ? k : len === 1 ? 0 : (k / (len - 1)) * (seg.length - 1);
    const i0 = Math.floor(x), i1 = Math.min(seg.length - 1, i0 + 1), f = x - i0;
    path[start + k] = seg[i0] * (1 - f) + seg[i1] * f;
  }
  for (let L = start + len; L <= N; L++) {
    const v = wm.iDry + wm.rho * (path[L - 1] - wm.iDry);
    path[L] = v < wm.iDry + 0.005 ? wm.iDry : v;
  }
  return path;
}

function neutralisations(s: RaceSetup, prep: Prepared, rng: Rng, wet: boolean): Uint8Array {
  const N = s.track.laps, g = s.params.global.safety_car;
  const status = new Uint8Array(N + 2);
  const wetMul = (t: "SC" | "VSC" | "RED") => (wet ? g[t].wet_rate_ratio : 1);
  const events: { type: number; lap: number; dur: number }[] = [];
  const add = (type: number, key: "SC" | "VSC" | "RED", rate: number) => {
    const n = rng.poisson(rate * wetMul(key));
    for (let k = 0; k < n; k++) {
      const p = prep.ev[key];
      const lap = rng.u() < p.lap1 ? 1 : Math.max(2, Math.ceil(sampleHistC(p.hist, rng) * N));
      const dur = Math.max(1, samplePmf(p.dur, rng));
      events.push({ type, lap, dur });
    }
  };
  add(SC, "SC", s.track.scRate);
  add(VSC, "VSC", s.track.vscRate);
  add(RED, "RED", s.track.redRate);
  events.sort((a, b) => a.lap - b.lap);
  for (const e of events) {
    if (status[e.lap] !== GREEN) continue;                 // overlapping: keep the first
    if (e.type === RED) {
      status[e.lap] = RED;                                // suspension lap, then SC restart lap
      if (e.lap + 1 <= N && status[e.lap + 1] === GREEN) status[e.lap + 1] = SC;
      continue;
    }
    for (let L = e.lap; L < e.lap + e.dur && L <= N; L++) if (status[L] === GREEN) status[L] = e.type;
  }
  return status;
}

interface Plan { compounds: Compound[]; stops: number[] }   // stops = lap numbers ending each stint but the last

// A1b: teams choose strategies by where they start. A car samples from the
// strategies run by drivers who started within GRID_WINDOW places of its slot,
// widening the window until at least MIN_POOL examples are available.
const GRID_WINDOW = 2, MIN_POOL = 5;

function samplePlan(s: RaceSetup, prep: Prepared, rng: Rng, fallback: Strategy, slot: number): Plan {
  const N = s.track.laps;
  if (prep.strategyPool.length) {
    let pool = prep.strategyPool;
    const withGrid = pool.filter((q) => q.grid);
    if (withGrid.length >= MIN_POOL) {
      for (let w = GRID_WINDOW; w <= s.cars.length; w += 1) {
        const near = withGrid.filter((q) => Math.abs(q.grid! - slot) <= w);
        if (near.length >= MIN_POOL) { pool = near; break; }
      }
    }
    // A1c: draw `choices` strategies from the nearby pool and run the one
    // with the lowest expected race time under this year's tyre model (teams
    // do not repeat a plan that the current tyres make slow).
    const choices = Math.max(1, s.scenario.strategyChoices ?? s.params.calibration?.strategy_choices ?? 1);
    let best: Plan | null = null, bestT = Infinity;
    for (let c = 0; c < choices; c++) {
      const q = pool[rng.int(pool.length)];
      const stops = q.stop_fracs.map((f) => Math.min(N - 1, Math.max(1, Math.round(f * N))));
      const plan = { compounds: [...q.compounds], stops };
      if (choices === 1) return plan;
      const ends = [...stops, N];
      const strat = { stints: q.compounds.map((comp, j) => ({ compound: comp, laps: Math.max(1, ends[j] - (j ? ends[j - 1] : 0)) })) };
      const tt = expectedTime(s.track, strat, 0);
      if (tt < bestT) { bestT = tt; best = plan; }
    }
    return best!;
  }
  return { compounds: fallback.stints.map((x) => x.compound), stops: stopLaps(fallback) };
}

const sigmoid = (x: number) => 1 / (1 + Math.exp(-x));

// ------------------------------------------------------------ the race

export function simulateRace(s: RaceSetup, prep: Prepared, seed: number, fallback: Strategy, opt: SimOptions = {}): RaceResult {
  const rng = new Rng(seed);
  const T = s.track, P = s.params, G = P.global, N = T.laps, n = s.cars.length, wm = prep.wm;
  const userStrategy = opt.userStrategy ?? s.scenario.strategy;

  // Parameter uncertainty, one draw per race (M6, S4).
  const offset = {} as Record<Dry, number>, slope = {} as Record<Dry, number>;
  for (const c of DRY) { offset[c] = rng.normal(T.offset[c][0], T.offset[c][1]); slope[c] = rng.normal(T.slope[c][0], T.slope[c][1]); }
  const curve = rng.normal(T.curve[0], T.curve[1]);
  const fuel = rng.normal(T.fuel[0], T.fuel[1]);
  const fuel2 = rng.normal(T.fuel2[0], T.fuel2[1]);
  const traffic = rng.normal(T.traffic[0], T.traffic[1]);
  const pitMean = rng.normal(T.pit[0], T.pit[1]);
  const pm = G.pace_mode, mode = s.scenario.paceMode;
  const modePct = !pm.supported || mode === "normal" ? 0 : (mode === "push" ? -1 : 1) * pm.mode_pace_sd_pct;
  const modeWear = (pm.wear_change_per_pace_pct * modePct) / 100 * T.base;     // PM1 (s per lap of age)
  const ov = G.overtaking, era = ov.current_era_offset ?? ov.eras["2026"]?.offset ?? 0;
  const scLap = G.neutralised_pace.SC.median_ratio, vscLap = G.neutralised_pace.VSC.median_ratio;
  const pitSC = G.pit.neutralised_ratio.sc.median_ratio, pitVSC = G.pit.neutralised_ratio.vsc.median_ratio;

  const pace = new Float64Array(n), wetX = new Float64Array(n);
  const gridFx = s.scenario.gridImpliesPace && G.grid_effect ? G.grid_effect : null;
  // Knowing the grid explains part of race-day form: remove that share.
  // I3: the backtest showed the summed pace spread is too wide (outcomes
  // fell inside the 80% range 95% of the time); one scale, picked on the 2025
  // practice races, narrows car, skill and form spread together.
  // I4: with real (dry) qualifying gaps for most of the field, race pace is
  // the fitted blend of season form and the qualifying gap, and the form draw
  // uses the smaller spread left once qualifying is known.
  const qe = s.scenario.gridImpliesPace ? G.quali_effect ?? null : null;
  const withQ = s.cars.filter((c) => c.qualiGap !== null);
  const useQuali = !!qe && withQ.length >= n / 2;
  const qMean = useQuali ? withQ.reduce((a, c) => a + c.qualiGap!, 0) / withQ.length : 0;
  const k = s.scenario.paceSpread
    ?? (useQuali ? P.calibration?.pace_spread_scale : P.calibration?.pace_spread_scale_without_quali) ?? 1;
  const tau0 = gridFx
    ? Math.sqrt(Math.max(G.skill_model.tau_pct ** 2 - (gridFx.form_sd_before_grid_pct ** 2 - gridFx.form_sd_after_grid_pct ** 2), 0.25 * G.skill_model.tau_pct ** 2))
    : G.skill_model.tau_pct;
  const tau = k * tau0;
  const prior = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const c = s.cars[i];
    // E1: car and skill drawn jointly (posterior correlation).
    const z1 = rng.normal(), z2 = rng.normal();
    const car = c.carPct + k * c.carSd * z1;
    const skill = c.skillPct + k * c.skillSd * (c.corr * z1 + Math.sqrt(Math.max(0, 1 - c.corr * c.corr)) * z2);
    prior[i] = car + skill;
    wetX[i] = rng.normal(c.wetPct, c.wetSd);
  }
  const priorMean = prior.reduce((a, b) => a + b, 0) / n;
  for (let i = 0; i < n; i++) {
    const c = s.cars[i];
    if (useQuali && c.qualiGap !== null)
      pace[i] = qe!.weight_prior * (prior[i] - priorMean) + qe!.weight_quali * (c.qualiGap - qMean) + rng.normal(0, k * qe!.form_sd_after_quali_pct);
    else pace[i] = prior[i] - priorMean + rng.normal(0, tau);      // plus the race-to-race form draw
    if (c.isUser) pace[i] += modePct;
  }

  const wetness = wetnessPath(s, prep, rng);
  const status = neutralisations(s, prep, rng, wetness !== null);

  // Retirements (R4).
  const dnfLap = new Int32Array(n).fill(0);
  const dnfMul = wetness ? s.dnfWetRatio : 1;
  for (let i = 0; i < n; i++) if (rng.u() < Math.min(0.95, s.cars[i].dnfProb * dnfMul))
    dnfLap[i] = rng.u() < G.dnf.lap1_share ? 1 : Math.max(1, Math.ceil(sampleHistC(prep.dnfHist, rng) * N));

  // Grid: user at the chosen slot, rivals ordered by sampled race pace
  // (qualifying is not modelled).
  let gridOrder: number[];
  if (s.scenario.listedGrid) gridOrder = [...Array(n).keys()];          // cars are built in grid order
  else {
    const others = [...Array(n).keys()].filter((i) => !s.cars[i].isUser).sort((a, b) => pace[a] - pace[b]);
    gridOrder = others.slice();
    if (s.userIdx >= 0) gridOrder.splice(Math.min(Math.max(0, s.scenario.grid - 1), n - 1), 0, s.userIdx);
  }

  const slotOf = new Int32Array(n);
  gridOrder.forEach((i, slot) => { slotOf[i] = slot; });
  // Plans (A1): user = chosen strategy, rivals = strategies run here since 2022.
  const plans: Plan[] = s.cars.map((c) => {
    const fixed = s.scenario.fixedPlans?.[c.driverId];
    if (fixed) return { compounds: fixed.stints.map((x) => x.compound), stops: stopLaps(fixed) };
    if (c.isUser && !s.scenario.sampleUserStrategy)
      return { compounds: userStrategy.stints.map((x) => x.compound), stops: stopLaps(userStrategy) };
    return samplePlan(s, prep, rng, fallback, slotOf[s.cars.indexOf(c)] + 1);
  });

  // I2: a grid read as a qualifying result says something about pace this
  // weekend. Each place behind the slot the car's expected pace would give
  // costs the fitted pct_per_grid_place of lap time (and each place ahead
  // gains it). The race-day form draw above already used the smaller
  // post-grid spread (see formSd).
  if (gridFx && !useQuali) {
    const prior = s.cars.map((c) => c.carPct + c.skillPct);
    const expRank = new Float64Array(n);
    [...Array(n).keys()].sort((a, b) => prior[a] - prior[b]).forEach((i, r) => { expRank[i] = r; });
    gridOrder.forEach((i, slot) => { pace[i] += gridFx.pct_per_grid_place * (slot - expRank[i]); });
  }

  // State
  const cum = new Float64Array(n), running = new Uint8Array(n).fill(1);
  const comp: Compound[] = plans.map((p) => p.compounds[0]);
  const age = new Float64Array(n), stintIdx = new Int32Array(n), lapsDone = new Int32Array(n);
  const stints: CarResult["stints"][] = plans.map((p) => [{ compound: p.compounds[0], from: 1, to: 0 }]);
  const parts = s.cars.map(() => ({ pit: 0, tyre: 0, traffic: 0, held: 0, neutral: 0, weather: 0, stops: 0 }));
  const gapAhead = new Float64Array(n).fill(99);
  const trace = opt.record ? s.cars.map(() => new Float32Array(N + 1)) : undefined;
  const userCum = opt.record ? new Float64Array(N + 1) : undefined;
  const E = new Float64Array(n), lapT = new Float64Array(n), pitThis = new Uint8Array(n), nextComp: (Compound | null)[] = new Array(n).fill(null);
  let usedWet = false;
  const order: number[] = [], ord: number[] = [], tent = new Float64Array(n);

  const familyOf = (c: Compound): Compound => (c === "INTERMEDIATE" || c === "WET" ? c : "MEDIUM");

  const changeTo = (i: number, c: Compound, lap: number) => {
    stints[i][stints[i].length - 1].to = lap;
    stints[i].push({ compound: c, from: lap + 1, to: 0 });
    comp[i] = c; age[i] = 0;
  };

  for (let L = 1; L <= N; L++) {
    const st = status[L];
    const wv = wetness ? wetness[L] : wm.iDry;
    const isWet = wetness !== null && wv > wm.iDry + 1e-6;
    if (isWet) usedWet = true;

    // --- planned and reactive pit decisions for the end of this lap
    for (let i = 0; i < n; i++) {
      pitThis[i] = 0; nextComp[i] = null;
      if (!running[i] || st === RED) continue;
      const p = plans[i];
      const k = stintIdx[i];
      // weather switch at the crossover (W1): change family if another is faster
      if (wetness) {
        const best = bestFamily(wm, wv);
        const prevBest = bestFamily(wm, wetness[Math.max(1, L - 1)]);
        if (familyOf(comp[i]) !== best && best === prevBest && L < N) {
          pitThis[i] = 1;
          if (best === "MEDIUM") {
            // Back to slicks (W5): the dry compound with the lowest expected
            // time for the remaining laps; one extra stop only if no
            // compound's observed stint cap covers the distance.
            const R = N - L;
            const cost = (c: Dry, len: number) => offset[c] * len + slope[c] * len * (len + 1) / 2 + curve * len * (len + 1) * (2 * len + 1) / 6;
            let bestC: Dry = "MEDIUM", bestT = Infinity;
            for (const c of DRY) if (T.maxStint[c] >= R && cost(c, R) < bestT) { bestT = cost(c, R); bestC = c; }
            if (bestT < Infinity) { p.compounds = ["X" as Dry, bestC]; p.stops = []; }
            else {
              const h = Math.ceil(R / 2);
              let c1: Dry = "HARD", c2: Dry = "HARD", tt = Infinity;
              for (const a of DRY) for (const b of DRY) if (T.maxStint[a] >= h && T.maxStint[b] >= R - h) {
                const v = cost(a, h) + cost(b, R - h) + T.pit[0];
                if (v < tt) { tt = v; c1 = a; c2 = b; }
              }
              bestC = c1; p.compounds = ["X" as Dry, c1, c2]; p.stops = [L + h];
            }
            // re-index the plan so stint 1 is the new slick stint
            p.compounds = p.compounds.slice(1); stintIdx[i] = 0;
            nextComp[i] = bestC;
          } else nextComp[i] = best;
          continue;
        }
      }
      if (familyOf(comp[i]) !== "MEDIUM") continue;      // on wet tyres: wait for the crossover
      if (k < p.stops.length && p.stops[k] === L) {
        // W6: teams see rain coming a few laps out; do not fit fresh slicks
        // if the crossover to wet tyres is within the next 3 laps.
        let rainSoon = false;
        if (wetness) for (let j = 1; j <= 3 && L + j <= N; j++) if (bestFamily(wm, wetness[L + j]) !== "MEDIUM") rainSoon = true;
        if (rainSoon) { p.stops[k] = L + 1; continue; }
        pitThis[i] = 1; nextComp[i] = p.compounds[k + 1]; continue;
      }
      // SC / VSC reaction (A2): pit now if the next planned stop is close
      const react = s.cars[i].isUser ? s.scenario.reactToSC : true;
      if (react && (st === SC || st === VSC) && k < p.stops.length && L < N - 1) {
        const due = p.stops[k];
        const stintLen = due - (k === 0 ? 0 : p.stops[k - 1]);
        if (due - L <= Math.max(3, Math.round(0.35 * stintLen))) {
          // shift the remaining plan forward by the laps saved
          const shift = due - L;
          for (let m = k; m < p.stops.length; m++) p.stops[m] = Math.max(L + 1, p.stops[m] - shift);
          p.stops[k] = L;
          pitThis[i] = 1; nextComp[i] = p.compounds[k + 1];
        }
      }
    }

    // --- expected and actual lap times
    for (let i = 0; i < n; i++) {
      if (!running[i]) continue;
      age[i] += 1;
      const c = comp[i];
      const dryBase = T.base * (1 + pace[i] / 100) + fuel * L + fuel2 * L * L;
      let e: number, tyre = 0;
      if (c === "INTERMEDIATE" || c === "WET") {
        e = dryBase * compoundRatio(wm, c, wv) * (1 + wetX[i] / 100);
      } else {
        const a = age[i];
        const extraWear = s.cars[i].isUser ? modeWear : 0;
        tyre = offset[c] + (slope[c] + extraWear) * a + curve * a * a;
        e = (dryBase + tyre) * (isWet ? compoundRatio(wm, c, wv) * (1 + wetX[i] / 100) : 1);
      }
      E[i] = e;
      let t = e + rng.normal(0, T.sigma * (isWet ? compoundRatio(wm, c, wv) : 1));
      if (L > 1 && st === GREEN && gapAhead[i] < 1.0) { t += traffic; parts[i].traffic += traffic; }   // F7
      parts[i].tyre += tyre;
      if (isWet) parts[i].weather += e - dryBase - tyre;
      if (st === SC || st === RED) { const x = E[i] * scLap; parts[i].neutral += x - t; t = x; }
      else if (st === VSC) { const x = t * vscLap; parts[i].neutral += x - t; t = x; }
      if (pitThis[i]) {
        const resid = sampleQ(prep.q.pitResid, rng);
        const loss = (pitMean + resid) * (st === SC || st === RED ? pitSC : st === VSC ? pitVSC : 1);
        t += Math.max(0, loss); parts[i].pit += Math.max(0, loss); parts[i].stops++;
      }
      lapT[i] = t;
    }

    // --- positions
    order.length = 0;
    for (let i = 0; i < n; i++) if (running[i]) order.push(i);
    if (L === 1) {
      // Start (R5): position change by grid slot, spread scaled per track.
      const startPos = new Map<number, number>();
      gridOrder.forEach((i, g) => {
        const ch = Math.round(samplePmf(prep.startPmf[g], rng) * T.startRatio);
        startPos.set(i, g + 1 + ch + rng.u() * 0.5);
      });
      order.sort((a, b) => startPos.get(a)! - startPos.get(b)!);
      let tAcc = 0;
      order.forEach((i, k) => {
        if (k === 0) tAcc = lapT[i] + G.gaps.leader_lap1_loss_s;
        else tAcc += sampleQ(prep.q.lap1Gap, rng, 0.05);
        // pit on lap 1 (rare) still costs its loss on top of the queue position
        cum[i] = tAcc + (pitThis[i] ? lapT[i] - E[i] : 0);
      });
    } else {
      order.sort((a, b) => cum[a] - cum[b]);
      tent.fill(0);
      for (const i of order) tent[i] = cum[i] + lapT[i];
      if (st === GREEN) {
        for (let k = 1; k < order.length; k++) {
          const b = order[k], a = order[k - 1];
          const gap = cum[b] - cum[a];
          if (pitThis[a] || pitThis[b] || gap >= ov.window_s) continue;     // pit cycles: order by time
          const adv = E[a] - E[b];
          const pPass = sigmoid(T.overtakeIntercept + era + ov.coef.pace_adv.beta * adv + ov.coef.gap.beta * gap + ov.coef.pace_adv_x_gap.beta * adv * gap);
          if (rng.u() < pPass) {
            if (tent[b] >= tent[a]) tent[b] = tent[a] - 0.05;                 // pass completed (O1)
          } else {
            const held = sampleQ(prep.q.held, rng, 0.05);
            if (tent[b] < tent[a] + held) { parts[b].held += tent[a] + held - tent[b]; tent[b] = tent[a] + held; }
          }
        }
      } else {
        // Neutralised: no overtaking on track. Cars that stay out keep their
        // order; a car that pits drops back by its actual time (it can lose
        // places). Under SC / red the field then runs as a queue behind the
        // leader, compressed every lap at the empirical restart gaps (G2).
        const queue = st === SC || st === RED;
        let lastStay = -1;
        for (const b of order) {
          if (pitThis[b]) continue;
          if (lastStay >= 0 && tent[b] < tent[lastStay] + 0.2) tent[b] = tent[lastStay] + 0.2;
          lastStay = b;
        }
        order.sort((a, b) => tent[a] - tent[b]);
        if (queue) {
          for (let k = 1; k < order.length; k++) {
            const b = order[k], a = order[k - 1];
            const target = tent[a] + sampleQ(prep.q.restartGap, rng, 0.05);
            parts[b].neutral += target - tent[b];
            tent[b] = target;
          }
        }
        if (st === RED) {
          // R3: free tyre change for every car on slicks. A car with a stop
          // left uses it now; a car without one fits a fresh set of the same
          // compound.
          for (const i of order) {
            if (familyOf(comp[i]) !== "MEDIUM") continue;
            const p = plans[i], k = stintIdx[i];
            if (k < p.stops.length) {
              changeTo(i, p.compounds[k + 1], L); stintIdx[i]++;
              const shift = p.stops[k] - L;
              for (let m = k + 1; m < p.stops.length; m++) p.stops[m] = Math.max(L + 1, p.stops[m] - shift);
            } else changeTo(i, comp[i], L);
          }
        }
      }
      for (const i of order) cum[i] = tent[i];
    }

    // --- tyre changes, retirements, bookkeeping
    for (let i = 0; i < n; i++) {
      if (!running[i]) continue;
      lapsDone[i] = L;
      if (pitThis[i] && nextComp[i]) {
        const wasPlanned = familyOf(comp[i]) === "MEDIUM" && familyOf(nextComp[i]!) === "MEDIUM";
        changeTo(i, nextComp[i]!, L);
        if (wasPlanned) stintIdx[i]++;
      }
      if (dnfLap[i] === L) { running[i] = 0; }
    }
    ord.length = 0;
    for (let i = 0; i < n; i++) if (running[i]) ord.push(i);
    ord.sort((a, b) => cum[a] - cum[b]);
    for (let k = 0; k < ord.length; k++) gapAhead[ord[k]] = k === 0 ? 99 : cum[ord[k]] - cum[ord[k - 1]];
    if (trace) {
      const lead = ord.length ? cum[ord[0]] : 0;
      for (let i = 0; i < n; i++) trace[i][L] = running[i] || dnfLap[i] === 0 ? cum[i] - lead : NaN;
      if (userCum && s.userIdx >= 0) userCum[L] = cum[s.userIdx];
    }
  }

  // Classification: finishers by time, then retirements by laps completed.
  const idx = [...Array(n).keys()];
  idx.sort((a, b) => {
    const fa = dnfLap[a] === 0, fb = dnfLap[b] === 0;
    if (fa !== fb) return fa ? -1 : 1;
    if (!fa) return lapsDone[b] - lapsDone[a] || cum[a] - cum[b];
    return cum[a] - cum[b];
  });
  const cars: CarResult[] = new Array(n);
  idx.forEach((i, k) => {
    stints[i][stints[i].length - 1].to = lapsDone[i];
    cars[i] = { pos: k + 1, dnf: dnfLap[i] !== 0, dnfLap: dnfLap[i], time: cum[i], stints: stints[i], parts: parts[i] };
  });
  void usedWet;
  return { cars, status, wetness, trace, userCum };
}
