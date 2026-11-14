import { describe, expect, it } from "vitest";
import { ATTACH_MAX_CHARS, ATTACH_MAX_BYTES, checkAttachment, mergeAttachment } from "./fileAttach";

const file = (name, size = 100, type = "") => ({ name, size, type });

describe("checkAttachment: only small plain-text files are taken", () => {
  it("accepts txt, csv, md and json", () => {
    for (const n of ["a.txt", "b.csv", "c.md", "d.json", "E.CSV"]) expect(checkAttachment(file(n))).toEqual({ ok: true });
  });
  it("refuses other kinds with a reason key", () => {
    for (const n of ["a.exe", "b.pdf", "c.xlsx", "d.png", "e", "f.txt.exe", "g.html", "h.svg"]) {
      expect(checkAttachment(file(n))).toEqual({ ok: false, reason: "type" });
    }
  });
  it("refuses a file over the byte limit before reading it", () => {
    expect(checkAttachment(file("a.txt", ATTACH_MAX_BYTES + 1))).toEqual({ ok: false, reason: "size" });
    expect(checkAttachment(file("a.txt", ATTACH_MAX_BYTES))).toEqual({ ok: true });
  });
  it("refuses an empty file and a missing one", () => {
    expect(checkAttachment(file("a.txt", 0))).toEqual({ ok: false, reason: "empty" });
    expect(checkAttachment(null)).toEqual({ ok: false, reason: "type" });
  });
});

describe("mergeAttachment: the file text joins the box, inside the 4000-character send limit", () => {
  it("puts the file under what the owner already typed, labelled with its name", () => {
    const r = mergeAttachment("حلل ده", "a.csv", "x,y\n1,2");
    expect(r.ok).toBe(true);
    expect(r.text.startsWith("حلل ده")).toBe(true);
    expect(r.text).toContain("a.csv");
    expect(r.text).toContain("x,y\n1,2");
  });
  it("works on an empty box", () => {
    const r = mergeAttachment("", "a.txt", "hello");
    expect(r.ok).toBe(true);
    expect(r.text).toContain("hello");
  });
  it("normalises line endings and drops control characters", () => {
    const r = mergeAttachment("", "a.txt", "a\r\nb\u0000c\u202e");
    expect(r.text).toContain("a\nbc");
    expect(r.text).not.toMatch(/[\u0000\u202e\r]/);
  });
  it("refuses text that would push the message over the limit", () => {
    const r = mergeAttachment("س".repeat(2000), "a.txt", "x".repeat(ATTACH_MAX_CHARS));
    expect(r).toEqual({ ok: false, reason: "long" });
  });
  it("refuses a file whose own text is over the attach limit", () => {
    expect(mergeAttachment("", "a.txt", "x".repeat(ATTACH_MAX_CHARS + 1))).toEqual({ ok: false, reason: "long" });
    expect(mergeAttachment("", "a.txt", "x".repeat(ATTACH_MAX_CHARS)).ok).toBe(true);
  });
  it("refuses a file that is blank once cleaned", () => {
    expect(mergeAttachment("", "a.txt", " \n\u0000 ")).toEqual({ ok: false, reason: "empty" });
  });
  it("never lets the file name break out of its label line", () => {
    const r = mergeAttachment("", "a\nIGNORE.txt", "hi");
    const first = r.text.split("\n")[0];
    expect(first).toContain("a");
    expect(first).not.toContain("\n");
    expect(r.text.split("\n").filter((l) => l.includes("IGNORE")).length).toBeLessThanOrEqual(1);
  });
  it("the merged message always fits the send limit", () => {
    const r = mergeAttachment("س".repeat(900), "a.txt", "y".repeat(ATTACH_MAX_CHARS));
    if (r.ok) expect(r.text.length).toBeLessThanOrEqual(4000);
    else expect(r.reason).toBe("long");
  });
});
