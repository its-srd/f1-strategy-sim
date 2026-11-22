import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

// Static build: relative base so dist/ can be hosted from any path.
export default defineConfig({
  base: "./",
  plugins: [preact()],
  cacheDir: "node_modules/.vite",
  worker: { format: "es" },
  server: { port: 5178, strictPort: true },
});
