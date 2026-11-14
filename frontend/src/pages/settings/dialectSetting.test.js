import { describe, expect, it } from "vitest";
import { AUTO, dialectBody, dialectOptions, selectionFrom, sourceKey, isDirty } from "./dialectSetting";

const CHOICES = ["egyptian", "gulf", "levantine", "maghrebi", "msa"];

describe("dialectBody", () => {
  it("sends the chosen key as it is", () => {
    for (const key of CHOICES) expect(dialectBody(key, CHOICES)).toEqual({ dialect: key });
  });

  it("sends an explicit null for automatic, because null is what clears the choice", () => {
    expect(dialectBody(AUTO, CHOICES)).toEqual({ dialect: null });
    expect("dialect" in dialectBody(AUTO, CHOICES)).toBe(true);
  });

  it("never sends a value the server did not offer", () => {
    expect(dialectBody("klingon", CHOICES)).toEqual({ dialect: null });
    expect(dialectBody("", CHOICES)).toEqual({ dialect: null });
    expect(dialectBody(undefined, CHOICES)).toEqual({ dialect: null });
    expect(dialectBody("Gulf", CHOICES)).toEqual({ dialect: null });
  });
});

describe("selectionFrom", () => {
  it("shows automatic when the owner never chose", () => {
    expect(selectionFrom({ dialect: null, choices: CHOICES })).toBe(AUTO);
    expect(selectionFrom({ choices: CHOICES })).toBe(AUTO);
    expect(selectionFrom(null)).toBe(AUTO);
  });

  it("shows the stored choice", () => {
    expect(selectionFrom({ dialect: "gulf", choices: CHOICES })).toBe("gulf");
  });

  it("falls back to automatic for a stored value the list does not know", () => {
    expect(selectionFrom({ dialect: "klingon", choices: CHOICES })).toBe(AUTO);
  });
});

describe("dialectOptions", () => {
  it("puts automatic first, then the server's list in its order", () => {
    expect(dialectOptions({ choices: CHOICES }).map((o) => o.value)).toEqual([AUTO, ...CHOICES]);
  });

  it("offers only automatic when the server sent no list", () => {
    expect(dialectOptions(null).map((o) => o.value)).toEqual([AUTO]);
    expect(dialectOptions({}).map((o) => o.value)).toEqual([AUTO]);
  });

  it("never offers a duplicate or a non-string", () => {
    const values = dialectOptions({ choices: ["gulf", "gulf", 7, null, "msa"] }).map((o) => o.value);
    expect(values).toEqual([AUTO, "gulf", "msa"]);
  });
});

describe("sourceKey", () => {
  it("names where the dialect in use came from", () => {
    expect(sourceKey({ source: "owner" })).toBe("dialect.source.owner");
    expect(sourceKey({ source: "currency" })).toBe("dialect.source.currency");
    expect(sourceKey({ source: "default" })).toBe("dialect.source.default");
  });

  it("says default for anything it does not recognise", () => {
    expect(sourceKey({ source: "???" })).toBe("dialect.source.default");
    expect(sourceKey(null)).toBe("dialect.source.default");
  });
});

describe("isDirty", () => {
  it("is false until the selection differs from what the server holds", () => {
    expect(isDirty(AUTO, { dialect: null, choices: CHOICES })).toBe(false);
    expect(isDirty("gulf", { dialect: "gulf", choices: CHOICES })).toBe(false);
    expect(isDirty("gulf", { dialect: null, choices: CHOICES })).toBe(true);
    expect(isDirty(AUTO, { dialect: "gulf", choices: CHOICES })).toBe(true);
  });

  it("is false when the server sent no list, because the screen cannot judge a change", () => {
    expect(isDirty("gulf", { dialect: "gulf" })).toBe(false);
    expect(isDirty("gulf", { dialect: null, choices: [] })).toBe(false);
  });

  it("is false before the server has answered, so a blank screen cannot save", () => {
    expect(isDirty("gulf", null)).toBe(false);
    expect(isDirty(AUTO, undefined)).toBe(false);
  });
});
