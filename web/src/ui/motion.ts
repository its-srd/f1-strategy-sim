// Small motion helpers. Every animation respects the visitor's
// "reduce motion" setting: numbers then jump straight to their value and
// nothing plays by itself.
import { useEffect, useRef, useState } from "preact/hooks";

export function prefersReducedMotion(): boolean {
  return typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

const easeOut = (t: number) => 1 - (1 - t) ** 3;

/** A number that counts from where it was to `target` (from 0 the first time). */
export function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(prefersReducedMotion() ? target : 0);
  const from = useRef(prefersReducedMotion() ? target : 0);
  useEffect(() => {
    if (prefersReducedMotion() || !Number.isFinite(target)) { setValue(target); from.current = target; return; }
    const start = performance.now(), a = from.current;
    let raf = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const v = a + (target - a) * easeOut(t);
      setValue(v);
      if (t < 1) raf = requestAnimationFrame(step);
      else from.current = target;
    };
    raf = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf); from.current = target; };
  }, [target, duration]);
  return value;
}

/** True once the element has been on screen (for things that start when seen). */
export function useInView<T extends Element>(threshold = 0.35): [preact.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect(); }
    }, { threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [seen, threshold]);
  return [ref, seen];
}
