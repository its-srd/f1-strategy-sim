// Race replay: the representative simulated race as a live timing tower.
// Positions come from each car's gap to the leader at the end of every lap;
// rows slide to their new place (CSS transform), tyres show compound and
// age, a PIT tag marks the stop lap, and the scrubber shows SC / VSC / red
// laps. It starts by itself the first time it is scrolled into view, unless
// the visitor prefers reduced motion.
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { Compound } from "../engine/types.ts";
import { COMPOUND_COLOR, COMPOUND_LETTER } from "./charts.tsx";
import { prefersReducedMotion, useInView } from "./motion.ts";

export interface ReplayRow { code: string; user: boolean; dnf: boolean; gaps: number[]; stints: { compound: Compound; from: number; to: number }[] }

const ROW = 30;
const LAPS_PER_SECOND = 1.6;
const STATUS_LABEL = ["", "Safety car", "Virtual safety car", "Red flag"];

export function RaceReplay(props: { rows: ReplayRow[]; laps: number; status: number[]; focus: string | null; onFocus: (code: string | null) => void }) {
  const { rows, laps, status } = props;
  const reduced = prefersReducedMotion();
  const [lap, setLap] = useState(reduced ? laps : 1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [ref, seen] = useInView<HTMLDivElement>(0.3);
  const clock = useRef<{ t: number; lap: number } | null>(null);

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
    const order = [...running, ...out];
    return order.map((r, k) => {
      const st = r.stints.find((s) => s.from <= lap && lap <= (s.to || laps)) ?? r.stints[r.stints.length - 1];
      const pit = r.stints.some((s, j) => j < r.stints.length - 1 && s.to === lap);
      const g = r.gaps[i];
      return { r, k, out: !Number.isFinite(g), gap: g, share: Number.isFinite(g) ? g / maxGap : 0, tyre: st, age: lap - st.from + 1, pit };
    });
  }, [rows, lap, laps]);

  // Stable DOM order (by code) so each row keeps its element and slides.
  const byCode = useMemo(() => [...rows].map((r) => r.code), [rows]);
  const place = new Map(view.map((v) => [v.r.code, v]));
  const flag = status[lap - 1] ?? 0;
  const toggle = () => { if (lap >= laps) setLap(1); setPlaying((p) => !p); clock.current = null; };

  return (
    <div class="replay" ref={ref}>
      <div class="replay-bar">
        <button class="play" onClick={toggle} aria-label={playing ? "Pause replay" : "Play replay"}>
          {playing
            ? <svg width="14" height="14" viewBox="0 0 14 14"><rect x="2" y="1" width="3.5" height="12" rx="1" fill="currentColor" /><rect x="8.5" y="1" width="3.5" height="12" rx="1" fill="currentColor" /></svg>
            : <svg width="14" height="14" viewBox="0 0 14 14"><path d="M3 1.5v11l9.5-5.5z" fill="currentColor" /></svg>}
        </button>
        <div class="lapno">Lap {lap}<small>/ {laps}</small></div>
        <div class="scrub">
          <div class="bands">{status.map((s, j) => s ? <i style={{ left: `${(j / laps) * 100}%`, width: `${100 / laps}%`, background: s === 3 ? "var(--c-soft)" : s === 2 ? "rgba(240,162,11,0.55)" : "var(--c-medium)" }} /> : null)}</div>
          <div class="fill" style={{ width: `${((lap - 1) / Math.max(1, laps - 1)) * 100}%` }} />
          <input type="range" min={1} max={laps} value={lap} aria-label="Lap"
            onInput={(e) => { setPlaying(false); setLap(Number((e.target as HTMLInputElement).value)); }} />
        </div>
        <div class="speed" role="group" aria-label="Replay speed">
          {[1, 2, 4].map((v) => <button class={speed === v ? "on" : ""} onClick={() => { clock.current = null; setSpeed(v); }}>{v}×</button>)}
        </div>
      </div>
      <div style={{ minHeight: "22px" }}>{flag ? <span class={`flag ${flag === 3 ? "red" : ""}`}>● {STATUS_LABEL[flag]}</span> : null}</div>
      <div class="tower" style={{ height: `${rows.length * ROW}px` }} onMouseLeave={() => props.onFocus(null)}>
        {byCode.map((code) => {
          const v = place.get(code)!;
          const cls = ["car", v.r.user ? "user" : "", v.out ? "out" : "", props.focus === code ? "focus" : ""].join(" ");
          return (
            <div class={cls} style={{ transform: `translateY(${v.k * ROW}px)` }} onMouseEnter={() => props.onFocus(code)}>
              <span class="pos">P{v.k + 1}</span>
              <span class="code">{code}{v.pit && <span class="pit">PIT</span>}</span>
              <span class="tyre" title={`${v.tyre.compound.toLowerCase()}, ${v.age} laps old`} style={{ background: COMPOUND_COLOR[v.tyre.compound] }}>{COMPOUND_LETTER[v.tyre.compound]}</span>
              <span class="gapbar"><i style={{ width: `${Math.max(v.out ? 0 : 1.5, v.share * 100)}%` }} /></span>
              <span class="gap">{v.out ? "OUT" : v.k === 0 ? "Leader" : `+${v.gap.toFixed(1)}`}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
