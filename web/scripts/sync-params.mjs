// Copy fitted parameters (data/params) and the assumptions doc into public/.
import { cpSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const out = join(here, "..", "public", "params");
mkdirSync(out, { recursive: true });
for (const f of readdirSync(join(root, "data", "params"))) if (f.endsWith(".json") && !f.startsWith("_")) cpSync(join(root, "data", "params", f), join(out, f));
for (const doc of ["assumptions.md", "backtest.md", "live_record.md"].filter((d) => existsSync(join(root, "docs", d)))) cpSync(join(root, "docs", doc), join(here, "..", "public", doc));
console.log("params synced");
