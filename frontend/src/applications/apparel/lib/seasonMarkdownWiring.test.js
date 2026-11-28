import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The dialog is JSX the test setup cannot render, so the links that matter most are guarded at the
// source: a stale preview must never be confirmable, and the token must travel with what it signed.
// The application tree moved under src/applications/apparel, so a path in these
// tests may be written from the application root, from src, or from the repo
// root. Resolve by trying each, with the application root first.
const read = (rel) => {
  const clean = rel.replace(/^(\.\.\/)+/, "").replace(/^(cashier|apparel)\//, "");
  for (const base of ["../", "../../", "../../../", "../../../../", "../../../../../"]) {
    try {
      return readFileSync(new URL(base + clean, import.meta.url), "utf8");
    } catch {
      // try the next base
    }
  }
  throw new Error(`cannot resolve ${rel}`);
};
const dialog = read("components/inventory/SeasonMarkdownDialog.jsx");
const page = read("routes/_authed/inventory.index.jsx");
const api = read("api/posApi.js");
const hook = read("api/useSeasonMarkdown.js");

describe("the dialog is reachable from the inventory screen", () => {
  it("there is a button that opens it", () => {
    expect(page).toMatch(/onClick=\{\(\) => setMarkdownOpen\(true\)\}/);
    expect(page).toMatch(/تخفيض موسم/);
  });
  it("the dialog gets the shop's own seasons and brands, and its open state", () => {
    const tag = page.match(/<SeasonMarkdownDialog[\s\S]*?\/>/)?.[0] ?? "";
    expect(tag).toMatch(/open=\{markdownOpen\}/);
    expect(tag).toMatch(/onOpenChange=\{setMarkdownOpen\}/);
    expect(tag).toMatch(/seasons=\{seasons\.data \?\? \[\]\}/);
    expect(tag).toMatch(/brands=\{brands\.data \?\? \[\]\}/);
  });
  it("the page imports what it uses", () => {
    expect(page).toMatch(/import SeasonMarkdownDialog from/);
    expect(page).toMatch(/import \{[^}]*\bPercent\b[^}]*\} from "lucide-react"/);
  });
});

describe("a preview can never outlive what it was made for", () => {
  it("editing the season, brand or percent drops the preview", () => {
    expect(dialog).toMatch(/const edit = \(setter\) => \(value\) => \{\s*setter\(value\);\s*preview\.reset\(\);/);
    for (const setter of ["setSeason", "setBrandId", "setPercent"]) {
      expect(dialog).toMatch(new RegExp(`edit\\(${setter}\\)`));
    }
  });
  it("a 409 drops the preview, so the old prices cannot be confirmed again", () => {
    expect(dialog).toMatch(/if \(kind === "stale"\) preview\.reset\(\)/);
  });
  it("closing the dialog clears the preview, the result and the error", () => {
    const close = dialog.match(/const close = [\s\S]*?\n  \};/)?.[0] ?? "";
    expect(close).toMatch(/preview\.reset\(\)/);
    expect(close).toMatch(/apply\.reset\(\)/);
    expect(close).toMatch(/setError\(null\)/);
  });
});

describe("confirming sends the previewed set, and only that", () => {
  it("apply is called with the shown preview and the brand it was made with", () => {
    expect(dialog).toMatch(/apply\.mutate\(\s*\{ preview: shown, brandId \}/);
  });
  it("the confirm button is armed only through canConfirm, and shows the busy state", () => {
    expect(dialog).toMatch(/disabled=\{!canConfirm\(\{ preview: shown, busy \}\)\}/);
    expect(dialog).toMatch(/apply\.isPending \? "جارٍ التنفيذ…" : confirmLabel\(shown\)/);
  });
  it("preview is armed only through canPreview, with the percent checked first", () => {
    expect(dialog).toMatch(/disabled=\{!canPreview\(\{ season, percentValid, busy \}\)\}/);
    expect(dialog).toMatch(/const percentValid = percentText\(percent\) !== null/);
  });
  it("the percent box tells the owner when it is not a valid percent", () => {
    expect(dialog).toMatch(/aria-invalid=\{percent !== "" && !percentValid\}/);
  });
  it("cancel and busy cannot both be pressed mid-request", () => {
    expect(dialog).toMatch(/onClick=\{\(\) => close\(false\)\} disabled=\{busy\}/);
    expect(dialog).toMatch(/const busy = preview\.isPending \|\| apply\.isPending/);
  });
});

describe("the owner sees the danger before confirming", () => {
  it("the under-cost warning, the unknown-cost note and the floor note are shown from the preview totals", () => {
    expect(dialog).toMatch(/belowCostWarning\(shown\.totals\)/);
    expect(dialog).toMatch(/unknownCostNote\(shown\.totals\)/);
    expect(dialog).toMatch(/floorNote\(shown\.totals\)/);
  });
  it("the under-cost warning is an alert, and a stale error is amber not red", () => {
    expect(dialog).toMatch(/role="alert"[^>]*>\{warning\}|\{warning && <p[^>]*role="alert"/);
    expect(dialog).toMatch(/error === "stale" \? "border-amber-300/);
  });
  it("a season with nothing in it says so instead of offering to confirm nothing", () => {
    expect(dialog).toMatch(/shown\.rows\.length === 0/);
    expect(dialog).toMatch(/shown\.rows\.length > 0/);
  });
});

describe("the api client and the hook", () => {
  it("preview and apply go to the two routes", () => {
    expect(api).toMatch(/seasonMarkdownPreview: \(body\) => post\("\/catalog\/season-markdown\/preview", body\)/);
    expect(api).toMatch(/seasonMarkdownApply: \(body\) => post\("\/catalog\/season-markdown\/apply", body\)/);
  });
  it("preview builds its body with previewBody, apply with applyBody", () => {
    expect(hook).toMatch(/shapePreview\(await posApi\.seasonMarkdownPreview\(previewBody\(input\)\)\)/);
    expect(hook).toMatch(/posApi\.seasonMarkdownApply\(applyBody\(p, brandId\)\)/);
  });
  it("after a successful apply every cached price is dropped, not patched by hand", () => {
    expect(hook).toMatch(/onSuccess: \(\) => qc\.invalidateQueries\(\{ queryKey: \["cashier"\] \}\)/);
  });
  it("success tells the owner how many sizes changed and closes the dialog", () => {
    expect(dialog).toMatch(/toast\.success\(appliedMessage\(result\)\)/);
    expect(dialog).toMatch(/close\(false\)/);
  });
});
