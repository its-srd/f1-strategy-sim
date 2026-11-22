// The strategy as a strip across the race distance. Drag a pit marker to
// move the stop (or focus it and use the arrow keys, Shift for 5 laps);
// click a stint to change its tyre (soft → medium → hard). A hatched stint
// is longer than the 95th-percentile stint teams have run on that compound
// since 2022.
import { useRef, useState } from "preact/hooks";
import { DRY, type Dry } from "../engine/types.ts";
import { COMPOUND_COLOR, COMPOUND_LETTER } from "./charts.tsx";

export function StintStrip(props: { stints: { compound: Dry; laps: number }[]; laps: number; caps?: Record<Dry, number>; onPit: (k: number, lap: number) => void; onCompound: (k: number, c: Dry) => void }) {
  const { stints, laps, caps } = props;
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const pits: number[] = [];
  stints.reduce((acc, s, i) => { acc += s.laps; if (i < stints.length - 1) pits.push(acc); return acc; }, 0);
  const at = (lap: number) => `${(100 * lap) / laps}%`;
  const clamp = (k: number, lap: number) => Math.max((k ? pits[k - 1] : 0) + 1, Math.min((k < pits.length - 1 ? pits[k + 1] : laps) - 1, Math.round(lap)));
  const move = (k: number, lap: number) => { const v = clamp(k, lap); if (v !== pits[k]) props.onPit(k, v); };
  const fromPointer = (e: PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return ((e.clientX - r.left) / r.width) * laps;
  };
  const ticks = [1, Math.round(laps / 4), Math.round(laps / 2), Math.round((3 * laps) / 4), laps];
  let from = 0;
  return (
    <div class="strip" ref={ref}
      onPointerMove={(e) => { if (drag !== null) move(drag, fromPointer(e as PointerEvent)); }}
      onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}>
      {stints.map((s, k) => {
        const left = from; from += s.laps;
        const over = !!caps && s.laps > caps[s.compound];
        const next = DRY[(DRY.indexOf(s.compound) + 1) % DRY.length];
        return (
          <button key={`${k}-${s.compound}`} class={`st flash ${over ? "over" : ""}`} style={{ left: at(left), width: at(s.laps), "--c": COMPOUND_COLOR[s.compound] }}
            title={`Stint ${k + 1}: ${s.compound.toLowerCase()}, laps ${left + 1}–${left + s.laps} (${s.laps})${over ? `, longer than the ${caps![s.compound]}-lap cap` : ""}. Click for ${next.toLowerCase()}.`}
            aria-label={`Stint ${k + 1}, ${s.compound.toLowerCase()}, ${s.laps} laps. Click to change to ${next.toLowerCase()}.`}
            onClick={() => props.onCompound(k, next)}>
            {COMPOUND_LETTER[s.compound]}{s.laps / laps > 0.13 && <small>{s.laps}</small>}
          </button>
        );
      })}
      {pits.map((lap, k) => (
        <div class={`handle ${drag === k ? "drag" : ""}`} style={{ left: at(lap) }} tabIndex={0} role="slider"
          aria-label={`Pit stop ${k + 1}`} aria-valuemin={1} aria-valuemax={laps - 1} aria-valuenow={lap} aria-valuetext={`end of lap ${lap}`}
          onPointerDown={(e) => { e.preventDefault(); (ref.current as HTMLDivElement).setPointerCapture((e as PointerEvent).pointerId); setDrag(k); }}
          onKeyDown={(e) => {
            const step = e.shiftKey ? 5 : 1;
            if (e.key === "ArrowLeft" || e.key === "ArrowDown") { e.preventDefault(); move(k, lap - step); }
            if (e.key === "ArrowRight" || e.key === "ArrowUp") { e.preventDefault(); move(k, lap + step); }
          }}>
          <b>PIT L{lap}</b>
        </div>
      ))}
      <div class="ticks" aria-hidden="true">{ticks.map((v) => <i style={{ left: at(v === 1 ? 0 : v) }}>{v === 1 ? "L1" : v}</i>)}</div>
    </div>
  );
}
