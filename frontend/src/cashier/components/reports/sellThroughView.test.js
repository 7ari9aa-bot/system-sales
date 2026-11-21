import { describe, expect, it } from "vitest";
import {
  RUNNING_OUT_FROM,
  SITTING_UNTIL,
  STATE_TEXT,
  barWidth,
  sellThroughColumns,
  sellThroughErrorNotice,
  sellThroughSummary,
  sellThroughTotalsRow,
  shareLabel,
  stateCounts,
  stockState,
} from "./sellThroughView";

const row = (over = {}) => ({ model: "قميص", colour: "أسود", size: "M", season: "SS26", unitsSold: 5, unitsOnHand: 5, share: 50, ...over });

describe("shareLabel", () => {
  it("one decimal and a percent sign", () => {
    expect(shareLabel(62.5)).toBe("62.5٪");
    expect(shareLabel(100)).toBe("100.0٪");
    expect(shareLabel(0)).toBe("0.0٪");
  });
  it("a dash when there is nothing to be a share of", () => {
    expect(shareLabel(null)).toBe("—");
    expect(shareLabel(undefined)).toBe("—");
  });
});

describe("the cut-offs are the numbers the owner was told, not whatever the constant says", () => {
  it("70 percent sold is running out, 69.9 is not, 20 with stock is sitting, 20.1 is not", () => {
    expect(RUNNING_OUT_FROM).toBe(70);
    expect(SITTING_UNTIL).toBe(20);
    expect(stockState({ share: 70, unitsOnHand: 3 })).toBe("out");
    expect(stockState({ share: 69.9, unitsOnHand: 3 })).toBe("");
    expect(stockState({ share: 20, unitsOnHand: 3 })).toBe("sitting");
    expect(stockState({ share: 20.1, unitsOnHand: 3 })).toBe("");
  });
});

describe("stockState", () => {
  it("nearly everything sold is running out, exactly at the cut-off included", () => {
    expect(stockState(row({ share: RUNNING_OUT_FROM }))).toBe("out");
    expect(stockState(row({ share: RUNNING_OUT_FROM - 0.1 }))).toBe("");
    expect(stockState(row({ share: 100, unitsOnHand: 0 }))).toBe("out");
  });
  it("little sold with stock left is sitting, exactly at the cut-off included", () => {
    expect(stockState(row({ share: SITTING_UNTIL, unitsOnHand: 10 }))).toBe("sitting");
    expect(stockState(row({ share: SITTING_UNTIL + 0.1, unitsOnHand: 10 }))).toBe("");
    expect(stockState(row({ share: 0, unitsOnHand: 4 }))).toBe("sitting");
  });
  it("a low share with nothing left on the shelf is not 'sitting'", () => {
    expect(stockState(row({ share: 10, unitsOnHand: 0 }))).toBe("");
  });
  it("no share (nothing sold and nothing left) is neither", () => {
    expect(stockState(row({ share: null }))).toBe("");
    expect(stockState(undefined)).toBe("");
  });
  it("the two states have their own words", () => {
    expect(STATE_TEXT.out).toBe("قرّب يخلص");
    expect(STATE_TEXT.sitting).toBe("راكد");
    expect(STATE_TEXT[""]).toBe("");
  });
});

describe("barWidth", () => {
  it("is the share, kept inside 0..100", () => {
    expect(barWidth(40)).toBe(40);
    expect(barWidth(0)).toBe(0);
    expect(barWidth(100)).toBe(100);
    expect(barWidth(250)).toBe(100);
    expect(barWidth(-5)).toBe(0);
  });
  it("no share draws nothing", () => {
    expect(barWidth(null)).toBe(0);
    expect(barWidth(undefined)).toBe(0);
    expect(barWidth(NaN)).toBe(0);
  });
});

describe("columns", () => {
  const cols = Object.fromEntries(sellThroughColumns().map((c) => [c.key, c]));
  it("has the six columns in reading order", () => {
    expect(sellThroughColumns().map((c) => c.key)).toEqual(["variant", "season", "sold", "onHand", "share", "state"]);
  });
  it("the variant cell is the model with colour and size under it", () => {
    expect(cols.variant.text(row())).toBe("قميص");
    expect(cols.variant.sub(row())).toBe("أسود / M");
  });
  it("sold and on hand print the figures", () => {
    expect(cols.sold.text(row({ unitsSold: 12 }))).toBe("12");
    expect(cols.onHand.text(row({ unitsOnHand: 0 }))).toBe("0");
  });
  it("a size that sold and has nothing left is in red", () => {
    expect(cols.onHand.tone(row({ unitsSold: 4, unitsOnHand: 0 }))).toBe("loss");
    expect(cols.onHand.tone(row({ unitsSold: 4, unitsOnHand: 2 }))).toBe("");
    expect(cols.onHand.tone(row({ unitsSold: 0, unitsOnHand: 0 }))).toBe("");
  });
  it("the state column says it in words, and red only for running out", () => {
    expect(cols.state.text(row({ share: 90, unitsOnHand: 1 }))).toBe("قرّب يخلص");
    expect(cols.state.tone(row({ share: 90, unitsOnHand: 1 }))).toBe("loss");
    expect(cols.state.text(row({ share: 5, unitsOnHand: 9 }))).toBe("راكد");
    expect(cols.state.tone(row({ share: 5, unitsOnHand: 9 }))).toBe("muted");
    expect(cols.state.text(row({ share: 50 }))).toBe("");
  });
  it("the share column prints the share and carries a bar", () => {
    expect(cols.share.text(row({ share: 62.5 }))).toBe("62.5٪");
    expect(cols.share.bar(row({ share: 62.5 }))).toBe(62.5);
    expect(cols.share.tone(row({ share: 90 }))).toBe("strong");
    expect(cols.share.tone(row({ share: 30 }))).toBe("muted");
  });
});

describe("the totals row", () => {
  it("uses the same keys as the columns", () => {
    const t = sellThroughTotalsRow({ unitsSold: 10, unitsOnHand: 30, share: 25 });
    expect(t).toMatchObject({ variant: "الإجمالي", sold: "10", onHand: "30", share: "25.0٪" });
    for (const c of sellThroughColumns()) expect(c.key in t).toBe(true);
  });
  it("is null when there are no totals", () => {
    expect(sellThroughTotalsRow(null)).toBeNull();
  });
});

describe("the summary line", () => {
  const rows = [row({ share: 90, unitsOnHand: 1 }), row({ share: 80, unitsOnHand: 2 }), row({ share: 5, unitsOnHand: 9 }), row({ share: 50 })];
  it("counts what is running out and what sits", () => {
    expect(stateCounts(rows)).toEqual({ out: 2, sitting: 1 });
    expect(sellThroughSummary(rows)).toBe("٢ مقاس قرّب يخلص • ١ مقاس راكد".replace(/[٢١]/g, (d) => ({ "٢": "2", "١": "1" })[d]));
  });
  it("leaves out a part that has nothing in it", () => {
    expect(sellThroughSummary([row({ share: 90, unitsOnHand: 1 })])).toBe("1 مقاس قرّب يخلص");
    expect(sellThroughSummary([row({ share: 5, unitsOnHand: 9 })])).toBe("1 مقاس راكد");
    expect(sellThroughSummary([row()])).toBe("");
    expect(sellThroughSummary()).toBe("");
  });
});

describe("the error notice", () => {
  it("no error, no notice", () => {
    expect(sellThroughErrorNotice(null, "failed")).toBeNull();
  });
  it("no permission names who can open it and is not a retry", () => {
    for (const kind of ["forbidden", "unauthorized"]) {
      const n = sellThroughErrorNotice({ status: 403 }, kind);
      expect(n.tone).toBe("forbidden");
      expect(n.message).toMatch(/صاحب المحل أو المدير/);
    }
  });
  it("offline and failed are different messages", () => {
    const off = sellThroughErrorNotice({ status: 0 }, "offline");
    const bad = sellThroughErrorNotice({ status: 500 }, "failed");
    expect(off.message).toMatch(/الاتصال/);
    expect(bad.message).toMatch(/تعذّر تحميل تقرير التصريف/);
    expect(off.message).not.toBe(bad.message);
  });
});
