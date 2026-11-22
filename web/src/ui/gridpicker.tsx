// The starting grid seen from above: two staggered columns of grid boxes,
// pole at the top left. Click a box to start your driver there. After
// qualifying every box shows the driver in it, so moving your car visibly
// pushes the others back one place; "Q" marks your real grid slot.

export function GridPicker(props: { slots: number; selected: number; codes?: (string | null)[]; you: string; realSlot?: number; onPick: (slot: number) => void }) {
  const { slots, selected, codes, you, realSlot } = props;
  return (
    <div class="gridpick">
      <div class="lanes" role="group" aria-label="Starting grid">
        {Array.from({ length: slots }, (_, i) => {
          const slot = i + 1, on = slot === selected;
          const code = on ? you : codes?.[i] ?? "";
          return (
            <button class={`slot ${on ? "on" : ""} ${slot === realSlot ? "real" : ""}`} aria-pressed={on} aria-label={`Start P${slot}${code ? `, ${code}` : ""}`}
              onClick={() => props.onPick(slot)}>
              <span>P{slot}</span><em>{code}</em>
            </button>
          );
        })}
      </div>
      <div class="legend-line"><span>Click a box to start there</span>{realSlot ? <span>Q = real grid slot</span> : <span>Pole at top left</span>}</div>
    </div>
  );
}
