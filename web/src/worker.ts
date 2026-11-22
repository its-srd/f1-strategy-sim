// Web Worker: runs the Monte Carlo off the main thread.
import { runMonteCarlo } from "./engine/montecarlo.ts";
import type { Params, Scenario } from "./engine/types.ts";

let params: Params | null = null;
const ctx = self as unknown as { onmessage: ((e: MessageEvent) => void) | null; postMessage: (m: unknown) => void };

ctx.onmessage = (e: MessageEvent) => {
  const msg = e.data as { type: "params"; params: Params } | { type: "run"; scenario: Scenario; id: number };
  if (msg.type === "params") { params = msg.params; return; }
  if (msg.type === "run") {
    try {
      const res = runMonteCarlo(params!, msg.scenario, (done, total, phase) => ctx.postMessage({ type: "progress", id: msg.id, done, total, phase }));
      ctx.postMessage({ type: "result", id: msg.id, result: res });
    } catch (err) {
      ctx.postMessage({ type: "error", id: msg.id, error: String((err as Error).message ?? err) });
    }
  }
};
