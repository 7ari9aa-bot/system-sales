import { describe, expect, it } from "vitest";
import { mappingBody, mergedMapping, stepOf } from "./importFlow";

describe("stepOf", () => {
  it("starts at upload when there is no session", () => {
    expect(stepOf(null)).toBe("upload");
    expect(stepOf(undefined)).toBe("upload");
  });
  it("follows the server's status", () => {
    const at = (status) => stepOf({ status });
    expect(at("analyzed")).toBe("mapping");
    expect(at("mapped")).toBe("mapping");
    expect(at("validating")).toBe("review");
    expect(at("validated")).toBe("review");
    for (const s of ["running", "completed", "cancelled", "failed"]) expect(at(s), s).toBe("run");
  });
  it("shows the mapping for a status it does not know rather than a blank screen", () => {
    expect(stepOf({ status: "something_new" })).toBe("mapping");
  });
});

describe("mapping body", () => {
  const session = { sheets: { Products: { mapping: { Name: "title", Extra: null } }, Variants: { mapping: { Code: "sku" } } } };
  it("sends every sheet, using the draft where the merchant changed one", () => {
    const draft = { Products: { Name: "title", Extra: "brand" } };
    expect(mergedMapping(session, draft)).toEqual({ Products: { Name: "title", Extra: "brand" }, Variants: { Code: "sku" } });
  });
  it("sends the server's suggestion when nothing was changed", () => {
    expect(mappingBody(session, {}, "skip").mapping).toEqual({ Products: { Name: "title", Extra: null }, Variants: { Code: "sku" } });
  });
  it("only ever sends the two policies the screen offers", () => {
    expect(mappingBody(session, {}, "update").options).toEqual({ duplicate_policy: "update" });
    for (const p of ["skip", "create_only", undefined, "anything"]) expect(mappingBody(session, {}, p).options).toEqual({ duplicate_policy: "skip" });
  });
});
