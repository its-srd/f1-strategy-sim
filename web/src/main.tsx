import { render } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import "./styles.css";
import type { MCResult } from "./engine/montecarlo.ts";
import { SPORTING_RULES, checkStrategy, enumerateStrategies, expectedTime, strategyLabel, trackSetup } from "./engine/setup.ts";
import { DRY, type Dry, type PaceMode, type Params, type Scenario, type Strategy, type Weather } from "./engine/types.ts";
import { validateParams } from "./engine/validate.ts";
import { BandChart, COMPOUND_COLOR, COMPOUND_LETTER, Heat, LineChart, PairedBars, StintMap, type Series } from "./ui/charts.tsx";
import { renderMarkdown } from "./ui/markdown.tsx";
import { ExplainPanel } from "./ui/explain.tsx";
import { QualiPanel, fetchRaceGrid, parseQuali, type GridFetch, type QualiParse } from "./ui/quali.tsx";

const FILES = ["tracks", "teams", "drivers", "global", "grid_2026", "meta"] as const;
const pct = (x: number, d = 1) => `${(100 * x).toFixed(d)}%`;
const sgn = (x: number, d = 2) => `${x > 0 ? "+" : ""}${x.toFixed(d)}`;

async function loadParams(): Promise<Params> {
  const base = new URL("params/", document.baseURI);
  const got = await Promise.all(FILES.map((f) => fetch(new URL(`${f}.json`, base)).then((r) => { if (!r.ok) throw new Error(`params/${f}.json: ${r.status}`); return r.json(); })));
  const [tracks, teams, drivers, global, grid, meta] = got;
  // Backtest calibration (pace spread, rival strategy choice); optional.
  const calibration = await fetch(new URL("calibration.json", base)).then((r) => (r.ok ? r.json() : undefined)).catch(() => undefined);
  return { tracks, teams, drivers, global, grid, meta, calibration };
}

function bestDeterministic(p: Params, track: string, pacePct: number): Strategy | null {
  try {
    const t = trackSetup(p, track);
    let best: Strategy | null = null, bt = Infinity;
    for (const s of enumerateStrategies(t, 2, 2, true)) { const v = expectedTime(t, s, pacePct); if (v < bt) { bt = v; best = s; } }
    return best;
  } catch { return null; }
}

function mostCommon(p: Params, track: string): Strategy | null {
  const t = p.tracks[track], N = t.total_laps ?? 0;
  const seqs = t.strategies?.sequences ?? [];
  if (!seqs.length || !N) return null;
  const by = new Map<string, number[][]>();
  for (const s of seqs) { const k = s.compounds.join("-"); by.set(k, [...(by.get(k) ?? []), s.stop_fracs]); }
  const [key, fr] = [...by.entries()].sort((a, b) => b[1].length - a[1].length)[0];
  const comps = key.split("-") as Dry[];
  const med = comps.slice(0, -1).map((_, i) => { const v = fr.map((f) => f[i]).sort((a, b) => a - b); return v[v.length >> 1]; });
  const stops = med.map((f) => Math.round(f * N));
  const stints = comps.map((c, i) => ({ compound: c, laps: (i < stops.length ? stops[i] : N) - (i ? stops[i - 1] : 0) }));
  return stints.every((x) => x.laps > 0) ? { stints } : null;
}

/** Keep an after-qualifying scenario in step with the real grid. The driver
 *  races the car they qualified. `slot` (a what-if) moves only that driver;
 *  everyone else keeps their real order, and the driver keeps their real
 *  qualifying gap, so the what-if changes track position, not pace. */
function withQuali(s: Scenario, q: QualiParse, slot: number | null): Scenario {
  if (!s.listedGrid) return s;
  let entries = q.entries;
  const real = entries.findIndex((e) => e.driver_id === s.driver);
  if (real >= 0 && slot && slot - 1 !== real) {
    const me = entries[real];
    entries = entries.filter((_, i) => i !== real);
    entries.splice(Math.min(slot - 1, entries.length), 0, me);
  }
  const at = entries.findIndex((e) => e.driver_id === s.driver);
  return { ...s, gridImpliesPace: true, gridEntries: entries.length ? entries : undefined,
    grid: at >= 0 ? at + 1 : s.grid, team: at >= 0 ? entries[at].team_id : s.team };
}

type SetScenario = (u: Scenario | ((prev: Scenario) => Scenario)) => void;

// ------------------------------------------------------------ app

function App() {
  const [params, setParams] = useState<Params | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [paramProblems, setParamProblems] = useState<string[]>([]);
  const [page, setPage] = useState<"sim" | "model" | "record">("sim");
  const [sc, setSc] = useState<Scenario | null>(null);
  const [result, setResult] = useState<MCResult | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number; phase: string } | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  const worker = useRef<Worker | null>(null);
  const runId = useRef(0);

  useEffect(() => {
    loadParams().then((p) => {
      setParams(p);
      const problems = validateParams(p);
      if (problems.length) { console.warn("parameter problems", problems); setParamProblems(problems); }
      const today = new Date().toISOString().slice(0, 10);
      const next = p.grid.calendar.find((c) => c.date >= today && p.tracks[c.circuit_id]?.has_dry_data)
        ?? p.grid.calendar.find((c) => p.tracks[c.circuit_id]?.has_dry_data)!;
      const drv = p.grid.grid[0];
      const track = next.circuit_id;
      const pace = p.teams[drv.team_id].season_mean_pct + p.drivers[drv.driver_id].skill_pct;
      setSc({ track, driver: drv.driver_id, team: drv.team_id, grid: 3, strategy: bestDeterministic(p, track, pace) ?? { stints: [] },
        paceMode: "normal", reactToSC: true, weather: { kind: "dry" }, sims: 10000, seed: 2026 });
      const w = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
      w.postMessage({ type: "params", params: p });
      w.onmessage = (e) => {
        const m = e.data;
        if (m.id !== runId.current) return;
        if (m.type === "progress") setProgress({ done: m.done, total: m.total, phase: m.phase });
        if (m.type === "result") { setResult(m.result); setRunning(false); setProgress(null); }
        if (m.type === "error") { setRunErr(m.error); setRunning(false); setProgress(null); }
      };
      worker.current = w;
    }).catch((e) => setLoadErr(String(e)));
  }, []);

  const run = () => {
    if (!sc || !worker.current) return;
    runId.current++;
    setRunning(true); setRunErr(null);
    worker.current.postMessage({ type: "run", id: runId.current, scenario: sc });
  };

  if (loadErr) return <div class="empty">Could not load fitted parameters: {loadErr}<br />Run <code>npm run sync-params</code> after fitting.</div>;
  if (!params || !sc) return <div class="empty">Loading fitted parameters…</div>;
  return (
    <>
      <header class="topbar">
        <h1>F1 Strategy Simulator</h1>
        <span class="stamp">Model fitted on {params.meta.races_in_data} races, {params.meta.first_race[0]}–{params.meta.last_race[0]} ({params.meta.last_race[1]}) · {params.meta.clean_laps.toLocaleString()} clean laps · fitted {params.meta.generated_utc.slice(0, 10)}</span>
        <nav>
          <button class={`tab ${page === "sim" ? "on" : ""}`} onClick={() => setPage("sim")}>Simulator</button>
          <button class={`tab ${page === "record" ? "on" : ""}`} onClick={() => setPage("record")}>Track record</button>
          <button class={`tab ${page === "model" ? "on" : ""}`} onClick={() => setPage("model")}>Model &amp; assumptions</button>
        </nav>
      </header>
      {page === "model" ? <DocPage file="assumptions.md" /> : page === "record" ? <DocPage file="live_record.md" then="backtest.md" /> : (
        <div class="layout">
          <Controls p={params} sc={sc} setSc={(u) => setSc((prev) => (typeof u === "function" ? u(prev!) : u))} onRun={run} running={running} progress={progress} err={runErr} />
          <main class="main">
            {paramProblems.length > 0 && <div class="warn" style={{ marginBottom: "10px" }}>The parameter files have {paramProblems.length} problem{paramProblems.length > 1 ? "s" : ""} (first: {paramProblems[0]}); results may use defaults. Refit with <code>./scripts/update.sh</code>.</div>}
            {result ? <Results p={params} r={result} /> : <div class="empty">Set up a scenario and press <b>Simulate</b>.<br /><br />The output is a set of probabilities from {sc.sims.toLocaleString()} simulated races. It is never a single prediction.</div>}
          </main>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------ controls

function Controls(props: { p: Params; sc: Scenario; setSc: SetScenario; onRun: () => void; running: boolean; progress: { done: number; total: number; phase: string } | null; err: string | null }) {
  const { p, sc, setSc } = props;
  const t = p.tracks[sc.track];
  const N = t.total_laps ?? 0;
  const tracks = Object.entries(p.tracks).sort((a, b) => (a[1].round_2026 ?? 99) - (b[1].round_2026 ?? 99) || a[1].name.localeCompare(b[1].name));
  const gridIds = new Set(p.grid.grid.map((g) => g.driver_id));
  const drivers = Object.entries(p.drivers).sort((a, b) => a[1].name.localeCompare(b[1].name));
  const teams = Object.entries(p.teams).sort((a, b) => a[1].season_mean_pct - b[1].season_mean_pct);
  const userPace = p.teams[sc.team].season_mean_pct + (p.drivers[sc.driver]?.skill_pct ?? 0);
  const ts = useMemo(() => { try { return trackSetup(p, sc.track); } catch { return null; } }, [sc.track]);
  const check = ts ? checkStrategy(sc.strategy, ts, sc.weather.kind === "window", sc.applyRules !== false) : null;
  const rule = SPORTING_RULES[sc.track];
  const stops = sc.strategy.stints.length - 1;
  const ends: number[] = [];
  sc.strategy.stints.reduce((acc, s) => { acc += s.laps; ends.push(acc); return acc; }, 0);

  const upd = (patch: Partial<Scenario>) => setSc(withQuali({ ...sc, ...patch }, parsed, slotChoice));

  // After-qualifying mode: the real qualifying result of the selected 2026
  // race is fetched automatically; it sets everyone's start position and
  // gives the engine this weekend's qualifying gaps.
  const after = !!sc.listedGrid;
  const [qText, setQText] = useState("");
  const [qWet, setQWet] = useState(false);
  const [slotChoice, setSlotChoice] = useState<number | null>(null);
  const [manual, setManual] = useState(false);
  const [qStatus, setQStatus] = useState<{ kind: "idle" | "loading" | "loaded" | "missing" | "error" | "notcal"; msg?: string; info?: GridFetch }>({ kind: "idle" });
  const parsed = useMemo(() => parseQuali(qText, p, qWet, qStatus.info), [qText, qWet, p, qStatus.info]);
  const inGrid = parsed.entries.some((e) => e.driver_id === sc.driver);
  const realSlot = parsed.entries.findIndex((e) => e.driver_id === sc.driver) + 1;
  const qualified = qStatus.info?.qualiPos[p.drivers[sc.driver]?.code ?? ""];
  const afterBlock = after && (!parsed.entries.length || parsed.errors.length > 0 || !inGrid);
  const season = Number(p.grid.calendar[0]?.date.slice(0, 4) ?? p.meta.target_season ?? 2026);
  const modelSeason = p.meta.target_season ?? season;
  const req = useRef(0);
  useEffect(() => {
    if (!after) return;
    const id = ++req.current;
    const apply = (text: string, status: typeof qStatus) => {
      if (id !== req.current) return;                  // a newer request won
      setQText(text); setQWet(false); setSlotChoice(null); setQStatus(status);
      setSc((prev) => ({ ...withQuali(prev, parseQuali(text, p, false, status.info), null),
        actualResult: status.info?.actual ?? undefined, raceLabel: status.info?.race }));
    };
    const cal = p.grid.calendar.find((c) => c.circuit_id === sc.track);
    const round = t.on_2026_calendar ? t.round_2026 : null;
    if (!round || !cal) { apply("", { kind: "notcal" }); return; }
    setQStatus({ kind: "loading" });
    fetchRaceGrid(season, round, cal.date)
      .then((r) => (r ? apply(r.text, { kind: "loaded", msg: r.race, info: r }) : apply("", { kind: "missing" })))
      .catch((e) => apply("", { kind: "error", msg: String(e.message ?? e) }));
  }, [after, sc.track]);
  const setTrack = (k: string) => {
    const s = bestDeterministic(p, k, userPace) ?? { stints: [] };
    upd({ track: k, strategy: s, weather: sc.weather.kind === "window" ? { kind: "dry" } : sc.weather });
  };
  const setStops = (n: number) => {
    const comps = sc.strategy.stints.map((x) => x.compound);
    const cs: Dry[] = Array.from({ length: n + 1 }, (_, i) => comps[i] ?? (i % 2 ? "HARD" : "MEDIUM"));
    const len = Math.floor(N / (n + 1));
    upd({ strategy: { stints: cs.map((c, i) => ({ compound: c, laps: i < n ? len : N - len * n })) } });
  };
  const setEnd = (k: number, lap: number) => {
    const e = [...ends]; e[k] = lap;
    const st = sc.strategy.stints.map((s, i) => ({ compound: s.compound, laps: (i === e.length - 1 ? N : e[i]) - (i ? e[i - 1] : 0) }));
    upd({ strategy: { stints: st } });
  };
  const setComp = (k: number, c: Dry) => upd({ strategy: { stints: sc.strategy.stints.map((s, i) => (i === k ? { ...s, compound: c } : s)) } });
  const w = sc.weather;
  const setWeather = (x: Weather) => upd({ weather: x });

  return (
    <aside class="controls">
      <div class="group">
        <span class="label">Track</span>
        <select value={sc.track} onChange={(e) => setTrack((e.target as HTMLSelectElement).value)}>
          <optgroup label={`${season} calendar`}>
            {tracks.filter(([, v]) => v.on_2026_calendar).map(([k, v]) => <option value={k} disabled={!v.has_dry_data}>R{v.round_2026} {v.name}{v.has_dry_data ? "" : " (no dry data)"}</option>)}
          </optgroup>
          <optgroup label="Other circuits with data">
            {tracks.filter(([, v]) => !v.on_2026_calendar && v.has_dry_data).map(([k, v]) => <option value={k}>{v.name} ({v.circuit_name})</option>)}
          </optgroup>
        </select>
        <div class="hint">{N} laps · {t.dry_races} dry races fitted · base lap {t.base_lap?.base_s.toFixed(2)} s{t.base_lap?.source === "track_scaled" ? ` (from ${t.base_lap.from_year}, scaled to ${modelSeason} pace)` : ""}</div>
      </div>

      <div class="group">
        <span class="label">Driver and car</span>
        <label class="field"><span>Driver</span>
          <select value={sc.driver} onChange={(e) => {
            const id = (e.target as HTMLSelectElement).value;
            const g = p.grid.grid.find((x) => x.driver_id === id);
            setSlotChoice(null);
            setSc(withQuali({ ...sc, driver: id, team: g?.team_id ?? sc.team }, parsed, null));
          }}>
            <optgroup label={`${modelSeason} grid`}>{drivers.filter(([k]) => gridIds.has(k)).map(([k, v]) => <option value={k}>{v.name}</option>)}</optgroup>
            <optgroup label="Not on the current grid (skill projected, wider uncertainty)">{drivers.filter(([k]) => !gridIds.has(k)).map(([k, v]) => <option value={k}>{v.name} (last raced {v.last_season})</option>)}</optgroup>
          </select>
        </label>
        <label class="field"><span>Car ({modelSeason} team){after ? ": the car they qualified" : ""}</span>
          <select value={sc.team} disabled={after} onChange={(e) => upd({ team: (e.target as HTMLSelectElement).value })}>
            {teams.map(([k, v]) => <option value={k}>{v.name}</option>)}
          </select>
        </label>
        <DriverNote p={p} sc={sc} />
        <div class="seg" style={{ margin: "4px 0 6px" }}>
          <button class={after ? "" : "on"} onClick={() => setSc({ ...sc, listedGrid: false, gridImpliesPace: false, gridEntries: undefined })}>Before qualifying</button>
          <button class={after ? "on" : ""} onClick={() => setSc(withQuali({ ...sc, listedGrid: true, gridImpliesPace: true }, parsed, slotChoice))}>After qualifying</button>
        </div>
        <div class="hint" style={{ marginBottom: "8px" }}>{after
          ? "Uses the real qualifying result of this race: everyone starts where they qualified, and the lap-time gaps tell the model who is quick this weekend. This is the tested, more accurate mode."
          : "Qualifying not run yet: you choose where your driver starts; the other cars line up by expected pace. The model knows season form only."}</div>
        {!after && <label class="field"><span>Grid position</span>
          <select value={sc.grid} onChange={(e) => upd({ grid: Number((e.target as HTMLSelectElement).value) })}>
            {Array.from({ length: p.grid.grid.length }, (_, i) => <option value={i + 1}>P{i + 1}</option>)}
          </select>
        </label>}
        {after && <>
          <div class="hint" style={{ marginBottom: "6px" }}>
            {qStatus.kind === "loading" && "Loading the real qualifying result…"}
            {qStatus.kind === "loaded" && qStatus.info && <>
              <b>{qStatus.msg}</b>: {qStatus.info.source === "result" ? "starting grid from the official race result" : qStatus.info.source === "official" ? "official starting grid (OpenF1), penalties applied" : "qualifying order"}; lap times from qualifying (Jolpica-F1).
              {qStatus.info.penalties.length > 0 && <div style={{ marginTop: "3px" }}>Grid changes after qualifying: {qStatus.info.penalties.join("; ")}.</div>}
              {qStatus.info.penalties.length === 0 && qStatus.info.source !== "qualifying" && <div style={{ marginTop: "3px" }}>Checked: grid matches the qualifying order (no penalties).</div>}
              {qStatus.info.warnings.map((w) => <div class="warn" style={{ marginTop: "3px" }}>{w}</div>)}
            </>}
            {qStatus.kind === "missing" && <span class="warn">Qualifying for {t.name} {season} has not happened or is not published yet. Use "Before qualifying", or enter a grid under "Edit grid".</span>}
            {qStatus.kind === "notcal" && <span class="warn">{t.name} is not on the {season} calendar, so there is no real qualifying. Use "Before qualifying", or enter a grid under "Edit grid".</span>}
            {qStatus.kind === "error" && <span class="err">Could not load qualifying ({qStatus.msg}). Enter a grid under "Edit grid", or try again.</span>}
          </div>
          {inGrid && <label class="field"><span>Grid position (real grid P{realSlot}{qualified && qualified !== realSlot ? `, qualified P${qualified}` : ""})</span>
            <select value={sc.grid} onChange={(e) => {
              const v = Number((e.target as HTMLSelectElement).value);
              setSlotChoice(v === realSlot ? null : v);
              setSc(withQuali(sc, parsed, v));
            }}>
              {parsed.entries.map((_, i) => <option value={i + 1}>P{i + 1}{i + 1 === realSlot ? " (real grid)" : ""}</option>)}
            </select>
          </label>}
          {inGrid && slotChoice !== null && slotChoice !== realSlot && <div class="hint">What-if: {p.drivers[sc.driver]?.name} starts P{sc.grid} instead of P{realSlot}. Their qualifying pace is unchanged, so this shows what track position alone is worth.</div>}
          {parsed.entries.length > 0 && !inGrid && <div class="err">{p.drivers[sc.driver]?.name ?? sc.driver} is not in this grid. Pick one of the drivers who qualified.</div>}
          <div class="row" style={{ gap: "8px", margin: "4px 0" }}>
            <label class="row" style={{ gap: "4px", flex: "none" }}>
              <input type="checkbox" style={{ flex: "none" }} checked={qWet} onChange={(e) => { const v = (e.target as HTMLInputElement).checked; setQWet(v); setSc(withQuali(sc, parseQuali(qText, p, v, qStatus.info), slotChoice)); }} />
              <span style={{ color: "var(--text-secondary)" }}>Wet qualifying</span>
            </label>
            <button class="btn small" style={{ flex: "none" }} onClick={() => setManual(!manual)}>{manual ? "Hide grid" : "Edit grid"}</button>
          </div>
          {qWet && <div class="hint">Wet qualifying: the order is used, the lap-time gaps are not.</div>}
          {manual && <QualiPanel text={qText} parsed={parsed}
            onChange={(text) => { setQText(text); setSc(withQuali(sc, parseQuali(text, p, qWet, qStatus.info), slotChoice)); }} />}
        </>}
      </div>

      <div class="group">
        <span class="label">Strategy</span>
        <div class="row" style={{ marginBottom: "8px" }}>
          <label class="field" style={{ margin: 0 }}><span>Stops</span>
            <select value={stops} onChange={(e) => setStops(Number((e.target as HTMLSelectElement).value))}>
              {[0, 1, 2, 3].map((n) => <option value={n}>{n}</option>)}
            </select>
          </label>
          <div style={{ display: "flex", gap: "4px", alignSelf: "flex-end" }}>
            <button class="btn small" title="Fastest strategy on expected lap times (no traffic, no SC)" onClick={() => { const s = bestDeterministic(p, sc.track, userPace); if (s) upd({ strategy: s }); }}>Fastest</button>
            <button class="btn small" title="Most common compound sequence teams ran here since 2022, at median stop laps" disabled={!mostCommon(p, sc.track)} onClick={() => { const s = mostCommon(p, sc.track); if (s) upd({ strategy: s }); }}>Common</button>
          </div>
        </div>
        {sc.strategy.stints.map((s, k) => (
          <div class="stint">
            <span class="chip" style={{ background: COMPOUND_COLOR[s.compound] }}>{COMPOUND_LETTER[s.compound]}</span>
            <select value={s.compound} onChange={(e) => setComp(k, (e.target as HTMLSelectElement).value as Dry)}>
              {DRY.map((c) => <option value={c}>{c[0] + c.slice(1).toLowerCase()} (cap {ts?.maxStint[c]})</option>)}
            </select>
            {k < stops
              ? <input type="number" min={1} max={N - 1} value={ends[k]} title="Pit at the end of this lap" onChange={(e) => setEnd(k, Number((e.target as HTMLInputElement).value))} />
              : <span class="n">to lap {N}</span>}
            <span class="n">{s.laps}L</span>
          </div>
        ))}
        <div class="hint">Number = pit at the end of that lap. Cap = longest stint on that compound observed at this track.</div>
        {rule && <label class="row" style={{ margin: "4px 0", gap: "6px" }}>
          <input type="checkbox" style={{ flex: "none" }} checked={sc.applyRules !== false} onChange={(e) => upd({ applyRules: (e.target as HTMLInputElement).checked })} />
          <span style={{ color: "var(--text-secondary)" }}>Apply track rule: {rule.note}</span>
        </label>}
        {check?.errors.map((e) => <div class="err">{e}</div>)}
        {check?.warnings.map((e) => <div class="warn">{e}</div>)}
        <label class="field" style={{ marginTop: "8px" }}><span>Pace mode</span>
          <div class="seg">
            {(["conserve", "normal", "push"] as PaceMode[]).map((m) => <button class={sc.paceMode === m ? "on" : ""} onClick={() => upd({ paceMode: m })}>{m}</button>)}
          </div>
        </label>
        <div class="hint"><span class="tag pooled">what-if only</span> Push / conserve = ±{p.global.pace_mode.mode_pace_sd_pct.toFixed(2)}% pace, with {Math.abs(p.global.pace_mode.wear_change_per_pace_pct).toFixed(3)}% extra / less wear per lap of tyre age per 1% of pace (teammate data, n={p.global.pace_mode.n_pairs.toLocaleString()} stint pairs). Both numbers are measured, but they describe how teammates' stints differ (traffic, damage and team orders included), not a speed a driver can choose, and the extra wear is likely understated. So "push" looks nearly free here: the model cannot tell you whether pushing pays.</div>
        <label class="row" style={{ marginTop: "8px", gap: "6px" }}>
          <input type="checkbox" style={{ flex: "none" }} checked={sc.reactToSC} onChange={(e) => upd({ reactToSC: (e.target as HTMLInputElement).checked })} />
          <span style={{ color: "var(--text-secondary)" }}>Pit early under SC/VSC when a stop is due soon</span>
        </label>
      </div>

      <div class="group">
        <span class="label">Weather</span>
        <div class="seg" style={{ marginBottom: "8px" }}>
          <button class={w.kind === "dry" ? "on" : ""} onClick={() => setWeather({ kind: "dry" })}>Dry</button>
          <button class={w.kind === "probability" ? "on" : ""} onClick={() => setWeather({ kind: "probability", p: 0.3 })}>Rain chance</button>
          <button class={w.kind === "window" ? "on" : ""} onClick={() => setWeather({ kind: "window", startLap: Math.round(N * 0.3), endLap: Math.round(N * 0.55) })}>Rain window</button>
        </div>
        {w.kind === "probability" && <label class="field"><span>Chance of a rain spell: {pct(w.p, 0)}</span>
          <input type="range" min={0} max={1} step={0.05} value={w.p} onInput={(e) => setWeather({ kind: "probability", p: Number((e.target as HTMLInputElement).value) })} /></label>}
        {w.kind === "window" && <div class="row">
          <label class="field"><span>Rain from lap</span><input type="number" min={1} max={N} value={w.startLap} onChange={(e) => setWeather({ ...w, startLap: Number((e.target as HTMLInputElement).value) })} /></label>
          <label class="field"><span>to lap</span><input type="number" min={1} max={N} value={w.endLap} onChange={(e) => setWeather({ ...w, endLap: Number((e.target as HTMLInputElement).value) })} /></label>
        </div>}
        {w.kind !== "dry" && <>
          <div class="hint">{w.kind === "window"
            ? "It rains for these laps: the track gets wet over a couple of laps (or is already wet if the window starts on lap 1), stays wet at a level taken from real wet races, then dries at the measured rate. Enter when rain falls, not when cars are on wet tyres: the drying afterwards is added by the model."
            : "A rain spell, if it comes, replays a real wet spell lap for lap (rise, peak and drying)."}</div>
          <span class="label" style={{ marginTop: "10px" }}>Wet-weather call (your car)</span>
          <label class="field"><span>When to switch to wet tyres and back</span>
            <select value={sc.wetCall?.timing ?? 0} onChange={(e) => upd({ wetCall: { timing: Number((e.target as HTMLSelectElement).value), interOnly: !!sc.wetCall?.interOnly } })}>
              {[-3, -2, -1, 0, 1, 2, 3].map((v) => <option value={v}>{v === 0 ? "When they become faster (model's call)" : v < 0 ? `${-v} lap${v < -1 ? "s" : ""} early (gamble)` : `${v} lap${v > 1 ? "s" : ""} late (stay out)`}</option>)}
            </select>
          </label>
          <label class="row" style={{ gap: "6px", marginBottom: "6px" }}>
            <input type="checkbox" style={{ flex: "none" }} checked={!!sc.wetCall?.interOnly} onChange={(e) => upd({ wetCall: { timing: sc.wetCall?.timing ?? 0, interOnly: (e.target as HTMLInputElement).checked } })} />
            <span style={{ color: "var(--text-secondary)" }}>Intermediates only (never full wets)</span>
          </label>
          <div class="hint">Your dry strategy applies until the rain. Rivals switch when wet tyres become faster, at the crossover measured from when real teams switched; every team sees rain about 3 laps ahead. Wet pace is <span class="tag pooled">pooled</span> from {p.global.wet.n_wet_races} wet races. Tested on 13 real wet races: with the rain model the finishing order is predicted about as well as when rain is ignored, no better (see Track record).</div>
        </>}
      </div>

      <div class="group">
        <span class="label">Run</span>
        <label class="field"><span>Simulated races</span>
          <select value={sc.sims} onChange={(e) => upd({ sims: Number((e.target as HTMLSelectElement).value) })}>
            {[2000, 5000, 10000, 20000].map((n) => <option value={n}>{n.toLocaleString()}</option>)}
          </select>
        </label>
        {afterBlock && <div class="hint">After qualifying needs a grid for this race (see above).</div>}
        <button class="btn primary" disabled={props.running || !check?.ok || !ts || afterBlock} onClick={props.onRun}>{props.running ? "Simulating…" : "Simulate"}</button>
        {props.progress && <><div class="progress"><i style={{ width: `${(100 * props.progress.done) / Math.max(1, props.progress.total)}%` }} /></div><div class="hint">{props.progress.phase}</div></>}
        {props.err && <div class="err">{props.err}</div>}
      </div>
    </aside>
  );
}

function DriverNote({ p, sc }: { p: Params; sc: Scenario }) {
  const d = p.drivers[sc.driver], team = p.teams[sc.team];
  const bt = team.by_track[sc.track];
  const onGrid = p.grid.grid.find((g) => g.driver_id === sc.driver);
  const seat = p.grid.grid.filter((g) => g.team_id === sc.team);
  const replaced = onGrid?.team_id === sc.team ? null : seat[seat.length - 1];
  return (
    <div class="hint" style={{ marginBottom: "8px" }}>
      {d.no_dry_data ? <>No dry race in the data: skill = average driver ± {d.sd_pct.toFixed(3)}% (prior spread).</> : <>Skill {sgn(d.skill_pct, 3)}% ± {d.sd_pct.toFixed(3)} ({d.career_dry_races_fitted} dry races; negative = faster).</>}{d.years_since_last > 0 ? ` Last raced ${d.last_season}: uncertainty widened by ${d.years_since_last} yr of drift.` : ""}<br />
      Car {sgn(bt ? bt.car_pct : team.season_mean_pct, 3)}% ± {(bt ? bt.sd : team.season_sd_pct).toFixed(3)} ({bt ? `measured at this track in ${p.meta.target_season ?? 2026}` : `${p.meta.target_season ?? 2026} season mean, track not raced in ${p.meta.target_season ?? 2026}`}).
      {replaced && <><br />Takes {replaced.name}'s seat{onGrid ? `; ${replaced.name} moves to ${p.teams[onGrid.team_id].name}` : ""}.</>}
    </div>
  );
}

// ------------------------------------------------------------ results

function Results({ p, r }: { p: Params; r: MCResult }) {
  const me = r.drivers.find((d) => d.isUser)!;
  const top = r.drivers.filter((d) => !d.isUser).slice(0, 4);
  const colors = ["var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];
  const series: Series[] = r.drivers.map((d) => {
    const k = top.indexOf(d);
    return { key: d.driverId, label: d.code, color: d.isUser ? "var(--series-1)" : k >= 0 ? colors[k] : "var(--series-other)", values: d.medianGap, emphasis: d.isUser || k >= 0 };
  });
  const alt = r.alternative;
  const ch = r.chosen;
  const parts = [
    ["Pit stops", "pit"], ["Tyre pace and wear", "tyre"], ["Dirty air", "traffic"], ["Held up behind", "held"], ["Wet conditions", "weather"],
  ] as const;
  return (
    <>
      <div class="cards">
        <Card k="Win" v={pct(me.win)} s={`${me.code} · ${me.teamName} car`} />
        <Card k="Podium" v={pct(me.podium)} s={`from P${r.scenario.grid}${r.scenario.listedGrid ? " (real grid)" : ""}`} />
        <Card k="Points" v={pct(me.points)} s={`${me.expPoints.toFixed(1)} expected pts`} />
        <Card k="Retirement" v={pct(me.dnf)} s={`team ${p.meta.target_season ?? 2026} rate × track`} />
        <Card k="Mean finish" v={me.meanPos.toFixed(1)} s="DNF counted at its place" />
        <Card k="Sims" v={r.sims.toLocaleString()} s={`${(r.elapsedMs / 1000).toFixed(1)} s · ${r.trackName}`} />
      </div>
      <ActualBanner p={p} r={r} />
      <div class="hint" style={{ marginBottom: "8px" }}>{r.scenario.listedGrid
        ? "Mode: after qualifying. Real grid order, and qualifying gaps read as this weekend's pace (the backtested mode)."
        : "Mode: before qualifying. You set your grid slot; rivals start in order of expected pace. Less accurate than after qualifying (see Track record)."}</div>
      {r.warnings.map((w) => <div class="warn" style={{ marginBottom: "8px" }}>{w}</div>)}

      <div class="panel">
        <h2>Finishing probabilities, every driver</h2>
        <div class="sub">Share of {r.sims.toLocaleString()} simulated races. Uncertainty in car pace, driver skill, tyre wear and pit loss is sampled in every race, along with SC/VSC/red flags, retirements, the start, overtakes and lap noise. Sorted by expected points.</div>
        <div class="table-wrap"><table class="t">
          <thead><tr><th class="l">Driver</th><th class="l">Car</th>{r.scenario.actualResult && <th>Actual</th>}<th>Win</th><th>Podium</th><th>Points</th><th>DNF</th><th>Mean pos</th><th>Exp. pts</th><th class="l" style={{ whiteSpace: "normal", minWidth: "70px" }}>Finish P1 → P{r.drivers.length}, DNF</th></tr></thead>
          <tbody>{r.drivers.map((d) => (
            <tr class={d.isUser ? "user" : ""}>
              <td class="l">{d.name}</td><td class="l">{d.teamName}</td>
              {r.scenario.actualResult && <td class="mono">{actualOf(r, d.code)}</td>}
              <td><Bar v={d.win} /></td><td><Bar v={d.podium} /></td><td><Bar v={d.points} /></td>
              <td>{pct(d.dnf)}</td><td>{d.meanPos.toFixed(1)}</td><td>{d.expPoints.toFixed(1)}</td>
              <td class="l heat-cell"><Heat hist={d.posHist} /></td>
            </tr>
          ))}</tbody>
        </table></div>
      </div>

      <div class="panel">
        <h2>Median race trace: gap to the leader</h2>
        <div class="sub">Median gap behind the leader at the end of each lap, over the first {Math.min(400, r.sims)} simulated races. Your driver and the four highest expected scorers are highlighted; others are grey. Gaps above 60 s are clipped.</div>
        <div class="legend">{series.filter((s) => s.emphasis).map((s) => <span><i style={{ background: s.color }} />{s.label}</span>)}<span><i style={{ background: "var(--series-other)" }} />others</span></div>
        <LineChart series={series} yLabel="gap to leader (s)" invert yMaxClip={60} />
      </div>

      <div class="panel">
        <h2>Tyre stint map: one representative simulated race</h2>
        <div class="sub">The simulated race closest to the median outcome for your driver. Rivals run strategies teams actually used here (planned green-flag stops only). Shading: <span style={{ background: "var(--sc)", padding: "0 4px" }}>SC</span> <span style={{ background: "var(--vsc)", padding: "0 4px" }}>VSC</span> <span style={{ background: "var(--red)", padding: "0 4px" }}>red flag</span>.</div>
        <div class="legend">{(["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"] as const).map((c) => <span><i class="sq" style={{ background: COMPOUND_COLOR[c] }} />{COMPOUND_LETTER[c]} {c.toLowerCase()}</span>)}</div>
        <StintMap rows={r.representative.stints.map((s) => ({ ...s, user: s.code === me.code }))} laps={r.laps} status={r.representative.status} wetness={r.representative.wetness} />
      </div>

      <div class="panel">
        <h2>Your strategy vs the best alternative the model found</h2>
        <div class="sub">Candidates are ranked by expected race time, then the best of each compound sequence is re-simulated on the same {alt?.sims.toLocaleString()} random races as yours (paired comparison). Best = highest expected points; its gain is then measured again on {alt?.sims.toLocaleString()} fresh races, so picking the luckiest of several does not inflate it.</div>
        <div class="warn" style={{ marginBottom: "8px" }}><span class="tag pooled">experimental</span> Not validated. On real teammates who ran different strategies, knowing the strategies did not measurably improve the predicted gap in 2025 or 2026, even with the true tyre values of each race: those gaps vary by 17–25 s, the strategy effects are about 5 s, so the test cannot tell. The tyre model itself does predict lap-to-lap gaps between teammates (about 28% of their variation), but overstates tyre differences by about 20%. Treat differences under about 5 s as noise. See the Track record tab.</div>
        {alt && <div style={{ margin: "0 0 10px", fontSize: "13px" }}>{(alt.dExpPts ?? 0) > 2 * (alt.dExpPtsSE ?? 0)
          ? <>Best alternative <b class="mono">{alt.label}</b> gains <b>{sgn(alt.dExpPts ?? 0)}</b> expected points (±{(2 * (alt.dExpPtsSE ?? 0)).toFixed(2)}, paired) over yours.</>
          : <>No alternative is distinguishably better than yours. The closest, <b>{alt.label}</b>, is {sgn(alt.dExpPts ?? 0)} ± {(2 * (alt.dExpPtsSE ?? 0)).toFixed(2)} expected points: within Monte Carlo noise.</>}
          {alt.aheadShare !== undefined && <> In the same simulated races it finished <b>ahead of yours in {pct(alt.aheadShare, 0)}</b> and behind in {pct(alt.behindShare ?? 0, 0)} (level in the rest): that spread, from tyre wear, safety cars and rivals, is how sure the choice is.</>}</div>}
        <div class="table-wrap"><table class="t" style={{ marginBottom: "10px" }}>
          <thead><tr><th class="l">Strategy</th><th>Exp. pts</th><th style={{ whiteSpace: "normal" }}>vs yours (±2 SE)</th><th>Win</th><th>Podium</th><th>Points</th><th>Mean pos</th><th style={{ whiteSpace: "normal" }}>Median time</th><th>Pit</th><th style={{ whiteSpace: "normal" }}>Held up</th></tr></thead>
          <tbody>{r.candidates.map((c, i) => (
            <tr class={i === 0 ? "user" : ""}>
              <td class="l mono" style={{ whiteSpace: "normal" }}>{i === 0 ? "yours: " : c === alt ? "best alt: " : ""}<span style={{ whiteSpace: "nowrap" }}>{c.label}</span></td>
              <td>{c.expPoints.toFixed(2)}</td>
              <td>{i === 0 ? "–" : `${sgn(c.dExpPts ?? 0)} ± ${(2 * (c.dExpPtsSE ?? 0)).toFixed(2)}`}{i > 0 && Math.abs(c.dExpPts ?? 0) < 2 * (c.dExpPtsSE ?? 0) ? <span class="tag" title="The difference is smaller than twice its standard error: Monte Carlo noise">within noise</span> : ""}</td>
              <td>{pct(c.win)}</td><td>{pct(c.podium)}</td><td>{pct(c.points)}</td><td>{c.meanPos.toFixed(2)}</td>
              <td>{c.medianTime ? fmtTime(c.medianTime) : "–"}</td><td>{c.parts.pit.toFixed(1)} s</td><td>{c.parts.held.toFixed(1)} s</td>
            </tr>
          ))}</tbody>
        </table></div>
        {alt && <>
          <div class="grid2">
            <div>
              <h2 style={{ fontSize: "12.5px" }}>Where the time goes (mean seconds per race)</h2>
              <PairedBars items={parts.map(([label, k]) => ({ label, a: r.candidates[0].parts[k], b: alt.parts[k] }))} aLabel={`yours ${ch.label}`} bLabel={`best ${alt.label}`} unit=" s" w={460} />
              <div class="hint">Tyre = compound offset + wear, summed over the race. Held up = time lost behind a slower car that could not be passed. Time under SC/VSC is the same for every strategy and is left out.</div>
            </div>
            <div>
              <h2 style={{ fontSize: "12.5px" }}>Gap: yours minus best alternative, lap by lap</h2>
              {r.deltaByLap && <BandChart {...r.deltaByLap} yLabel="seconds (positive = yours behind)" w={460} />}
              <div class="hint">Line = median, band = middle 50% over paired races. A rising line means your strategy is losing time on those laps. A flat 0 after both cars have stopped usually means your car is held up in the same train either way, so the car ahead sets your lap times.</div>
            </div>
          </div>
        </>}
      </div>

      {r.wetCallEval && <div class="panel">
        <h2>Your wet-weather call vs the model's call</h2>
        <div style={{ fontSize: "13px" }}>Call: <b>{r.wetCallEval.label}</b>. Expected points {r.wetCallEval.yoursExpPts.toFixed(2)} vs {r.wetCallEval.defaultExpPts.toFixed(2)} with the model's call: <b>{sgn(r.wetCallEval.dExpPts)} ± {(2 * r.wetCallEval.dExpPtsSE).toFixed(2)}</b>{Math.abs(r.wetCallEval.dExpPts) < 2 * r.wetCallEval.dExpPtsSE ? " (within noise)" : ""}{r.wetCallEval.dMedianTime !== null ? `; median race time ${sgn(r.wetCallEval.dMedianTime, 1)} s` : ""}.</div>
        <div class="hint" style={{ marginTop: "4px" }}>Same {r.wetCallEval.sims.toLocaleString()} random races for both calls (paired).{p.global.wet.switch_timing && <> In real races ({p.global.wet.switch_timing.n_transitions} field-wide tyre changes in the wet) each lap later than the field cost about <b>{(-p.global.wet.switch_timing.places_gained_per_lap_later).toFixed(1)} places</b> (95% CI {(-p.global.wet.switch_timing.places_gained_per_lap_later_ci95[1]).toFixed(1)} to {(-p.global.wet.switch_timing.places_gained_per_lap_later_ci95[0]).toFixed(1)}). The model's effect is about 5 times that, because how fast slicks lose time past the crossover is assumed, not fitted: trust the direction more than the size.</>}</div>
      </div>}
      <TrackData p={p} r={r} />
      <ExplainPanel result={r} />
    </>
  );
}

function actualOf(r: MCResult, code: string): string {
  const a = r.scenario.actualResult?.find((x) => x.code === code);
  return !a ? "–" : a.pos === null ? "DNF" : `P${a.pos}`;
}

/** For a race that has already been run: the real winner next to the
 *  prediction, and whether the model had learned from this race. */
function ActualBanner({ p, r }: { p: Params; r: MCResult }) {
  const act = r.scenario.actualResult;
  if (!act) return null;
  const t = p.tracks[r.scenario.track];
  const season = Number(p.grid.calendar[0]?.date.slice(0, 4) ?? 2026);
  const dt = p.meta.data_through;
  const seen = !!dt && !!t.round_2026 && (season < dt.year || (season === dt.year && t.round_2026 <= dt.round));
  const winner = act.find((a) => a.pos === 1);
  const w = winner && r.drivers.find((d) => d.code === winner.code);
  const fav = r.drivers.reduce((a, b) => (b.win > a.win ? b : a));
  return (
    <div class="panel" style={{ borderColor: "var(--axis)" }}>
      <h2>This race has been run{r.scenario.raceLabel ? `: ${r.scenario.raceLabel}` : ""}</h2>
      <div style={{ fontSize: "13px" }}>Winner: <b>{w?.name ?? winner?.code ?? "–"}</b> (started P{winner?.grid || "pit lane"}). The model gave them <b>{w ? pct(w.win) : "–"}</b>; its favourite was {fav.name} at {pct(fav.win)}. The "Actual" column shows every finishing position.</div>
      <div class="hint" style={{ marginTop: "4px" }}>{seen
        ? "The model has already learned from this race, so this is a look back, not a forecast. The honest forecast record is on the Track record tab."
        : "The model had not seen this race: this is a genuine forecast made from data before the race."}</div>
    </div>
  );
}

const fmtTime = (s: number) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return `${h}:${String(m).padStart(2, "0")}:${x.toFixed(1).padStart(4, "0")}`; };
const Card = (x: { k: string; v: string; s: string }) => <div class="card"><div class="k">{x.k}</div><div class="v">{x.v}</div><div class="s">{x.s}</div></div>;
const Bar = ({ v }: { v: number }) => <div class="bar"><i style={{ width: `${Math.min(100, 100 * v)}%` }} /><b>{pct(v)}</b></div>;
const Src = ({ s }: { s: string }) => <span class={`tag ${s.split(" ")[0]}`}>{s}</span>;

function TrackData({ p, r }: { p: Params; r: MCResult }) {
  const t = p.tracks[r.scenario.track], g = p.global;
  const pc = t.pace!;
  const est = (k: string, label: string, unit = " s", d = 3) => {
    const e = pc[k];
    return <><dt>{label}</dt><dd>{sgn(e.mean_s ?? 0, d)}{unit} ± {(e.sd_s ?? 0).toFixed(d)} <Src s={e.source} /> <span class="hint">{e.n_races} races</span></dd></>;
  };
  return (
    <div class="panel">
      <h2>What the model knows about {t.name}</h2>
      <div class="sub">Every value is fitted from data. <span class="tag track">track</span> = estimated at this circuit (shrunk toward the pool by its uncertainty); <span class="tag pooled">pooled</span> = not enough data here, so the cross-track estimate is used. <span class="tag track">track + weekend long runs</span> = this weekend's practice long runs (or sprint) added to the wear, before the race. Full list: the Model &amp; assumptions tab.</div>
      <div class="grid2">
        <dl class="kv">
          <dt>Dry races fitted</dt><dd>{t.dry_races}</dd>
          <dt>Base lap</dt><dd>{t.base_lap!.base_s.toFixed(2)} s ({t.base_lap!.source === "track" ? `${t.base_lap!.from_year} race` : `${t.base_lap!.from_year}, scaled by the season pace ratio`})</dd>
          {est("offset_SOFT", "Soft vs medium (new tyre)")}
          {est("offset_HARD", "Hard vs medium (new tyre)")}
          {est("slope_SOFT", "Soft wear per lap", " s/lap")}
          {est("slope_MEDIUM", "Medium wear per lap", " s/lap")}
          {est("slope_HARD", "Hard wear per lap", " s/lap")}
          {est("fuel", "Fuel + track evolution per lap", " s/lap")}
          {est("traffic", "Dirty air (< 1 s behind)", " s/lap")}
          {est("sigma", "Lap-to-lap noise (SD)")}
          <dt>Stint caps (observed)</dt><dd>{DRY.map((c) => `${c[0]} ${t.max_stint?.[c] ?? g.max_stint_pooled[c]}`).join(" · ")}</dd>
        </dl>
        <dl class="kv">
          <dt>Pit loss (green)</dt><dd>{t.pit ? `${t.pit.green_loss_s.toFixed(1)} s ± ${t.pit.sd.toFixed(1)} (${t.pit.n_stops} stops)` : `${g.pooled.pit_green_loss_s.toFixed(1)} s`} <Src s={t.pit ? "track" : "pooled"} /></dd>
          <dt>Pit under SC / VSC</dt><dd>× {g.pit.neutralised_ratio.sc.median_ratio.toFixed(2)} / × {g.pit.neutralised_ratio.vsc.median_ratio.toFixed(2)} of green loss <Src s="pooled" /></dd>
          <dt>Safety car</dt><dd>{t.sc_rate?.rate_per_race.toFixed(2)} per race <Src s="pooled" /> <span class="hint">{g.safety_car.SC.between_track_variation_detected ? "" : "no between-track difference detected in SC counts (variance/mean " + g.safety_car.SC.variance_to_mean.toFixed(2) + "), so every track gets the pooled rate"}</span></dd>
          <dt>VSC</dt><dd>{t.vsc_rate?.rate_per_race.toFixed(2)} per race <Src s="track" />{Math.abs((g.safety_car.VSC.era_2026.ratio_averaged ?? 1) - 1) > 0.005 ? ` × ${g.safety_car.VSC.era_2026.ratio_averaged!.toFixed(2)} (2026 rules: measured ratio ${g.safety_car.VSC.era_2026.ratio.toFixed(2)}, ${Math.round(100 * (g.safety_car.VSC.era_2026.p_rules_changed_rate ?? 0))}% likely a real change)` : ""}</dd>
          <dt>Red flag</dt><dd>{t.red_rate?.rate_per_race.toFixed(2)} per race ({t.red_rate?.observed} in {t.red_rate?.n_races} dry races)</dd>
          <dt>In simulation</dt><dd>SC in {pct(r.neutralShare.sc, 0)} of races, VSC {pct(r.neutralShare.vsc, 0)}, red {pct(r.neutralShare.red, 0)}{r.neutralShare.wet ? `, rain ${pct(r.neutralShare.wet, 0)}` : ""}</dd>
          <dt>Overtaking</dt><dd>track intercept {sgn(t.overtake?.intercept ?? 0)} ± {(t.overtake?.se ?? 0).toFixed(2)} ({t.overtake?.pairs.toLocaleString()} close pairs, {t.overtake?.passes} passes; lower = harder)</dd>
          <dt>Lap-1 spread</dt><dd>× {t.start?.ratio.toFixed(2)} of pooled ({t.start?.n} starts)</dd>
          <dt>Retirement factor</dt><dd>× {t.dnf?.ratio.toFixed(2)} ({t.dnf?.starts} starts)</dd>
          <dt>Rival strategies</dt><dd>{t.strategies ? `${t.strategies.n} planned strategies from ${t.strategies.races} races since ${t.strategies.from_year}` : "none observed"}</dd>
          <dt>Wet model</dt><dd>pooled, {g.wet.n_wet_races} races; slick/inter crossover at {g.wet.switch_crossover.inter_ratio.toFixed(3)}× dry pace (CI {g.wet.switch_crossover.ci95.map((x) => x.toFixed(3)).join("–")}) <Src s="pooled" /></dd>
        </dl>
      </div>
    </div>
  );
}

function DocPage({ file, then }: { file: string; then?: string }) {
  const [html, setHtml] = useState<string>("Loading…");
  useEffect(() => {
    const get = (f: string) => fetch(new URL(f, document.baseURI)).then((r) => (r.ok ? r.text() : ""));
    Promise.all([get(file), then ? get(then) : Promise.resolve("")]).then(([a, b]) => setHtml(renderMarkdown(a) + (b ? "<hr />" + renderMarkdown(b) : "")));
  }, [file, then]);
  return <div class="main doc" dangerouslySetInnerHTML={{ __html: html }} />;
}

render(<App />, document.getElementById("app")!);
void strategyLabel;
