import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const here = path.dirname(fileURLToPath(import.meta.url));

// Unit tests live next to the code (src/**/*.test.js). Playwright owns e2e/:
// without this, vitest picks up e2e/*.spec.js and dies on the Playwright runtime.
export default defineConfig({
  resolve: { alias: { "@": path.resolve(here, "src") } },
  test: {
    include: ["src/**/*.test.{js,jsx}"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    environment: "node",
  },
});
