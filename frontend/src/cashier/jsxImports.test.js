import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A component used in JSX but never imported only crashes when that branch renders, such as the
 * error line shown after scanning an unknown barcode. Unit tests rarely reach those branches, so
 * this checks every cashier file: each capitalised JSX tag must be imported or defined in the file.
 */
function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return path.endsWith(".jsx") && !path.endsWith(".test.jsx") ? [path] : [];
  });
}

const GLOBAL_TAGS = new Set(["Fragment", "Suspense", "StrictMode"]);

function undeclaredTags(source) {
  const used = new Set([...source.matchAll(/<([A-Z][A-Za-z0-9]*)[\s/>.]/g)].map((m) => m[1]));
  const declared = new Set();
  for (const m of source.matchAll(/import\s+([^;]+?)\s+from\s+["'][^"']+["']/gs)) {
    for (const part of m[1].replace(/[{}]/g, ",").split(",")) {
      // "* as X", "A as B" and plain names all declare the LAST identifier.
      const name = part.trim().split(/\s+as\s+/).pop().replace(/^\*\s*/, "").trim();
      if (name) declared.add(name);
    }
  }
  for (const m of source.matchAll(/(?:function|const|let|class)\s+([A-Z][A-Za-z0-9]*)/g)) declared.add(m[1]);
  // props renamed on destructuring ("icon: Icon") and locals chosen at render time ("TrendIcon = ...")
  for (const m of source.matchAll(/:\s*([A-Z][A-Za-z0-9]*)\s*[,}=]/g)) declared.add(m[1]);
  for (const m of source.matchAll(/\b([A-Z][A-Za-z0-9]*)\s*=[^=>]/g)) declared.add(m[1]);
  return [...used].filter((tag) => !declared.has(tag) && !GLOBAL_TAGS.has(tag));
}

describe("every component used in cashier JSX is imported", () => {
  it("detects a missing import", () => {
    expect(undeclaredTags('import { A } from "x";\nconst v = <A /> ;\nconst w = <Icon />;')).toEqual(["Icon"]);
  });

  for (const file of files(join(process.cwd(), "src/cashier"))) {
    it(file.split("src/cashier/")[1], () => {
      expect(undeclaredTags(readFileSync(file, "utf8"))).toEqual([]);
    });
  }
});
