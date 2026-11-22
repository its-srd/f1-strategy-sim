// Turn fitted parameters + the user's scenario into a race setup.
// Every number here comes from data/params. Structural rules are labelled
// with their docs/assumptions.md code.

import { DRY, type Compound, type Dry, type Params, type Scenario, type Strategy, type TrackParams } from "./types.ts";

export interface CarSetup {
  idx: number;
  driverId: string; code: string; name: string;
  teamId: string; teamName: string;
  isUser: boolean;
  carPct: number; carSd: number; carSource: string;        // S4, S5
  skillPct: number; skillSd: number;
  corr: number;                                            // posterior corr(car, skill), own seat only (E1)
  qualiGap: number | null;                                 // dry qualifying gap to pole, % (I4), if known
  wetPct: number; wetSd: number;
  dnfProb: number;                                         // R4
}

export interface TrackSetup {
  key: string; name: string; laps: number; base: number;
  offset: Record<Dry, [number, number]>;                   // [mean s, sd s]
  slope: Record<Dry, [number, number]>;
  curve: [number, number]; fuel: [number, number]; fuel2: [number, number]; traffic: [number, number]; sigma: number;
  pit: [number, number];
  scRate: number; vscRate: number; redRate: number;
  overtakeIntercept: number; startRatio: number;
  maxStint: Record<Dry, number>;
  sources: Record<string, string>;
}

export interface RaceSetup {
  track: TrackSetup;
  cars: CarSetup[];
  userIdx: number;
  dnfWetRatio: number;                                     // applied only in races where it rains
  scenario: Scenario;
  params: Params;
}

// Sporting regulations that change legal strategies. These are rules, not
// fitted parameters, so they live here with their source (assumption R6).
export const SPORTING_RULES: Record<string, { minStops: number; note: string }> = {
  monaco: { minStops: 2, note: "Monaco: at least two pit stops (FIA rule introduced for 2025; every planned strategy in the 2025 data has two or more stops)." },
};

export function trackSetup(p: Params, key: string): TrackSetup {
  const t = p.tracks[key];
  if (!t || !t.has_dry_data || !t.pace || !t.base_lap) throw new Error(`No dry-race data for ${key}`);
  const g = p.global;
  const est = (name: string): [number, number] => {
    const e = t.pace![name];
    return [e.mean_s ?? 0, e.sd_s ?? 0];
  };
  const pooledStint = g.max_stint_pooled;
  const maxStint = {} as Record<Dry, number>;
  for (const c of DRY) maxStint[c] = t.max_stint?.[c] ?? pooledStint[c];
  const vscEra = g.safety_car.VSC.era_2026.apply_2026_ratio ? g.safety_car.VSC.era_2026.ratio : 1;
  const scEra = g.safety_car.SC.era_2026.apply_2026_ratio ? g.safety_car.SC.era_2026.ratio : 1;
  const redEra = g.safety_car.RED.era_2026.apply_2026_ratio ? g.safety_car.RED.era_2026.ratio : 1;
  const sources: Record<string, string> = {};
  for (const [k, v] of Object.entries(t.pace)) sources[k] = v.source;
  return {
    key, name: t.name, laps: t.total_laps ?? 50, base: t.base_lap.base_s,
    offset: { SOFT: est("offset_SOFT"), MEDIUM: [0, 0], HARD: est("offset_HARD") },
    slope: { SOFT: est("slope_SOFT"), MEDIUM: est("slope_MEDIUM"), HARD: est("slope_HARD") },
    curve: est("curve"), fuel: est("fuel"), fuel2: t.pace.fuel2 ? est("fuel2") : [0, 0], traffic: est("traffic"),
    sigma: t.pace.sigma.mean_s ?? 0.4,
    pit: t.pit ? [t.pit.green_loss_s, t.pit.sd] : [g.pooled.pit_green_loss_s, g.pooled.pit_sd_s],
    scRate: (t.sc_rate?.rate_per_race ?? g.safety_car.SC.pooled_rate_dry) * scEra,
    vscRate: (t.vsc_rate?.rate_per_race ?? g.safety_car.VSC.pooled_rate_dry) * vscEra,
    redRate: (t.red_rate?.rate_per_race ?? g.safety_car.RED.pooled_rate_dry) * redEra,
    overtakeIntercept: t.overtake?.intercept ?? 0,
    startRatio: t.start?.ratio ?? 1,
    maxStint, sources,
  };
}

/** The 2026 grid with the user's driver placed in the chosen team (S4).
 *  The user's driver takes the second seat of the chosen team. If the driver
 *  already races for another 2026 team, the displaced driver takes that seat
 *  (a swap), so the grid keeps 22 cars and every car keeps a driver. */
export function buildField(p: Params, sc: Scenario): CarSetup[] {
  const grid = (sc.gridEntries ?? p.grid.grid).map((g) => ({ ...g }));
  const userOnGrid = grid.find((g) => g.driver_id === sc.driver);
  const teamSeats = grid.filter((g) => g.team_id === sc.team);
  if (!userOnGrid || userOnGrid.team_id !== sc.team) {
    // Replace the team's lower-placed driver in the latest race (grid order = finishing order).
    const others = teamSeats.filter((g) => g.driver_id !== sc.driver);
    const target = others[others.length - 1] ?? teamSeats[0];
    if (userOnGrid) {
      // swap seats
      const displaced = target.driver_id;
      const dEntry = { ...target };
      target.driver_id = sc.driver; target.code = userOnGrid.code; target.name = userOnGrid.name;
      userOnGrid.driver_id = displaced; userOnGrid.code = dEntry.code; userOnGrid.name = dEntry.name;
    } else {
      const d = p.drivers[sc.driver];
      target.driver_id = sc.driver; target.code = d.code; target.name = d.name;
    }
  }
  const t = p.tracks[sc.track];
  const dnfTrack = t.dnf?.ratio ?? 1;
  return grid.map((g, idx) => {
    const team = p.teams[g.team_id];
    const bt = team.by_track[sc.track];
    const d = p.drivers[g.driver_id];
    const teamRate = team.dnf?.rate ?? p.global.dnf.target_season_rate;
    // Car and skill are estimated jointly from teammate comparisons, so for a
    // driver in the seat they actually raced in 2026 they must be drawn with
    // their posterior correlation. A driver moved to another car: independent.
    const ownSeat = d?.last_season === 2026 && d?.last_team === g.team_id;
    const cc = d?.car_corr_2026 ?? {};
    const vals = Object.values(cc);
    const corr = !ownSeat ? 0 : (cc[sc.track] ?? (vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0));
    return {
      idx, driverId: g.driver_id, code: d?.code ?? g.code, name: d?.name ?? g.name,
      teamId: g.team_id, teamName: team.name, isUser: g.driver_id === sc.driver,
      carPct: bt ? bt.car_pct : team.season_mean_pct,
      carSd: bt ? bt.sd : team.season_sd_pct,
      carSource: bt ? `2026 ${t.name}` : "2026 season mean (track not yet raced in 2026)",
      skillPct: d?.skill_pct ?? 0, skillSd: d?.sd_pct ?? p.global.skill_model.sigma0_pct, corr,
      qualiGap: g.quali_gap_pct === undefined || g.quali_wet || g.quali_gap_pct > (p.global.quali_effect?.quali_gap_clip_pct ?? Infinity) ? null : g.quali_gap_pct,
      wetPct: d?.wet_extra_pct ?? 0, wetSd: d?.wet_extra_sd ?? p.global.wet.driver_wet_skill.between_driver_sd_pct,
      dnfProb: Math.min(0.95, teamRate * dnfTrack),
    };
  });
}

export function makeSetup(p: Params, sc: Scenario): RaceSetup {
  const track = trackSetup(p, sc.track);
  const cars = buildField(p, sc);
  const userIdx = cars.findIndex((c) => c.isUser);
  return { track, cars, userIdx, scenario: sc, params: p, dnfWetRatio: p.global.dnf.wet_rate / p.global.dnf.dry_rate };
}

// ------------------------------------------------------------ wet pace (W1, W3)

export interface WetModel { iDry: number; iCross: number; wetA: number; wetB: number; rho: number }

export function wetModel(p: Params): WetModel {
  const w = p.global.wet;
  return {
    iDry: w.dynamics.stationary_dry_level,
    iCross: w.switch_crossover.inter_ratio,
    wetA: w.wet_minus_inter.intercept,
    wetB: w.wet_minus_inter.slope_per_inter_ratio,
    rho: w.dynamics.rho,
  };
}

/** Lap-time ratio (vs dry pace) of each compound family at wetness i
 *  (i = inter lap-time ratio). */
export function compoundRatio(m: WetModel, c: Compound, i: number): number {
  if (c === "INTERMEDIATE") return Math.max(i, m.iDry);
  if (c === "WET") return Math.max(i, m.iDry) + m.wetA + m.wetB * Math.max(i, m.iDry);
  if (i <= m.iDry) return 1;
  return 1 + (i - m.iDry) * (m.iCross - 1) / (m.iCross - m.iDry);
}

export function bestFamily(m: WetModel, i: number, interOnly = false): Compound {
  const s = compoundRatio(m, "MEDIUM", i), it = compoundRatio(m, "INTERMEDIATE", i), w = interOnly ? Infinity : compoundRatio(m, "WET", i);
  if (s <= it && s <= w) return "MEDIUM";
  return it <= w ? "INTERMEDIATE" : "WET";
}

/** Invert "best tyre ratio" -> wetness i (monotone, bisection). */
export function wetnessFromBest(m: WetModel, best: number): number {
  const f = (i: number) => Math.min(compoundRatio(m, "MEDIUM", i), compoundRatio(m, "INTERMEDIATE", i), compoundRatio(m, "WET", i));
  if (best <= 1) return m.iDry;
  let lo = m.iDry, hi = 2.5;
  for (let k = 0; k < 50; k++) { const mid = (lo + hi) / 2; if (f(mid) < best) lo = mid; else hi = mid; }
  return (lo + hi) / 2;
}

// ------------------------------------------------------------ strategies

export function stopLaps(s: Strategy): number[] {
  const out: number[] = [];
  let lap = 0;
  for (let i = 0; i < s.stints.length - 1; i++) { lap += s.stints[i].laps; out.push(lap); }
  return out;
}

export interface StrategyCheck { ok: boolean; errors: string[]; warnings: string[] }

export function checkStrategy(s: Strategy, t: TrackSetup, wet: boolean, applyRules = true): StrategyCheck {
  const errors: string[] = [], warnings: string[] = [];
  const rule = SPORTING_RULES[t.key];
  if (applyRules && rule && s.stints.length - 1 < rule.minStops) errors.push(rule.note);
  const total = s.stints.reduce((a, b) => a + b.laps, 0);
  if (total !== t.laps) errors.push(`Stints add up to ${total} laps; the race is ${t.laps}.`);
  if (s.stints.some((x) => x.laps < 1)) errors.push("Every stint needs at least 1 lap.");
  if (!wet && new Set(s.stints.map((x) => x.compound)).size < 2)
    errors.push("Dry-race rule: at least two different dry compounds must be used.");
  s.stints.forEach((x, i) => {
    const cap = t.maxStint[x.compound];
    if (x.laps > cap) warnings.push(`Stint ${i + 1} (${x.compound}, ${x.laps} laps) is longer than any ${x.compound} stint observed here (${cap}). Wear beyond that is extrapolated linearly (M2).`);
  });
  return { ok: errors.length === 0, errors, warnings };
}

/** Expected (noise-free, no traffic, no neutralisation) race time of one car
 *  for a strategy. Used to rank candidates before Monte Carlo. */
export function expectedTime(t: TrackSetup, s: Strategy, pacePct: number, paceShift = 0, wearShift = 0): number {
  let time = 0, lap = 0;
  const base = t.base * (1 + (pacePct + paceShift) / 100);
  for (let k = 0; k < s.stints.length; k++) {
    const st = s.stints[k];
    const off = t.offset[st.compound][0], sl = t.slope[st.compound][0] + wearShift, cu = t.curve[0];
    for (let a = 1; a <= st.laps; a++) {
      lap++;
      time += base + off + sl * a + cu * a * a + t.fuel[0] * lap + t.fuel2[0] * lap * lap;
    }
    if (k < s.stints.length - 1) time += t.pit[0];
  }
  return time;
}

export const MIN_STINT = 3;

/** Enumerate legal dry strategies (1-3 stops) within stint caps. */
export function enumerateStrategies(t: TrackSetup, maxStops = 3, step3 = 2, applyRules = true): Strategy[] {
  const N = t.laps, out: Strategy[] = [];
  const minStops = applyRules ? SPORTING_RULES[t.key]?.minStops ?? 1 : 1;
  if (maxStops < minStops) maxStops = minStops;
  const seqs = (n: number): Dry[][] => {
    if (n === 0) return [[]];
    const r: Dry[][] = [];
    for (const s of seqs(n - 1)) for (const c of DRY) r.push([...s, c]);
    return r;
  };
  // Candidate stints are at least MIN_STINT laps: shorter "stints" in the
  // data are damage or puncture stops (A1), not planned strategy.
  const fits = (c: Dry, l: number) => l >= MIN_STINT && l <= t.maxStint[c];
  for (let stops = minStops; stops <= maxStops; stops++) {
    const cs = seqs(stops + 1).filter((q) => new Set(q).size >= 2);
    const step = stops >= 3 ? step3 : 1;
    const rec = (k: number, used: number, acc: number[], comp: Dry[]) => {
      if (k === stops) {
        const last = N - used;
        if (fits(comp[stops], last)) out.push({ stints: comp.map((c, i) => ({ compound: c, laps: i < stops ? acc[i] : last })) });
        return;
      }
      for (let l = step; used + l < N; l += step) {
        if (!fits(comp[k], l)) { if (l > t.maxStint[comp[k]]) break; continue; }
        rec(k + 1, used + l, [...acc, l], comp);
      }
    };
    for (const comp of cs) rec(0, 0, [], comp);
  }
  return out;
}

export function strategyLabel(s: Strategy): string {
  const L = (c: Dry) => c[0];
  return s.stints.map((x) => `${L(x.compound)}${x.laps}`).join("-");
}
