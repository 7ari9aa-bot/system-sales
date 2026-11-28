import { describe, expect, it } from "vitest";
import { reportLines, reportTone, zipFileProblem } from "./imageZipReport";

const ok = { matched: [{ sku: "TEE-M" }, { sku: "TEE-M" }, { sku: "JNS-32" }], stats: { attached: 3 } };

describe("the image folder report", () => {
  it("says how many pictures landed on how many SKUs", () => {
    expect(reportLines(ok)[0]).toBe("اتربطت 3 صورة على 2 صنف");
    expect(reportTone(ok)).toBe("good");
  });

  it("names the SKUs the shop does not have, and the files that are not pictures", () => {
    const lines = reportLines({
      matched: [{ sku: "TEE-M" }],
      unknown_skus: ["GHOST-1", "GHOST-2"],
      not_pictures: ["readme.txt"],
      stats: { attached: 1, unknown: 2, not_pictures: 1 },
    });
    expect(lines.join(" | ")).toContain("GHOST-1، GHOST-2");
    expect(lines.join(" | ")).toContain("readme.txt");
  });

  it("is honest when nothing was attached at all", () => {
    const report = { matched: [], unknown_skus: ["X"], stats: { attached: 0, unknown: 1 } };
    expect(reportTone(report)).toBe("bad");
    expect(reportLines(report).join(" ")).toContain("X");
    expect(reportLines({ matched: [], stats: {} })[0]).toContain("اسم الملف = SKU");
  });

  it("refuses the wrong file before uploading", () => {
    expect(zipFileProblem(null)).toContain("اختر");
    expect(zipFileProblem({ name: "photos.rar", size: 10 })).toContain(".zip");
    expect(zipFileProblem({ name: "photos.zip", size: 0 })).toContain("فاضي");
    expect(zipFileProblem({ name: "photos.zip", size: 1024 })).toBeNull();
  });
});
