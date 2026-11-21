import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";
import {
  LIMITS, buildInteractive, bodyLimit, canAddButton, canAddRow, canAddSection, draftDisplay, emptyForm, nextId, previewLines, rowCount, switchKind, toDisplay,
} from "./interactiveForm";

const t = (key, vars) => (vars ? `${key}:${Object.values(vars).join(",")}` : key);
const buttons = (over = {}) => ({ ...emptyForm("buttons"), body: "Confirm?", buttons: [{ title: "Yes" }, { title: "No" }], ...over });
const list = (over = {}) => ({
  ...emptyForm("list"), body: "Pick", listButton: "Options",
  sections: [{ title: "Shipping", rows: [{ title: "Express", description: "1 day" }, { title: "Standard", description: "" }] }], ...over,
});
const cta = (over = {}) => ({ ...emptyForm("cta_url"), body: "Track it", label: "Track", url: "https://fihrist.world/o/1", ...over });
const rows = (n, start = 0) => Array.from({ length: n }, (_, i) => ({ title: `R${start + i}`, description: "" }));

describe("what the form produces", () => {
  test("reply buttons: the shape the server takes, with ids made for the agent", () => {
    const r = buildInteractive(buttons({ header: " Order ", footer: "Thanks" }), t);
    expect(r).toEqual({
      ok: true,
      spec: { kind: "buttons", body: "Confirm?", header: { type: "text", text: "Order" }, footer: "Thanks", buttons: [{ id: "btn_1", title: "Yes" }, { id: "btn_2", title: "No" }] },
    });
  });
  test("a list", () => {
    expect(buildInteractive(list(), t).spec).toEqual({
      kind: "list", body: "Pick", button: "Options",
      sections: [{ title: "Shipping", rows: [{ id: "row_1_1", title: "Express", description: "1 day" }, { id: "row_1_2", title: "Standard" }] }],
    });
  });
  test("a link button", () => {
    expect(buildInteractive(cta(), t).spec).toEqual({ kind: "cta_url", body: "Track it", label: "Track", url: "https://fihrist.world/o/1" });
  });
  test("an empty optional header, footer or description is left out", () => {
    const spec = buildInteractive(buttons({ header: "  ", footer: "" }), t).spec;
    expect(spec).not.toHaveProperty("header");
    expect(spec).not.toHaveProperty("footer");
    expect(buildInteractive(list(), t).spec.sections[0].rows[1]).not.toHaveProperty("description");
  });
  test("an id the agent never typed is kept stable if it was already given", () => {
    const f = buttons({ buttons: [{ title: "Yes", id: "keep_me" }] });
    expect(buildInteractive(f, t).spec.buttons[0].id).toBe("keep_me");
  });
});

describe("each field is judged where it is typed", () => {
  const errs = (form) => buildInteractive(form, t).errors;
  test("body is required and capped per kind", () => {
    expect(errs(buttons({ body: " " })).body).toBe("required");
    expect(errs(buttons({ body: "x".repeat(1025) })).body).toBe("tooLong:1024");
    expect(errs(list({ body: "x".repeat(4097) })).body).toBe("tooLong:4096");
    expect(buildInteractive(list({ body: "x".repeat(4096) }), t).ok).toBe(true);
    expect(errs(cta({ body: "x".repeat(1025) })).body).toBe("tooLong:1024");
  });
  test("a button title is required, capped at 20 and unique ignoring case", () => {
    expect(errs(buttons({ buttons: [{ title: "" }] }))["buttons.0.title"]).toBe("required");
    expect(errs(buttons({ buttons: [{ title: "x".repeat(21) }] }))["buttons.0.title"]).toBe("tooLong:20");
    expect(errs(buttons({ buttons: [{ title: "Yes" }, { title: "yes" }] }))["buttons.1.title"]).toBe("duplicate");
  });
  test("lengths count characters, so Arabic and emoji are not over-counted", () => {
    expect(buildInteractive(buttons({ buttons: [{ title: "ا".repeat(20) }] }), t).ok).toBe(true);
    expect(buildInteractive(buttons({ buttons: [{ title: "😀".repeat(20) }] }), t).ok).toBe(true);
    expect(errs(buttons({ buttons: [{ title: "😀".repeat(21) }] }))["buttons.0.title"]).toBe("tooLong:20");
  });
  test("header and footer are capped at 60", () => {
    expect(errs(buttons({ header: "x".repeat(61) })).header).toBe("tooLong:60");
    expect(errs(buttons({ footer: "x".repeat(61) })).footer).toBe("tooLong:60");
  });
  test("a list needs a button label, a section title and a row title", () => {
    expect(errs(list({ listButton: "" })).listButton).toBe("required");
    expect(errs(list({ listButton: "x".repeat(21) })).listButton).toBe("tooLong:20");
    expect(errs(list({ sections: [{ title: "", rows: rows(1) }] }))["sections.0.title"]).toBe("required");
    expect(errs(list({ sections: [{ title: "S", rows: [{ title: "", description: "" }] }] }))["sections.0.rows.0.title"]).toBe("required");
  });
  test("section title 24, row title 24, description 72", () => {
    expect(errs(list({ sections: [{ title: "x".repeat(25), rows: rows(1) }] }))["sections.0.title"]).toBe("tooLong:24");
    expect(errs(list({ sections: [{ title: "S", rows: [{ title: "x".repeat(25), description: "" }] }] }))["sections.0.rows.0.title"]).toBe("tooLong:24");
    expect(errs(list({ sections: [{ title: "S", rows: [{ title: "R", description: "x".repeat(73) }] }] }))["sections.0.rows.0.description"]).toBe("tooLong:72");
  });
  test("ten rows in total across sections, not ten per section", () => {
    const two = (a, b) => list({ sections: [{ title: "A", rows: rows(a) }, { title: "B", rows: rows(b, a) }] });
    expect(buildInteractive(two(5, 5), t).ok).toBe(true);
    expect(errs(two(5, 6)).rows).toBe("tooManyRows:10");
  });
  test("a link needs a label and a real web address", () => {
    expect(errs(cta({ label: "" })).label).toBe("required");
    expect(errs(cta({ label: "x".repeat(21) })).label).toBe("tooLong:20");
    for (const url of ["", "fihrist.world", "javascript:alert(1)", "ftp://x.example/a", "https://"]) {
      expect(errs(cta({ url })).url, url).toBeTruthy();
    }
    expect(buildInteractive(cta({ url: "http://x.example/a?b=1" }), t).ok).toBe(true);
  });
  test("more than three buttons, none, or an unknown kind are refused", () => {
    expect(errs(buttons({ buttons: [1, 2, 3, 4].map((n) => ({ title: `B${n}` })) })).buttons).toBe("tooMany:3");
    expect(errs(buttons({ buttons: [] })).buttons).toBe("atLeastOne");
    expect(buildInteractive({ ...buttons(), kind: "carousel" }, t).ok).toBe(false);
  });
});

describe("the form's helpers", () => {
  test("the three Add buttons stop exactly at the limit", () => {
    expect(canAddButton(buttons({ buttons: rows(2) }))).toBe(true);
    expect(canAddButton(buttons({ buttons: rows(3) }))).toBe(false);
    expect(canAddRow(list({ sections: [{ title: "A", rows: rows(9) }] }))).toBe(true);
    expect(canAddRow(list({ sections: [{ title: "A", rows: rows(10) }] }))).toBe(false);
    expect(canAddSection(list({ sections: [{ title: "A", rows: rows(10) }] }))).toBe(false);
    const ten = Array.from({ length: 10 }, (_, i) => ({ title: `S${i}`, rows: rows(0) }));
    expect(canAddSection(list({ sections: ten }))).toBe(false);
  });
  test("rows are counted across sections", () => {
    expect(rowCount(list({ sections: [{ title: "A", rows: rows(3) }, { title: "B", rows: rows(4) }] }))).toBe(7);
  });
  test("switching kind keeps the shared text and drops the rest", () => {
    const next = switchKind(buttons({ header: "H", footer: "F" }), "list");
    expect(next).toMatchObject({ kind: "list", body: "Confirm?", header: "H", footer: "F", listButton: "" });
    expect(next.buttons).toEqual(emptyForm("list").buttons);
    expect(switchKind(next, "list")).toBe(next);
  });
  test("body limit follows the kind", () => {
    expect([bodyLimit("buttons"), bodyLimit("list"), bodyLimit("cta_url")]).toEqual([1024, 4096, 1024]);
    expect(LIMITS.rows).toBe(10);
  });
  test("an id is never reused", () => {
    expect(nextId("btn", [])).toBe("btn_1");
    expect(nextId("btn", ["btn_1", "btn_2"])).toBe("btn_3");
    expect(nextId("btn", ["btn_2"])).toBe("btn_1");
  });
  test("the preview text matches what the server keeps as the message body", () => {
    expect(previewLines(buildInteractive(buttons(), t).spec)).toBe("Confirm?\n[ Yes ]\n[ No ]");
    expect(previewLines(buildInteractive(list(), t).spec)).toBe("Pick\n[ Options ]\n- Express\n- Standard");
    expect(previewLines(buildInteractive(cta(), t).spec)).toBe("Track it\n[ Track ] https://fihrist.world/o/1");
  });
});

describe("showing a message at once equals what the server returns later", () => {
  const fixtures = JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/interactive_server.json"), "utf8"));
  test.each(Object.keys(fixtures))("%s", (name) => {
    expect(toDisplay(fixtures[name].spec)).toEqual(fixtures[name].server);
  });
  test("there are cases for all three kinds", () => {
    expect(new Set(Object.values(fixtures).map((f) => f.spec.kind))).toEqual(new Set(["buttons", "list", "cta_url"]));
  });
});

describe("the live preview of a half-filled form", () => {
  test("shows the text typed so far and skips choices still empty", () => {
    const d = draftDisplay(buttons({ buttons: [{ title: "Yes" }, { title: "" }, { title: "  " }] }));
    expect(d.body.text).toBe("Confirm?");
    expect(d.action.buttons.map((b) => b.reply.title)).toEqual(["Yes"]);
  });
  test("a list drops empty rows and sections that end up with none", () => {
    const d = draftDisplay(list({ sections: [{ title: "A", rows: [{ title: "x", description: "" }, { title: "", description: "d" }] }, { title: "B", rows: [{ title: "", description: "" }] }] }));
    expect(d.action.sections).toHaveLength(1);
    expect(d.action.sections[0].rows.map((r) => r.title)).toEqual(["x"]);
  });
  test("it never throws on a blank form, whatever the kind", () => {
    for (const kind of ["buttons", "list", "cta_url"]) expect(() => draftDisplay(emptyForm(kind))).not.toThrow();
  });
  test("a finished form previews exactly what will be sent", () => {
    for (const f of [buttons({ header: "H", footer: "F" }), list(), cta()]) {
      expect(draftDisplay(f)).toEqual(toDisplay(buildInteractive(f, t).spec));
    }
  });
});
