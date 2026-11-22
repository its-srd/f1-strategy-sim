// Optional explanation proxy for the F1 Strategy Simulator.
//
// The static site POSTs a JSON summary of a finished simulation here; this
// server asks Claude to explain it in plain language and returns the text.
// The API key stays on this server (ANTHROPIC_API_KEY or an `ant auth login`
// profile), never in the browser.
//
// Claude only interprets the numbers it is given (project principle 5): the
// system prompt forbids new predictions, and the simulator's output is the
// only data in the request.
//
// Run:   cd web/server && npm install && ALLOWED_ORIGIN=http://localhost:5178 npm start
// Build the site with VITE_EXPLAIN_URL=http://localhost:8787/explain to show the panel.

import Anthropic from "@anthropic-ai/sdk";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

const PORT = Number(process.env.PORT ?? 8787);
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN ?? "http://localhost:5178";
const MAX_BODY = 64 * 1024;                 // summaries are a few KB
const PER_IP_PER_HOUR = Number(process.env.RATE_LIMIT ?? 30);

const client = new Anthropic();

const SYSTEM = `You explain the output of an F1 race-strategy Monte Carlo simulator to technical F1 fans.

Rules:
- Use only the numbers in the JSON you are given. Do not add facts, form, news, or your own predictions about drivers, teams or races.
- The simulator's output is probabilities, never certainties. Never say a driver "will" win; describe chances and uncertainty.
- Explain what drives the result: grid slot, car vs driver pace (percent of lap time, negative = faster, with SD), retirement risk, safety-car/VSC frequency, and the time breakdown of the user's strategy versus the best alternative (pit, tyre, dirty air, held up).
- If the best alternative's gain is within its uncertainty, say the two are not distinguishable.
- Mention any warnings in the JSON.
- 150-250 words, plain prose, no headings.`;

const hits = new Map<string, number[]>();
function rateLimited(ip: string): boolean {
  const now = Date.now(), hour = 3600_000;
  const recent = (hits.get(ip) ?? []).filter((t) => now - t < hour);
  recent.push(now);
  hits.set(ip, recent);
  return recent.length > PER_IP_PER_HOUR;
}

function send(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, {
    "content-type": "application/json",
    "access-control-allow-origin": ALLOWED_ORIGIN,
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type",
  });
  res.end(JSON.stringify(body));
}

async function readBody(req: IncomingMessage): Promise<string> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const c of req) {
    size += (c as Buffer).length;
    if (size > MAX_BODY) throw new Error("body too large");
    chunks.push(c as Buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function explain(summary: unknown): Promise<string> {
  const response = await client.beta.messages.create({
    model: "claude-opus-5-5",
    max_tokens: 4000,                         // short prose answer
    output_config: { effort: "low" },        // interpretation of given numbers, not open reasoning
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",                     // re-run on a fallback model if a safety classifier declines
    system: SYSTEM,
    messages: [{ role: "user", content: `Simulation summary (JSON):\n${JSON.stringify(summary)}` }],
  });
  if (response.stop_reason === "refusal") throw new Error("The explanation request was declined.");
  return response.content.flatMap((b) => (b.type === "text" ? [b.text] : [])).join("\n").trim();
}

createServer(async (req, res) => {
  if (req.method === "OPTIONS") return send(res, 204, {});
  if (req.method !== "POST" || req.url !== "/explain") return send(res, 404, { error: "not found" });
  if (req.headers.origin && req.headers.origin !== ALLOWED_ORIGIN) return send(res, 403, { error: "origin not allowed" });
  const ip = req.socket.remoteAddress ?? "?";
  if (rateLimited(ip)) return send(res, 429, { error: "rate limit reached, try later" });
  try {
    const body = JSON.parse(await readBody(req));
    if (!body || typeof body.summary !== "object") return send(res, 400, { error: "expected {summary: {...}}" });
    send(res, 200, { text: await explain(body.summary) });
  } catch (err) {
    if (err instanceof Anthropic.RateLimitError) return send(res, 429, { error: "Claude API rate limit, try again shortly" });
    if (err instanceof Anthropic.AuthenticationError) return send(res, 500, { error: "proxy has no valid Anthropic credentials" });
    if (err instanceof Anthropic.APIError) return send(res, 502, { error: `Claude API error ${err.status}` });
    send(res, 400, { error: String((err as Error).message ?? err) });
  }
}).listen(PORT, () => console.log(`explain proxy on http://localhost:${PORT}/explain (origin ${ALLOWED_ORIGIN})`));
