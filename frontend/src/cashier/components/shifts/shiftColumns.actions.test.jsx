import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import shiftColumns from "./shiftColumns";

const actionsCell = (row) => {
  const col = shiftColumns({ onClose() {}, onDetails() {}, onReport() {} }).find((c) => c.key === "actions");
  return renderToStaticMarkup(col.render(row));
};

// On a narrow screen the day-close button ran past the table edge and was cut off. The buttons must wrap
// inside their cell instead, so the one that closes the day is always reachable.
describe("shift actions cell", () => {
  it("lets the buttons wrap instead of running past the cell", () => {
    expect(actionsCell({ status: "open" })).toMatch(/class="flex flex-wrap /);
  });
  it("offers the day-close button only for an open shift", () => {
    expect(actionsCell({ status: "open" })).toContain("إغلاق الوردية");
    expect(actionsCell({ status: "closed" })).not.toContain("إغلاق الوردية");
  });
});
