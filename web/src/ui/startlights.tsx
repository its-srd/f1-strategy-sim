// Start lights for a running simulation: five columns of red lamps light
// one by one as the batch progresses, and go out together when the result
// arrives. It is the progress bar, drawn as the thing every fan knows.

export function StartLights(props: { progress: number; out: boolean; phase?: string; races: number }) {
  const lit = props.out ? 0 : Math.min(5, Math.floor(props.progress * 5) + 1);
  const pc = Math.round(props.progress * 100);
  return (
    <div class={`lights ${props.out ? "out" : ""}`} role="status" aria-live="polite">
      <div class="gantry" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((k) => (
          <div class={`col ${k < lit ? "on" : ""}`}><i class="lamp" /><i class="lamp" /></div>
        ))}
      </div>
      <div class="txt">
        {props.out ? "Lights out" : "Simulating"}
        <small>{props.out ? "results below" : `${props.phase ?? "preparing"} · ${props.races.toLocaleString()} races`}</small>
      </div>
      <div class="pc">{props.out ? "100%" : `${pc}%`}</div>
    </div>
  );
}
