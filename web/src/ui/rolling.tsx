// Rolling digits, like a timing board: each digit is a strip of 0–9 that
// slides to its value. Non-digits ("P", ".", "%") are printed as they are.
// The strip starts at 0 and rolls on the next frame, so a new result always
// rolls in; under reduced motion CSS makes the move instant.
import { useEffect, useState } from "preact/hooks";

const DIGITS = "0123456789";

export function Rolling({ text, label }: { text: string; label?: string }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setReady(true)));
    return () => cancelAnimationFrame(id);
  }, []);
  const chars = [...text];
  let k = 0;
  return (
    <span class="roll" aria-label={label ?? text} role="img">
      {chars.map((c) => {
        if (!/[0-9]/.test(c)) return <span aria-hidden="true">{c}</span>;
        const d = Number(c);
        return (
          <span class="d" aria-hidden="true">
            <span style={{ "--k": k++, transform: `translateY(-${ready ? d : 0}em)` }}>
              {[...DIGITS].map((x) => <span>{x}</span>)}
            </span>
          </span>
        );
      })}
    </span>
  );
}
