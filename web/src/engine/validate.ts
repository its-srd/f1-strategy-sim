// Checks that the parameter files written by Python have every value the
// engine reads, as a finite number where a number is expected. The engine
// falls back to defaults in a few places (`?? 1`), so a renamed key would
// otherwise change results without any error (review section 5).
import { DRY, type Params } from "./types.ts";

const PACE_KEYS = ["fuel", "traffic", "curve", "sigma", "offset_SOFT", "offset_HARD", ...DRY.map((c) => `slope_${c}`)];

export function validateParams(p: Params): string[] {
  const problems: string[] = [];
  const num = (v: unknown, where: string, min = -Infinity) => {
    if (typeof v !== "number" || !Number.isFinite(v)) problems.push(`${where}: missing or not a number`);
    else if (v < min) problems.push(`${where}: ${v} is below ${min}`);
  };
  const obj = (v: unknown, where: string) => {
    if (!v || typeof v !== "object") { problems.push(`${where}: missing`); return false; }
    return true;
  };

  const g = p.global;
  if (obj(g, "global")) {
    num(g.skill_model?.tau_pct, "global.skill_model.tau_pct", 0);
    num(g.skill_model?.sigma0_pct, "global.skill_model.sigma0_pct", 0);
    for (const k of ["pace_adv", "gap", "pace_adv_x_gap"] as const) num(g.overtaking?.coef?.[k]?.beta, `global.overtaking.coef.${k}.beta`);
    num(g.overtaking?.window_s, "global.overtaking.window_s", 0);
    num(g.pooled?.pit_green_loss_s, "global.pooled.pit_green_loss_s", 0);
    num(g.pooled?.pit_sd_s, "global.pooled.pit_sd_s", 0);
    num(g.pit?.neutralised_ratio?.sc?.median_ratio, "global.pit.neutralised_ratio.sc.median_ratio", 0);
    num(g.pit?.neutralised_ratio?.vsc?.median_ratio, "global.pit.neutralised_ratio.vsc.median_ratio", 0);
    for (const t of ["SC", "VSC", "RED"] as const) {
      num(g.safety_car?.[t]?.pooled_rate_dry, `global.safety_car.${t}.pooled_rate_dry`, 0);
      num(g.safety_car?.[t]?.wet_rate_ratio, `global.safety_car.${t}.wet_rate_ratio`, 0);
      obj(g.safety_car?.[t]?.era_2026, `global.safety_car.${t}.era_2026`);
    }
    num(g.neutralised_pace?.SC?.median_ratio, "global.neutralised_pace.SC.median_ratio", 0);
    num(g.neutralised_pace?.VSC?.median_ratio, "global.neutralised_pace.VSC.median_ratio", 0);
    num(g.dnf?.lap1_share, "global.dnf.lap1_share", 0);
    num(g.dnf?.target_season_rate, "global.dnf.target_season_rate", 0);
    for (const c of DRY) num(g.max_stint_pooled?.[c], `global.max_stint_pooled.${c}`, 1);
    num(g.wet?.switch_crossover?.inter_ratio, "global.wet.switch_crossover.inter_ratio", 1);
    num(g.wet?.dynamics?.rho, "global.wet.dynamics.rho", 0);
    num(g.wet?.dynamics?.stationary_dry_level, "global.wet.dynamics.stationary_dry_level", 1);
    num(g.pace_mode?.mode_pace_sd_pct, "global.pace_mode.mode_pace_sd_pct", 0);
    if (g.sc_reaction?.coef) for (const k of ["intercept", "wear", "left", "owes", "vsc"] as const)
      num(g.sc_reaction.coef[k]?.beta, `global.sc_reaction.coef.${k}.beta`);
  }

  for (const [key, t] of Object.entries(p.tracks ?? {})) {
    if (!t.has_dry_data) continue;
    num(t.total_laps, `tracks.${key}.total_laps`, 1);
    num(t.base_lap?.base_s, `tracks.${key}.base_lap.base_s`, 1);
    for (const k of PACE_KEYS) {
      num(t.pace?.[k]?.mean_s, `tracks.${key}.pace.${k}.mean_s`);
      if (k !== "sigma") num(t.pace?.[k]?.sd_s, `tracks.${key}.pace.${k}.sd_s`, 0);
    }
  }
  for (const [key, t] of Object.entries(p.teams ?? {})) {
    num(t.season_mean_pct, `teams.${key}.season_mean_pct`);
    num(t.season_sd_pct, `teams.${key}.season_sd_pct`, 0);
    for (const [tk, b] of Object.entries(t.by_track ?? {})) {
      num(b.car_pct, `teams.${key}.by_track.${tk}.car_pct`);
      num(b.sd, `teams.${key}.by_track.${tk}.sd`, 0);
    }
  }
  for (const [key, d] of Object.entries(p.drivers ?? {})) {
    num(d.skill_pct, `drivers.${key}.skill_pct`);
    num(d.sd_pct, `drivers.${key}.sd_pct`, 0);
  }
  for (const e of p.grid?.grid ?? []) {
    if (!p.teams?.[e.team_id]) problems.push(`grid: team ${e.team_id} (${e.code}) has no parameters`);
  }
  if (p.calibration) {
    num(p.calibration.pace_spread_scale, "calibration.pace_spread_scale", 0);
    num(p.calibration.strategy_choices, "calibration.strategy_choices", 1);
  }
  return problems;
}
