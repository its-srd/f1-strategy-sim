// "After qualifying" input: paste the real grid with each driver's best
// qualifying lap. The engine then reads the grid and the qualifying gaps as
// evidence of pace this weekend (the backtested mode, see docs/backtest.md).
import type { GridEntry, Params } from "../engine/types.ts";

export interface QualiParse {
  entries: GridEntry[];
  rows: { slot: number; code: string; name: string; lap: number | null; gap: number | null; listed: boolean }[];
  errors: string[];
  notes: string[];
}

const TIME = /^(?:(\d+):)?(\d{1,3}\.\d{1,3})$/;

function toSeconds(tok: string): number | null {
  const m = tok.match(TIME);
  return m ? (m[1] ? Number(m[1]) * 60 : 0) + Number(m[2]) : null;
}

export function formatLap(s: number): string {
  const m = Math.floor(s / 60);
  return m ? `${m}:${(s - 60 * m).toFixed(3).padStart(6, "0")}` : s.toFixed(3);
}

/** One driver per line, in grid order: an optional position, the driver
 *  (3-letter code, car number or surname), then the best lap time (m:ss.sss or
 *  ss.sss), or nothing if no time was set. */
export function parseQuali(text: string, p: Params, wet: boolean): QualiParse {
  const grid = p.grid.grid;
  const errors: string[] = [], notes: string[] = [];
  const find = (id: string): GridEntry | undefined => {
    const s = id.toLowerCase();
    const onGrid = grid.find((g) => g.code.toLowerCase() === s || g.number === id
      || g.name.toLowerCase().split(" ").pop() === s);
    if (onGrid) return onGrid;
    // A stand-in or reserve driver in the data races their latest team's car.
    const hit = Object.entries(p.drivers).filter(([, d]) => d.code.toLowerCase() === s || d.name.toLowerCase().split(" ").pop() === s)
      .sort((a, b) => b[1].last_season - a[1].last_season)[0];
    return hit && p.teams[hit[1].last_team]
      ? { driver_id: hit[0], code: hit[1].code, name: hit[1].name, team_id: hit[1].last_team, number: "" }
      : undefined;
  };
  const picked: { g: GridEntry; lap: number | null }[] = [];
  text.split("\n").forEach((raw, n) => {
    const line = raw.trim();
    if (!line || line.startsWith("#")) return;
    let toks = line.split(/\s+/);
    // A leading position ("1", "P1", "1." or "1)") is dropped when another
    // token identifies the driver; otherwise it may be a car number.
    if (toks.length > 1 && /^P?\d+[.)]?$/i.test(toks[0])) {
      const rest = toks.slice(1).find((t) => !TIME.test(t));
      if (rest && find(rest)) toks = toks.slice(1);
    }
    const id = toks.find((t) => !TIME.test(t));
    const g = id ? find(id) : undefined;
    if (!g) { errors.push(`Line ${n + 1}: "${line}": no driver in the data matches "${id ?? ""}".`); return; }
    if (picked.some((x) => x.g.driver_id === g.driver_id)) { errors.push(`Line ${n + 1}: ${g.code} is listed twice.`); return; }
    const tt = toks.map(toSeconds).find((x) => x !== null) ?? null;
    picked.push({ g, lap: tt });
  });
  // Unlisted current-grid drivers start at the back, unless their team already
  // has two listed drivers (a stand-in took the seat).
  const perTeam = (team: string) => picked.filter((x) => x.g.team_id === team).length;
  const replaced = grid.filter((g) => !picked.some((x) => x.g.driver_id === g.driver_id) && perTeam(g.team_id) >= 2);
  const missing = grid.filter((g) => !picked.some((x) => x.g.driver_id === g.driver_id) && perTeam(g.team_id) < 2);
  if (replaced.length) notes.push(`Stand-ins: ${replaced.map((g) => `${g.code}'s seat taken by ${picked.filter((x) => x.g.team_id === g.team_id && !grid.some((y) => y.driver_id === x.g.driver_id)).map((x) => x.g.code).join("/")}`).join("; ")}.`);
  if (picked.length && missing.length)
    notes.push(`Not listed, so placed at the back without a time: ${missing.map((g) => g.code).join(", ")}.`);
  const all = [...picked, ...missing.map((g) => ({ g, lap: null }))];
  const best = Math.min(...all.map((x) => x.lap ?? Infinity));
  const withTime = all.filter((x) => x.lap !== null).length;
  if (picked.length && withTime < all.length / 2)
    notes.push("Fewer than half the cars have a lap time, so qualifying gaps are not used; the grid order still is.");
  if (wet) notes.push("Wet qualifying: lap-time gaps are not a pace signal and are ignored; the grid order still is.");
  const entries: GridEntry[] = all.map(({ g, lap }) => ({
    ...g, quali_gap_pct: lap === null || !Number.isFinite(best) ? undefined : 100 * (lap / best - 1), quali_wet: wet,
  }));
  const rows = all.map(({ g, lap }, i) => ({ slot: i + 1, code: g.code, name: g.name, lap,
    gap: lap === null || !Number.isFinite(best) ? null : 100 * (lap / best - 1), listed: i < picked.length }));
  return { entries: picked.length ? entries : [], rows, errors, notes };
}

export interface ActualRow { code: string; pos: number | null; grid: number; status: string }

export interface GridFetch {
  text: string;                       // grid order, "CODE best-lap" per line
  race: string;
  source: "result" | "official" | "qualifying";
  penalties: string[];                // grid differs from qualifying
  warnings: string[];
  actual: ActualRow[] | null;         // the race result, if the race has run
  qualiPos: Record<string, number>;   // qualifying position by driver code
}

const JOLPICA = "https://api.jolpi.ca/ergast/f1";
const OPENF1 = "https://api.openf1.org/v1";

async function getJson(url: string): Promise<any> {
  const r = await fetch(url);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`${new URL(url).host} answered ${r.status}`);
  return r.json();
}

/** OpenF1's official starting grid (penalties applied) for the qualifying
 *  session of the race weekend that ends on raceDate. */
async function openF1Grid(raceDate: string): Promise<{ position: number; driver_number: number; lap_duration: number | null }[] | null> {
  const d = new Date(raceDate + "T00:00:00Z");
  const from = new Date(d.getTime() - 4 * 864e5).toISOString().slice(0, 10);
  const to = new Date(d.getTime() + 864e5).toISOString().slice(0, 10);
  const sessions = await getJson(`${OPENF1}/sessions?session_name=Qualifying&date_start%3E=${from}&date_start%3C=${to}`);
  const key = sessions?.[0]?.session_key;
  if (!key) return null;
  const grid = await getJson(`${OPENF1}/starting_grid?session_key=${key}`);
  return Array.isArray(grid) && grid.length ? grid : null;
}

/** Everything known about a race's grid, checked against each other:
 *  1. race result (after the race): its grid column is the final word;
 *  2. OpenF1 official starting grid (penalties applied), before the race;
 *  3. qualifying order (Jolpica), flagged as "penalties not confirmed".
 *  Lap times are each driver's best Q1/Q2/Q3 lap (the model's definition). */
export async function fetchRaceGrid(year: number, round: number, raceDate: string): Promise<GridFetch | null> {
  const [qj, rj, of] = await Promise.all([
    getJson(`${JOLPICA}/${year}/${round}/qualifying.json`),
    getJson(`${JOLPICA}/${year}/${round}/results.json`),
    openF1Grid(raceDate).catch(() => null),
  ]);
  const qRace = qj?.MRData?.RaceTable?.Races?.[0];
  const rRace = rj?.MRData?.RaceTable?.Races?.[0];
  const quali = (qRace?.QualifyingResults ?? []) as { position: string; number: string; Driver: { code: string }; Q1?: string; Q2?: string; Q3?: string }[];
  const result = (rRace?.Results ?? []) as { position: string; positionText: string; grid: string; number: string; status: string; Driver: { code: string } }[];
  if (!quali.length && !result.length && !of) return null;

  const best = new Map<string, number>(), qPos = new Map<string, number>(), byNumber = new Map<number, string>();
  for (const q of quali) {
    const times = [q.Q1, q.Q2, q.Q3].map((x) => (x ? toSeconds(x) : null)).filter((x): x is number => x !== null);
    if (times.length) best.set(q.Driver.code, Math.min(...times));
    qPos.set(q.Driver.code, Number(q.position));
    byNumber.set(Number(q.number), q.Driver.code);
  }
  for (const r of result) byNumber.set(Number(r.number), r.Driver.code);

  const warnings: string[] = [];
  let order: string[], source: GridFetch["source"];
  const ofOrder = of ? [...of].sort((a, b) => a.position - b.position).map((x) => byNumber.get(x.driver_number) ?? `#${x.driver_number}`) : null;
  if (result.length) {
    // Grid 0 = pit-lane start: behind everyone, in qualifying order.
    order = [...result].sort((a, b) => (Number(a.grid) || 99) - (Number(b.grid) || 99) || (qPos.get(a.Driver.code) ?? 99) - (qPos.get(b.Driver.code) ?? 99)).map((r) => r.Driver.code);
    source = "result";
    if (ofOrder && ofOrder.slice(0, order.length).join() !== order.slice(0, ofOrder.length).join())
      warnings.push("The official starting grid (OpenF1) and the race result's grid differ; the race result is used.");
  } else if (ofOrder) {
    order = ofOrder;
    source = "official";
  } else {
    order = [...quali].sort((a, b) => Number(a.position) - Number(b.position)).map((q) => q.Driver.code);
    source = "qualifying";
    warnings.push("The official starting grid is not published yet: this is the qualifying order. Grid penalties may still change it; check under Edit grid.");
  }
  if (of) for (const x of of) if (!best.has(byNumber.get(x.driver_number) ?? "") && x.lap_duration) best.set(byNumber.get(x.driver_number)!, x.lap_duration);

  // Report the drivers who were moved back or start from the pit lane; the
  // cars that moved up as a result are summarised, not listed.
  const penalties: string[] = [];
  let movedUp = 0;
  order.forEach((code, i) => {
    const qp = qPos.get(code);
    const pitLane = source === "result" && Number(result.find((r) => r.Driver.code === code)?.grid) === 0;
    if (pitLane) penalties.push(`${code} qualified P${qp ?? "?"}, starts from the pit lane`);
    else if (qp && i + 1 > qp) penalties.push(`${code} qualified P${qp}, starts P${i + 1}`);
    else if (qp && i + 1 < qp) movedUp++;
  });
  if (penalties.length && movedUp) penalties.push(`${movedUp} cars moved up accordingly`);

  const actual = result.length ? result.map((r) => ({ code: r.Driver.code, pos: /^\d+$/.test(r.positionText) ? Number(r.position) : null,
    grid: Number(r.grid), status: r.status })) : null;
  const text = order.map((c) => `${c} ${best.has(c) ? formatLap(best.get(c)!) : ""}`.trim()).join("\n");
  return { text, race: `${year} ${(rRace ?? qRace)?.raceName ?? ""}`.trim(), source, penalties, warnings, actual,
    qualiPos: Object.fromEntries(qPos) };
}

export function exampleText(p: Params): { label: string; text: string; track: string | null } | null {
  const e = p.grid.example_quali;
  if (!e) return null;
  const cal = p.grid.calendar.find((c) => e.race.endsWith(c.race_name));
  return { label: e.race, track: cal?.circuit_id ?? null, text: e.rows.map((r) => `${r.code} ${r.best_lap_s ? formatLap(r.best_lap_s) : ""}`.trim()).join("\n") };
}

export function QualiPanel(props: { text: string; onChange: (text: string) => void; parsed: QualiParse }) {
  const { parsed } = props;
  return (
    <div>
      <label class="field"><span>Grid, one driver per line in grid order: code and best lap. Edit to apply grid penalties, or paste a result.</span>
        <textarea rows={8} value={props.text} placeholder={"VER 1:18.792\nNOR 1:18.869\nPIA 1:18.982\n..."}
          style={{ width: "100%", background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "6px 8px", font: "12px var(--mono)", color: "inherit" }}
          onInput={(e) => props.onChange((e.target as HTMLTextAreaElement).value)} />
      </label>
      {parsed.errors.map((e) => <div class="err">{e}</div>)}
      {parsed.notes.map((e) => <div class="hint">{e}</div>)}
      {parsed.rows.length > 0 && <table class="t" style={{ fontSize: "12px" }}>
        <thead><tr><th class="l">Grid</th><th class="l">Driver</th><th>Best lap</th><th>Gap</th></tr></thead>
        <tbody>{parsed.rows.map((r) => (
          <tr style={{ opacity: r.listed ? 1 : 0.55 }}>
            <td class="l">P{r.slot}</td><td class="l">{r.code}</td>
            <td class="mono">{r.lap === null ? "no time" : formatLap(r.lap)}</td>
            <td>{r.gap === null ? "–" : r.gap === 0 ? "pole" : `+${r.gap.toFixed(3)}%`}</td>
          </tr>))}
        </tbody>
      </table>}
    </div>
  );
}
