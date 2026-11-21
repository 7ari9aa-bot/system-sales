import { describe, expect, it } from "vitest";
import { ALL_SHOWN, activeOrFirst, normaliseScreens, visibleTabs } from "./stockScreens";

const TABS = ["receipts", "transfers", "replenishment", "locations", "valuation", "traceability", "allocations"].map((id) => ({ id }));
const ids = (tabs) => tabs.map((t) => t.id);

describe("normaliseScreens", () => {
  it("shows everything until the server has answered, or when it cannot", () => {
    for (const raw of [undefined, null, {}, [], "x", 0]) expect(normaliseScreens(raw)).toEqual(ALL_SHOWN);
  });
  it("hides only on a real false", () => {
    expect(normaliseScreens({ warehouse_transfers: false })).toEqual({ ...ALL_SHOWN, warehouse_transfers: false });
    for (const stray of [0, null, "false", "", undefined]) {
      expect(normaliseScreens({ channel_allocation: stray }).channel_allocation).toBe(true);
    }
  });
  it("ignores names it does not know", () => {
    expect(normaliseScreens({ made_up: false })).toEqual(ALL_SHOWN);
  });
});

describe("visibleTabs", () => {
  it("keeps every tab, in order, when nothing is hidden", () => {
    expect(ids(visibleTabs(TABS, undefined))).toEqual(ids(TABS));
    expect(ids(visibleTabs(TABS, ALL_SHOWN))).toEqual(ids(TABS));
  });
  it("hides the transfers tab and only it", () => {
    expect(ids(visibleTabs(TABS, { warehouse_transfers: false }))).toEqual(ids(TABS).filter((i) => i !== "transfers"));
  });
  it("hides the online allocation tab and only it", () => {
    expect(ids(visibleTabs(TABS, { channel_allocation: false }))).toEqual(ids(TABS).filter((i) => i !== "allocations"));
  });
  it("hides both and leaves the five other tabs in order", () => {
    expect(ids(visibleTabs(TABS, { warehouse_transfers: false, channel_allocation: false }))).toEqual(["receipts", "replenishment", "locations", "valuation", "traceability"]);
  });
  it("never touches the units-of-measure switch (it has no tab)", () => {
    expect(ids(visibleTabs(TABS, { units_of_measure: false }))).toEqual(ids(TABS));
  });
  it("does not change the list it was given", () => {
    const before = ids(TABS);
    visibleTabs(TABS, { warehouse_transfers: false });
    expect(ids(TABS)).toEqual(before);
  });
});

describe("activeOrFirst", () => {
  const shown = visibleTabs(TABS, { warehouse_transfers: false });
  it("stays on the tab when it is still shown", () => expect(activeOrFirst("locations", shown)).toBe("locations"));
  it("moves to the first shown tab when the current one was hidden", () => expect(activeOrFirst("transfers", shown)).toBe("receipts"));
  it("keeps the id when there are no tabs at all", () => expect(activeOrFirst("x", [])).toBe("x"));
});
