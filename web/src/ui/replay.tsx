// Race replay: the representative simulated race as a timing tower next to
// a lap chart. Positions come from each car's gap to the leader at the end
// of every lap. Tower rows slide to their new place, the arrows count
// places gained or lost since lap 1, tyres show compound (age on hover), a
// PIT tag marks the stop lap, the scrubber shows SC / VSC / red laps, and
// the winner's row gets the chequered flag on the last lap. It starts by
// itself the first time it is scrolled into view, unless the visitor
// prefers reduced motion.
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { Compound } from "../engine/types.ts";
import { COMPOUND_COLOR, COMPOUND_LETTER } from "./charts.tsx";
import { LapChart } from "./lapchart.tsx";
import { prefersReducedMotion, useInView } from "./motion.ts";

export interface ReplayRow { code: string; user: boolean; dnf: boolean; gaps: number[]; stints: { compound: Compound; from: number; to: number }[]; color?: string; emphasis?: boolean }

const ROW = 26;
const LAPS_PER_SECOND = 1.6;
const STATUS_LABEL = ["", "Safety car", "Virtual safety car", "Red flag"];

/** Running order at the end of every lap: position (1-based) per car, NaN once out. */
function positions(rows: ReplayRow[], laps: number): Map<string, number[]> {
  const out = new Map(rows.map((r) => [r.code, new Array<number>(laps).fill(NaN)]));
  for (let i = 0; i < laps; i++) {
    rows.filter((r) => Number.isFinite(r.gaps[i])).sort((a, b) => a.gaps[i] - b.gaps[i])
      .forEach((r, k) => { out.get(r.code)![i] = k + 1; });
  }
  return out;
}

export function RaceReplay(props: { rows: ReplayRow[]; laps: number; status: number[]; focus: string | null; onFocus: (code: string | null) => void }) {
  const { rows, laps, status } = props;
  const reduced = prefersReducedMotion();
  const [lap, setLap] = useState(reduced ? laps : 1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [ref, seen] = useInView<HTMLDivElement>(0.3);
  const clock = useRef<{ t: number; lap: number } | null>(null);
  const pos = useMemo(() => positions(rows, laps), [rows, laps]);

  // Play once automatically when first seen.
  useEffect(() => { if (seen && !reduced) { setLap(1); setPlaying(true); } }, [seen]);

  useEffect(() => {
    if (!playing) { clock.current = null; return; }
    let raf = 0;
    const tick = (now: number) => {
      if (!clock.current) clock.current = { t: now, lap };
      const next = clock.current.lap + ((now - clock.current.t) / 1000) * LAPS_PER_SECOND * speed;
      if (next >= laps) { setLap(laps); setPlaying(false); return; }
      setLap(Math.max(1, Math.floor(next)));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed]);

  const view = useMemo(() => {
    const i = lap - 1;
    const running = rows.filter((r) => Number.isFinite(r.gaps[i]));
    const out = rows.filter((r) => !Number.isFinite(r.gaps[i]));
    // retired cars at the back, the last to retire first
    const lastLap = (r: ReplayRow) => { let k = r.gaps.length - 1; while (k >= 0 && !Number.isFinite(r.gaps[k])) k--; return k; };
    running.sort((a, b) => a.gaps[i] - b.gaps[i]);
    out.sort((a, b) => lastLap(b) - lastLap(a));
    const maxGap = Math.max(5, ...running.map((r) => r.gaps[i]));
    return [...running, ...out].map((r, k) => {
      const st = r.stints.find((s) => s.from <= lap && lap <= (s.to || laps)) ?? r.stints[r.stints.length - 1];
      const pit = r.stints.some((s, j) => j < r.stints.length - 1 && s.to === lap);
      const g = r.gaps[i];
      const start = pos.get(r.code)?.[0];
      const moved = Number.isFinite(g) && start !== undefined && Number.isFinite(start) ? start - (k + 1) : 0;
      return { r, k, out: !Number.isFinite(g), gap: g, share: Number.isFinite(g) ? g / maxGap : 0, tyre: st, age: lap - st.from + 1, pit, moved };
    });
  }, [rows, lap, laps, pos]);

  // Stable DOM order (by code) so each row keeps its element and slides.
  const byCode = useMemo(() => rows.map((r) => r.code), [rows]);
  const place = new Map(view.map((v) => [v.r.code, v]));
  const flag = status[lap - 1] ?? 0;
  const done = lap >= laps;
  const toggle = () => { if (lap >= laps) setLap(1); setPlaying((p) => !p); clock.current = null; };

  return (
    <div class="replay" ref={ref}>
      <div class="replay-bar">
        <button class="play" onClick={toggle} aria-label={playing ? "Pause replay" : "Play replay"}>
          {playing
            ? <svg width="14" height="14" viewBox="0 0 14 14"><rect x="2" y="1" width="3.5" height="12" fill="currentColor" /><rect x="8.5" y="1" width="3.5" height="12" fill="currentColor" /></svg>
            : <svg width="14" height="14" viewBox="0 0 14 14"><path d="M3 1.5v11l9.5-5.5z" fill="currentColor" /></svg>}
        </button>
        <div class="lapno">Lap {lap}<small>/ {laps}</small></div>
        <div class="scrub">
          <div class="bands">{status.map((s, j) => s ? <i style={{ left: `${(j / laps) * 100}%`, width: `${100 / laps}%`, background: s === 3 ? "var(--c-soft)" : s === 2 ? "rgba(242,183,5,0.55)" : "var(--c-medium)" }} /> : null)}</div>
          <div class="fill" style={{ width: `${((lap - 1) / Math.max(1, laps - 1)) * 100}%` }} />
          <input type="range" min={1} max={laps} value={lap} aria-label="Lap"
            onInput={(e) => { setPlaying(false); setLap(Number((e.target as HTMLInputElement).value)); }} />
        </div>
        <div class="speed" role="group" aria-label="Replay speed">
          {[1, 2, 4].map((v) => <button class={speed === v ? "on" : ""} onClick={() => { clock.current = null; setSpeed(v); }}>{v}×</button>)}
        </div>
      </div>
      <div class="flag-row">
        {flag ? <span class={`flag-badge ${flag === 3 ? "red" : ""}`}>{STATUS_LABEL[flag]}</span> : done ? <><span class="flag-badge chequer" aria-hidden="true">·</span><span>Chequered flag · {view[0]?.r.code} wins</span></> : <span>Green flag</span>}
      </div>
      <div class="replay-body">
        <div>
        <div class="lapchart-caption"><span>Timing tower · end of lap {lap}</span><span>▲▼ since lap 1</span></div>
        <div class="tower" style={{ height: `${rows.length * ROW}px` }} onMouseLeave={() => props.onFocus(null)}>
          {byCode.map((code) => {
            const v = place.get(code)!;
            const cls = ["car", v.r.user ? "user" : "", v.out ? "out" : "", props.focus === code ? "focus" : "", done && v.k === 0 ? "chequer" : ""].join(" ");
            return (
              <div class={cls} style={{ transform: `translateY(${v.k * ROW}px)` }} onMouseEnter={() => props.onFocus(code)}>
                <span class="pos">{v.k + 1}</span>
                <span class="code">{code}{v.pit && <span class="pit">PIT</span>}</span>
                <span class={`delta ${v.moved > 0 ? "up" : v.moved < 0 ? "down" : ""}`} title="Places gained or lost since lap 1">{v.moved > 0 ? `▲${v.moved}` : v.moved < 0 ? `▼${-v.moved}` : ""}</span>
                <span class="tyre" title={`${v.tyre.compound.toLowerCase()}, ${v.age} laps old`} style={{ color: COMPOUND_COLOR[v.tyre.compound] }}>{COMPOUND_LETTER[v.tyre.compound]}</span>
                <span class="gapbar"><i style={{ width: `${Math.max(v.out ? 0 : 1.5, v.share * 100)}%` }} /></span>
                <span class="gap">{v.out ? "OUT" : v.k === 0 ? "LEADER" : `+${v.gap.toFixed(1)}`}</span>
              </div>
            );
          })}
        </div>
        </div>
        <div>
          <div class="lapchart-caption"><span>Lap chart · position at the end of each lap</span><span>hover a line</span></div>
          <LapChart rows={rows} pos={pos} laps={laps} lap={lap} rowH={ROW} focus={props.focus} onFocus={props.onFocus} />
        </div>
      </div>
    </div>
  );
}
