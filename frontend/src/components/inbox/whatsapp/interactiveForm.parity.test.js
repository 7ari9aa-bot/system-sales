// The form's limits must equal the server's. Two copies of one rule drift: someone raises a limit
// on one side, and the agent either sees a red field the server would accept, or a green one it
// refuses. This reads the server's constants out of its source and compares them with ours.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";
import { LIMITS } from "./interactiveForm";

const SERVER = resolve(__dirname, "../../../../../backend/app/applications/apparel/modules/conversations/gateway/whatsapp_interactive.py");
const source = readFileSync(SERVER, "utf8");
const server = (name) => {
  const m = source.match(new RegExp(`^${name}\\s*=\\s*(\\d+)`, "m"));
  if (!m) throw new Error(`${name} not found in whatsapp_interactive.py`);
  return Number(m[1]);
};

const PAIRS = {
  footer: "FOOTER_MAX",
  headerText: "HEADER_TEXT_MAX",
  buttonsBody: "BUTTONS_BODY_MAX",
  buttons: "BUTTONS_MAX",
  buttonTitle: "BUTTON_TITLE_MAX",
  buttonId: "BUTTON_ID_MAX",
  listBody: "LIST_BODY_MAX",
  listButton: "LIST_BUTTON_MAX",
  sections: "LIST_SECTIONS_MAX",
  rows: "LIST_ROWS_MAX",
  sectionTitle: "LIST_SECTION_TITLE_MAX",
  rowTitle: "LIST_ROW_TITLE_MAX",
  rowDescription: "LIST_ROW_DESCRIPTION_MAX",
  rowId: "LIST_ROW_ID_MAX",
  ctaBody: "CTA_BODY_MAX",
  ctaLabel: "CTA_LABEL_MAX",
  url: "CTA_URL_MAX",
};

describe("the form's limits are the server's", () => {
  test.each(Object.entries(PAIRS))("%s", (key, constant) => {
    expect(LIMITS[key]).toBe(server(constant));
  });
  test("every limit the form has is compared, so a new one cannot slip in unchecked", () => {
    expect(Object.keys(LIMITS).sort()).toEqual(Object.keys(PAIRS).sort());
  });
});
