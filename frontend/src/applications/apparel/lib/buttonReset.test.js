import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../../../index.css", import.meta.url), "utf8");

// The site's old "button{border:0;background:none}" reset sat OUTSIDE every @layer, so it beat Tailwind's utilities on
// every button: a picked colour or size looked the same as an unpicked one, the sizes had no button outline, and the
// "+ category" buttons floated bare. Inside @layer base, utilities win again.
describe("the global button reset does not beat utility classes", () => {
  it("exists exactly once", () => {
    expect(css.split("button{border:0;background:none").length - 1).toBe(1);
  });

  it("sits inside @layer base", () => {
    const at = css.indexOf("button{border:0;background:none");
    const before = css.slice(0, at);
    const open = before.lastIndexOf("@layer base{");
    expect(open).toBeGreaterThan(-1);
    let depth = 0;
    for (const ch of before.slice(open)) {
      if (ch === "{") depth += 1;
      if (ch === "}") depth -= 1;
    }
    expect(depth).toBe(1); // still inside the layer when the rule starts
  });
});
