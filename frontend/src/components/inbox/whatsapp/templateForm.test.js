import { describe, expect, it } from "vitest";
import { buildSend, cannotSendReason, formShape, renderBody, variableNumbers } from "./templateForm";

const tpl = (components, extra = {}) => ({ status: "approved", language: "en", components, ...extra });
const BODY2 = { type: "BODY", text: "Hi {{1}}, order {{2}} is ready" };

describe("variableNumbers", () => {
  it("lists each variable once, in order of appearance", () => {
    expect(variableNumbers("a {{2}} b {{1}} c {{2}}")).toEqual([2, 1]);
    expect(variableNumbers("no variables")).toEqual([]);
    expect(variableNumbers(null)).toEqual([]);
    expect(variableNumbers("{{ 3 }}")).toEqual([3]);
  });
});

describe("formShape", () => {
  it("reads header, body slots, footer and buttons from Meta's components", () => {
    const s = formShape(tpl([
      { type: "HEADER", format: "TEXT", text: "Order {{1}}" },
      BODY2,
      { type: "FOOTER", text: "Thanks" },
      { type: "BUTTONS", buttons: [
        { type: "QUICK_REPLY", text: "Yes" },
        { type: "URL", text: "Track", url: "https://x.example/{{1}}" },
        { type: "URL", text: "Site", url: "https://x.example" },
        { type: "PHONE_NUMBER", text: "Call", phone_number: "+201000000000" },
      ] },
    ]));
    expect(s.header).toEqual({ kind: "text", text: "Order {{1}}", slots: 1 });
    expect(s.bodySlots).toEqual([1, 2]);
    expect(s.footer).toBe("Thanks");
    expect(s.buttons.map((b) => [b.type, b.needsInput])).toEqual([
      ["quick_reply", true], ["url", true], ["url", false], ["phone", false],
    ]);
  });

  it("a media header has no text slot", () => {
    expect(formShape(tpl([{ type: "HEADER", format: "IMAGE" }, BODY2])).header).toEqual({ kind: "image", slots: 0 });
  });

  it("falls back to the plain body when a template has no components yet", () => {
    expect(formShape({ status: "approved", body_text: "Hello {{1}}" }).bodySlots).toEqual([1]);
  });
});

describe("cannotSendReason", () => {
  it.each(["draft", "submitted", "rejected", "paused", "archived"])("%s is not sendable", (status) => {
    expect(cannotSendReason(tpl([BODY2], { status }))).toBe("not_approved");
  });
  it("an approved template is sendable", () => expect(cannotSendReason(tpl([BODY2]))).toBeNull());
  it("a location header cannot be sent from here", () => {
    expect(cannotSendReason(tpl([{ type: "HEADER", format: "LOCATION" }, BODY2]))).toBe("unsupported_header");
  });
  it("nothing selected", () => expect(cannotSendReason(null)).toBe("missing"));
});

describe("renderBody", () => {
  it("puts the values in and leaves an unfilled slot visible", () => {
    expect(renderBody(tpl([BODY2]), { body: ["Ali", "7"] })).toBe("Hi Ali, order 7 is ready");
    expect(renderBody(tpl([BODY2]), { body: ["Ali", " "] })).toBe("Hi Ali, order {{2}} is ready");
    expect(renderBody(tpl([BODY2]), {})).toBe("Hi {{1}}, order {{2}} is ready");
  });
});

describe("buildSend", () => {
  it("builds the vars the server reads, with the template's own language", () => {
    const r = buildSend(tpl([BODY2]), { body: ["Ali", "7"] });
    expect(r).toEqual({ ok: true, vars: { body_params: ["Ali", "7"] }, language: "en" });
  });

  it("a template with nothing to fill sends no vars", () => {
    expect(buildSend(tpl([{ type: "BODY", text: "Hello" }]), {})).toEqual({ ok: true, vars: {}, language: "en" });
  });

  it("names every empty body variable", () => {
    const r = buildSend(tpl([BODY2]), { body: ["Ali", "  "] });
    expect(r.ok).toBe(false);
    expect(Object.keys(r.errors)).toEqual(["body.2"]);
  });

  it("trims values", () => {
    expect(buildSend(tpl([BODY2]), { body: ["  Ali ", " 7"] }).vars.body_params).toEqual(["Ali", "7"]);
  });

  it("a text header variable is required and sent as header_params", () => {
    const t = tpl([{ type: "HEADER", format: "TEXT", text: "Order {{1}}" }, { type: "BODY", text: "Hi" }]);
    expect(buildSend(t, {}).errors["header.1"]).toBeTruthy();
    expect(buildSend(t, { header: ["#7"] }).vars).toEqual({ header_params: ["#7"] });
  });

  it("a text header with no variable asks for nothing", () => {
    const t = tpl([{ type: "HEADER", format: "TEXT", text: "Hello" }, { type: "BODY", text: "Hi" }]);
    expect(buildSend(t, {})).toEqual({ ok: true, vars: {}, language: "en" });
  });

  it.each(["IMAGE", "VIDEO", "DOCUMENT"])("a %s header needs an https link", (format) => {
    const t = tpl([{ type: "HEADER", format }, { type: "BODY", text: "Hi" }]);
    expect(buildSend(t, {}).errors["header.media"]).toBeTruthy();
    expect(buildSend(t, { headerMedia: { link: "http://x/a.png" } }).errors["header.media"]).toBeTruthy();
    expect(buildSend(t, { headerMedia: { link: "javascript:alert(1)" } }).errors["header.media"]).toBeTruthy();
    expect(buildSend(t, { headerMedia: { link: "https://cdn.example/a.bin" } }).vars.header_media)
      .toEqual({ type: format.toLowerCase(), link: "https://cdn.example/a.bin" });
  });

  it("only a document header carries a file name", () => {
    const doc = tpl([{ type: "HEADER", format: "DOCUMENT" }, { type: "BODY", text: "Hi" }]);
    expect(buildSend(doc, { headerMedia: { link: "https://x/a.pdf", filename: "inv.pdf" } }).vars.header_media.filename).toBe("inv.pdf");
    const img = tpl([{ type: "HEADER", format: "IMAGE" }, { type: "BODY", text: "Hi" }]);
    expect(buildSend(img, { headerMedia: { link: "https://x/a.png", filename: "x" } }).vars.header_media.filename).toBeUndefined();
  });

  it("buttons: a quick reply defaults to its label, a url button needs its suffix, others send nothing", () => {
    const t = tpl([{ type: "BODY", text: "Hi" }, { type: "BUTTONS", buttons: [
      { type: "QUICK_REPLY", text: "Yes" },
      { type: "URL", text: "Track", url: "https://x.example/{{1}}" },
      { type: "URL", text: "Site", url: "https://x.example" },
      { type: "PHONE_NUMBER", text: "Call", phone_number: "+201000000000" },
    ] }]);
    expect(buildSend(t, {}).errors).toEqual({ "button.1": expect.any(String) });
    expect(buildSend(t, { buttons: { 1: "order/7" } }).vars.button_params).toEqual([
      { index: 0, type: "quick_reply", payload: "Yes" },
      { index: 1, type: "url", text: "order/7" },
    ]);
    expect(buildSend(t, { buttons: { 0: "YES_7", 1: "order/7" } }).vars.button_params[0].payload).toBe("YES_7");
  });

  it("an unapproved template is refused with the reason, whatever was filled in", () => {
    expect(buildSend(tpl([BODY2], { status: "paused" }), { body: ["a", "b"] })).toEqual({ ok: false, errors: { template: "not_approved" } });
  });

  it("the language is the template's own, so the check and the send agree", () => {
    expect(buildSend(tpl([BODY2], { language: "ar" }), { body: ["a", "b"] }).language).toBe("ar");
    expect(buildSend({ ...tpl([BODY2]), language: undefined }, { body: ["a", "b"] }).language).toBe("ar");
  });
});
