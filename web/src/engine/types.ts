// Shapes of the fitted parameter files in data/params (copied to public/params).
// Only the fields the engine and UI read are typed; the files carry more.

export type Dry = "SOFT" | "MEDIUM" | "HARD";
export type Compound = Dry | "INTERMEDIATE" | "WET";
export const DRY: Dry[] = ["SOFT", "MEDIUM", "HARD"];

export interface Est { mean: number | null; sd: number | null; mean_s: number | null; sd_s: number | null; n_races: number; source: "track" | "pooled"; last_year?: number }

export interface TrackParams {
  name: string; circuit_name: string; country: string;
  on_2026_calendar: boolean; round_2026: number | null; has_dry_data: boolean;
  total_laps: number | null; dry_races: number; mean_track_temp: number | null;
  base_lap: { base_s: number; from_year: number; scaled_by_years: number[]; source: string } | null;
  pace: Record<string, Est> | null;
  pit: { green_loss_s: number; sd: number; n_stops: number; years: number[] } | null;
  sc_rate: { rate_per_race: number; sd: number; n_races: number; observed: number } | null;
  vsc_rate: { rate_per_race: number; sd: number; n_races: number; observed: number } | null;
  red_rate: { rate_per_race: number; sd: number; n_races: number; observed: number } | null;
  overtake: { intercept: number; se: number; pairs: number; passes: number; races: number; raw_pass_rate_within_1s: number | null } | null;
  start: { ratio: number; n_races: number; n: number } | null;
  dnf: { rate: number; ratio: number; starts: number } | null;
  max_stint: Partial<Record<Dry, number>> | null;
  strategies: { from_year: number; n: number; races: number; stop_count_share: Record<string, number>;
    sequences: { race: string; compounds: Dry[]; stop_fracs: number[]; grid?: number | null }[] } | null;
}

export interface TeamParams {
  name: string; season_mean_pct: number; season_sd_pct: number; race_to_race_sd_pct: number; n_races: number;
  by_track: Record<string, { car_pct: number; sd: number; race: string; source: string }>;
  dnf: { rate: number; ratio_to_season: number; dnf: number; starts: number } | null;
}

export interface DriverParams {
  name: string; code: string; last_team: string; last_season: number; skill_pct: number; sd_pct: number;
  years_since_last: number; career_dry_races_fitted: number; first_season: number;
  wet_extra_pct: number; wet_extra_sd: number; wet_races: number;
  car_corr_2026?: Record<string, number>; no_dry_data?: boolean;
  history: Record<string, { skill_pct: number; sd: number; races: number }>;
}

export interface Quantiles { [q: string]: number }

export interface SCType {
  pooled_rate_dry: number; wet_rate_ratio: number; variance_to_mean: number; between_track_variation_detected: boolean;
  era_2026: { ratio: number; ratio_ci95: [number, number]; apply_2026_ratio: boolean; ratio_averaged?: number; p_rules_changed_rate?: number };
  lap1_share: number; lap_frac_hist: number[]; lap_frac_bins: number[]; duration_laps_pmf: Record<string, number>;
  n_deployments: number; prior_gamma_a: number; prior_gamma_b: number;
}

export interface GlobalParams {
  pooled: { pace: Record<string, { mean_pct: number; sd_pct: number; omega_pct_per_year: number; n_tracks: number; breaks: number[] }>;
            pit_green_loss_s: number; pit_sd_s: number };
  pit: { stop_residual_quantiles_s: Quantiles; neutralised_ratio: Record<"sc" | "vsc", { median_ratio: number; n_stops: number }>; n_green_stops: number };
  safety_car: Record<"SC" | "VSC" | "RED", SCType>;
  neutralised_pace: Record<"SC" | "VSC", { median_ratio: number; n_laps: number }>;
  dnf: { lap1_share: number; lap_frac_hist: number[]; lap_frac_bins: number[]; wet_rate: number; dry_rate: number;
         target_season_rate: number; n_dnf: number; n_starts: number };
  start: { pmf_by_grid: Record<string, { pmf: Record<string, number>; n: number }>; pooled_sd: number; n_starts: number;
    season?: { ratio: number; raw_ratio: number; n_starts: number; weight: number; season: number } };   // I6
  overtaking: { coef: Record<"pace_adv" | "gap" | "pace_adv_x_gap", { beta: number; se: number }>;
                eras: Record<string, { offset: number; se: number; pairs: number }>; current_era?: string; current_era_offset?: number; window_s: number; n_pairs: number; n_passes: number };
  wet: {
    switch_crossover: { inter_ratio: number; ci95: [number, number]; n_races: number };
    wet_minus_inter: { intercept: number; slope_per_inter_ratio: number; crossover_inter_ratio: number; n_laps: number; n_races: number };
    dynamics: { c: number; rho: number; stationary_dry_level: number; n_lap_pairs: number; n_races: number; resid_sd: number };
    trajectories: Record<string, [number, number, boolean][]>;
    driver_wet_skill: { between_driver_sd_pct: number; pairs: number; races: number };
    // W10: each driver's switch lap minus the field's median, laps -> count
    switch_timing?: { offsets: Record<string, number>; offset_sd_laps: number; n_transitions: number; n_driver_switches: number;
      places_gained_per_lap_later: number; places_gained_per_lap_later_ci95: [number, number] };
    n_wet_races: number;
  };
  gaps: { lap1_gap_quantiles_s: Quantiles; leader_lap1_loss_s: number; restart_gap_quantiles_s: Quantiles; held_gap_quantiles_s: Quantiles };
  pace_mode: { wear_change_per_pace_pct: number; ci95: [number, number]; mode_pace_sd_pct: number; supported: boolean; n_pairs: number };
  max_stint_pooled: Record<Dry, number>;
  // A2b: probability a car pits when an SC/VSC starts (model/sc_reaction.py)
  sc_reaction?: { coef: Record<"intercept" | "wear" | "left" | "owes" | "vsc", { beta: number; se: number }>; n_cars: number; share_pitted: number };
  skill_model: { tau_pct: number; omega_pct_per_year: number; sigma0_pct: number; n_obs: number };
  quali_effect?: QualiEffect | null;
  grid_effect?: GridEffect;
}

export interface GridEntry { driver_id: string; code: string; name: string; team_id: string; number: string; quali_gap_pct?: number; quali_wet?: boolean;
  quali_pos?: number;     // qualifying position before penalties (I2 uses it instead of the grid slot)
  pit_lane?: boolean }    // starts from the pit lane: no I2 pace shift

export interface QualiEffect { weight_prior: number; weight_quali: number; se: number[]; form_sd_after_quali_pct: number; form_sd_prior_only_pct: number; quali_gap_clip_pct: number; n_driver_races: number }
export interface GridEffect { pct_per_grid_place: number; se: number; form_sd_before_grid_pct: number; form_sd_after_grid_pct: number; n_driver_races: number }
// I2 / I4 refitted on the priors the engine has before a race (model/calibrate_pace.py)
export interface PaceBlend { quali: QualiEffect; grid: GridEffect; seasons: number[]; n_driver_races: number }

export interface Calibration { pace_spread_scale: number; pace_spread_scale_without_quali?: number; strategy_choices: number; chosen_on: string; scores: Record<string, unknown>;
  wet_driver_effects?: boolean;    // W1b: off since the wet-race backtest
  rival_switch_spread?: boolean;   // W10: off since the wet-race backtest
  pace_blend?: PaceBlend;          // used instead of global quali_effect / grid_effect
  pace_blend_forward?: Record<string, PaceBlend>;   // per scored season, fitted on earlier seasons only
  pass_logit_shift?: number;      // O3: added to the pass model's log-odds (calibrated on a backtest season)
  // I5: this season's race-day form spread relative to the long-run value,
  // measured on its earlier races (model/calibrate_pace.py)
  season_form?: { current: { ratio: number; sd: number; season_sd: number; n: number; season: number }; per_race: Record<string, { ratio: number }> };
  season_form_ratio?: number }    // backtests: the ratio as of the race being predicted

export interface Params {
  tracks: Record<string, TrackParams>;
  teams: Record<string, TeamParams>;
  drivers: Record<string, DriverParams>;
  global: GlobalParams;
  grid: { grid: GridEntry[]; example_quali?: { race: string; wet: boolean; rows: { code: string; grid: number; best_lap_s: number | null }[] } | null; calendar: { round: number; circuit_id: string; race_name: string; date: string }[]; from_race: string };
  calibration?: Calibration;
  meta: { generated_utc: string; target_season?: number; data_through?: { year: number; round: number }; races_in_data: number; dry_races_fitted: number; clean_laps: number; first_race: [number, string]; last_race: [number, string] };
}

// ------------------------------------------------------------ user inputs

export type PaceMode = "conserve" | "normal" | "push";

export interface Stint { compound: Dry; laps: number }   // laps in this stint
export interface Strategy { stints: Stint[] }

export type Weather =
  | { kind: "dry" }
  | { kind: "probability"; p: number }                  // chance of a rain spell during the race
  | { kind: "window"; startLap: number; endLap: number }
  // Hindsight replay for backtests: the real best-tyre lap-time ratio per lap
  // (index 0 = lap 1), as model/backtest.py measured it. Not offered in the UI.
  | { kind: "trace"; best: number[] };

/** Your car's call in the rain: switch `timing` laps before (negative) or
 *  after (positive) the lap the model's crossover says, and optionally never
 *  use full wets. Rivals always use the default call. */
export interface WetCall { timing: number; interOnly: boolean }

export interface Scenario {
  track: string;
  driver: string;               // driver id
  team: string;                 // team id whose car the driver races
  grid: number;                 // 1-based grid slot
  strategy: Strategy;
  paceMode: PaceMode;
  reactToSC: boolean;           // pit early under SC/VSC when a stop is due soon
  applyRules?: boolean;         // apply track sporting rules (setup.ts SPORTING_RULES); default true
  listedGrid?: boolean;         // start in the listed grid order (backtest, or after qualifying)
  gridEntries?: GridEntry[];    // after qualifying: the real grid, in order, with qualifying gaps
  actualResult?: { code: string; pos: number | null; grid: number; status: string }[];  // shown next to the prediction; ignored by the engine
  raceLabel?: string;
  sampleUserStrategy?: boolean; // backtest: the 'user' car also follows observed strategies
  fixedPlans?: Record<string, Strategy>;  // backtest: these drivers run exactly these strategies
  passShift?: number;       // backtest experiments: overrides calibration.pass_logit_shift
  statusTrace?: number[];   // backtest: the race's real track status per lap (index 0 = lap 1; 0 green, 1 SC, 2 VSC, 3 red)
  gridImpliesPace?: boolean;    // read the grid as a qualifying result: it shifts weekend pace (I2)
  wetCall?: WetCall;            // your car's wet-weather call (W7); default: switch at the crossover
  paceSpread?: number;          // multiplies car / skill / form spread (I3); default: params.calibration
  strategyChoices?: number;     // rivals draw this many nearby strategies and run the quickest (A1c); default: params.calibration
  weather: Weather;
  sims: number;
  seed: number;
}
