import { describe, expect, it } from "vitest";
import { productsPageQuery } from "@/applications/apparel/api/catalogApi";

// الاستعلام اللي الشاشة بتبعته للسيرفر: البحث والفلترة والترقيم، مش تحميل الكتالوج كله.
describe("productsPageQuery", () => {
  it("carries the search, the filters and the page window", () => {
    const q = new URLSearchParams(
      productsPageQuery({
        term: " تيشيرت ",
        status: "active",
        categoryId: "c1",
        brandId: "b1",
        season: "SS26",
        sort: "name",
        limit: 50,
        offset: 100,
      }),
    );
    expect(q.get("q")).toBe("تيشيرت");
    expect(q.get("status")).toBe("active");
    expect(q.get("category_id")).toBe("c1");
    expect(q.get("brand_id")).toBe("b1");
    expect(q.get("season")).toBe("SS26");
    expect(q.get("sort")).toBe("name");
    expect(q.get("limit")).toBe("50");
    expect(q.get("offset")).toBe("100");
  });

  it("sends only the window when nothing is filtered", () => {
    const q = new URLSearchParams(productsPageQuery({ term: "   " }));
    expect(q.get("q")).toBeNull();
    expect(q.get("status")).toBeNull();
    expect(q.get("limit")).toBe("50");
    expect(q.get("offset")).toBe("0");
  });
});
