/**
 * ESLint flat config (ESLint 9).
 *
 * The gate is deliberately the stock Next.js ruleset — `next/core-web-vitals`
 * plus `next/typescript` — because those are the rules the framework itself
 * enforces and the ones a reviewer expects to see. Rule-level tuning lives in
 * the override block below, not by dropping whole plugins.
 */

import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({ baseDirectory: __dirname });

const config = [
  {
    ignores: [
      ".next/**",
      ".next.stale/**",
      "node_modules/**",
      "next-env.d.ts",
      "playwright-report/**",
      "test-results/**",
      "blob-report/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default config;
