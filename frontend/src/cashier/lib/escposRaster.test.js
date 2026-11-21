import { describe, expect, it } from "vitest";
import {
  MAX_SLICE_ROWS,
  pictureToEscPos,
  rasterCommand,
  receiptLines,
  toBits,
} from "./escposRaster";

const px = (w, h, fn) => {
  const a = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y += 1)
    for (let x = 0; x < w; x += 1) {
      const [r, g, b, al] = fn(x, y);
      const i = (y * w + x) * 4;
      a[i] = r; a[i + 1] = g; a[i + 2] = b; a[i + 3] = al;
    }
  return a;
};
const BLACK = [0, 0, 0, 255];
const WHITE = [255, 255, 255, 255];

describe("toBits", () => {
  it("sets the most significant bit for the leftmost dot", () => {
    const { bits } = toBits(px(8, 1, (x) => (x === 0 ? BLACK : WHITE)), 8, 1);
    expect(bits[0]).toBe(0x80);
  });

  it("sets the least significant bit for the eighth dot", () => {
    const { bits } = toBits(px(8, 1, (x) => (x === 7 ? BLACK : WHITE)), 8, 1);
    expect(bits[0]).toBe(0x01);
  });

  it("pads a width that is not a multiple of 8 and leaves the padding blank", () => {
    const { bits, bytesPerRow } = toBits(px(10, 1, () => BLACK), 10, 1);
    expect(bytesPerRow).toBe(2);
    expect(Array.from(bits)).toEqual([0xff, 0xc0]);
  });

  it("treats a transparent pixel as paper, not as black", () => {
    const { bits } = toBits(px(8, 1, () => [0, 0, 0, 0]), 8, 1);
    expect(bits[0]).toBe(0);
  });

  it("splits light from dark at the middle grey, dark side inclusive of 127", () => {
    expect(toBits(px(8, 1, () => [127, 127, 127, 255]), 8, 1).bits[0]).toBe(0xff);
    expect(toBits(px(8, 1, () => [128, 128, 128, 255]), 8, 1).bits[0]).toBe(0x00);
  });

  it("weights green above red above blue", () => {
    // pure red luminance 76, pure green 150, pure blue 29
    expect(toBits(px(8, 1, () => [255, 0, 0, 255]), 8, 1).bits[0]).toBe(0xff);
    expect(toBits(px(8, 1, () => [0, 255, 0, 255]), 8, 1).bits[0]).toBe(0x00);
    expect(toBits(px(8, 1, () => [0, 0, 255, 255]), 8, 1).bits[0]).toBe(0xff);
  });

  it("weights red above blue, so swapping them changes the side of the line", () => {
    // red 255 + green 100: 76 + 59 = 135 (paper); with red and blue weights swapped it is 88 (black)
    expect(toBits(px(8, 1, () => [255, 100, 0, 255]), 8, 1).bits[0]).toBe(0x00);
    // blue 255 + green 100: 29 + 59 = 88 (black); swapped it is 135 (paper)
    expect(toBits(px(8, 1, () => [0, 100, 255, 255]), 8, 1).bits[0]).toBe(0xff);
  });

  it("rows do not bleed into each other", () => {
    const { bits } = toBits(px(8, 2, (_x, y) => (y === 0 ? BLACK : WHITE)), 8, 2);
    expect(Array.from(bits)).toEqual([0xff, 0x00]);
  });

  it("refuses a size that does not match the pixels", () => {
    expect(() => toBits(new Uint8ClampedArray(12), 8, 1)).toThrow(RangeError);
    expect(() => toBits(new Uint8ClampedArray(0), 0, 0)).toThrow(RangeError);
  });
});

describe("rasterCommand", () => {
  it("writes GS v 0 with the row width and height little-endian", () => {
    const cmd = rasterCommand(new Uint8Array(3 * 300), 3, 300);
    expect(Array.from(cmd.slice(0, 8))).toEqual([0x1d, 0x76, 0x30, 0x00, 3, 0, 300 & 0xff, 300 >> 8]);
    expect(cmd.length).toBe(8 + 900);
  });

  it("refuses a slice whose data does not match its size", () => {
    expect(() => rasterCommand(new Uint8Array(5), 3, 2)).toThrow(RangeError);
    expect(() => rasterCommand(new Uint8Array(0), 1, 0)).toThrow(RangeError);
  });
});

describe("pictureToEscPos", () => {
  const parse = (bytes) => {
    // walk: ESC @, then GS v 0 slices, then ESC d n, then optional GS V 1
    const slices = [];
    let i = 2;
    while (bytes[i] === 0x1d && bytes[i + 1] === 0x76) {
      const bpr = bytes[i + 4] | (bytes[i + 5] << 8);
      const rows = bytes[i + 6] | (bytes[i + 7] << 8);
      slices.push({ rows, data: bytes.slice(i + 8, i + 8 + bpr * rows) });
      i += 8 + bpr * rows;
    }
    return { slices, rest: Array.from(bytes.slice(i)) };
  };

  it("starts with the initialise command", () => {
    const out = pictureToEscPos(px(8, 1, () => WHITE), 8, 1);
    expect(Array.from(out.slice(0, 2))).toEqual([0x1b, 0x40]);
  });

  it("cuts at the end by default and not when told not to", () => {
    const img = px(8, 1, () => WHITE);
    expect(parse(pictureToEscPos(img, 8, 1)).rest).toEqual([0x1b, 0x64, 3, 0x1d, 0x56, 0x01]);
    expect(parse(pictureToEscPos(img, 8, 1, { cut: false })).rest).toEqual([0x1b, 0x64, 3]);
  });

  it("splits a tall picture into slices that keep every row, in order", () => {
    const h = MAX_SLICE_ROWS * 2 + 7;
    // row y is black only at x = y % 8, so a dropped or repeated row is visible
    const img = px(8, h, (x, y) => (x === y % 8 ? BLACK : WHITE));
    const { slices } = parse(pictureToEscPos(img, 8, h));
    expect(slices.map((s) => s.rows)).toEqual([MAX_SLICE_ROWS, MAX_SLICE_ROWS, 7]);
    const all = slices.flatMap((s) => Array.from(s.data));
    expect(all).toHaveLength(h);
    all.forEach((byte, y) => expect(byte).toBe(0x80 >> (y % 8)));
  });

  it("one more row than a slice makes a second slice of one row", () => {
    const h = MAX_SLICE_ROWS + 1;
    const { slices } = parse(pictureToEscPos(px(8, h, () => WHITE), 8, h));
    expect(slices.map((s) => s.rows)).toEqual([MAX_SLICE_ROWS, 1]);
  });

  it("clamps the paper feed to a byte", () => {
    const img = px(8, 1, () => WHITE);
    expect(parse(pictureToEscPos(img, 8, 1, { feed: 999, cut: false })).rest).toEqual([0x1b, 0x64, 255]);
    expect(parse(pictureToEscPos(img, 8, 1, { feed: -4, cut: false })).rest).toEqual([0x1b, 0x64, 0]);
  });
});

describe("receiptLines", () => {
  const base = {
    shopName: "محل الأمل",
    receiptNumber: "A-7",
    items: [
      { name: "شاي", quantity: 1, unit_price: "10", total: "10" },
      { name: "سكر", quantity: 3, unit_price: "5", total: "15" },
    ],
    total: "25",
  };

  it("keeps Arabic names as text for the canvas, not as bytes", () => {
    const lines = receiptLines(base);
    expect(lines[0]).toEqual({ kind: "title", text: "محل الأمل" });
    expect(lines.filter((l) => l.kind === "row").map((l) => l.right)).toEqual(["شاي", "سكر"]);
  });

  it("shows the quantity line only when more than one", () => {
    const subs = receiptLines(base).filter((l) => l.kind === "sub");
    expect(subs).toEqual([{ kind: "sub", text: "3 × 5.00" }]);
  });

  it("falls back to quantity times price when a line has no total", () => {
    const rows = receiptLines({ items: [{ name: "x", quantity: 2, unit_price: "4" }], total: "8" }).filter((l) => l.kind === "row");
    expect(rows[0].left).toBe("8.00");
  });

  it("prints the line total it was given, even when it differs from quantity times price", () => {
    const rows = receiptLines({ items: [{ name: "x", quantity: 2, unit_price: "10", total: "15" }], total: "15" }).filter((l) => l.kind === "row");
    expect(rows[0].left).toBe("15.00");
  });

  it("prints the discount and tax only when positive", () => {
    const has = (l, word) => l.some((x) => x.right === word);
    expect(has(receiptLines(base), "الخصم")).toBe(false);
    expect(has(receiptLines({ ...base, discount: "0", tax: "0" }), "الضريبة")).toBe(false);
    expect(receiptLines({ ...base, discount: "0" }).some((x) => x.right === "الخصم")).toBe(false);
    expect(receiptLines({ ...base, tax: "0" }).some((x) => x.right === "الضريبة")).toBe(false);
    const withBoth = receiptLines({ ...base, discount: "3", tax: "2" });
    expect(withBoth.find((x) => x.right === "الخصم").left).toBe("-3.00");
    expect(withBoth.find((x) => x.right === "الضريبة").left).toBe("2.00");
  });

  it("ends with the total, then the footer when given", () => {
    const lines = receiptLines({ ...base, footerNote: "شكراً" });
    expect(lines.find((x) => x.kind === "total")).toEqual({ kind: "total", left: "25.00", right: "الإجمالي" });
    expect(lines.at(-1)).toEqual({ kind: "center", text: "شكراً" });
    expect(receiptLines(base).at(-1).kind).toBe("rule");
  });

  it("omits the receipt number and date lines when absent", () => {
    const kinds = receiptLines({ shopName: "s", items: [], total: "0" }).map((l) => l.kind);
    expect(kinds).toEqual(["title", "rule", "rule", "total", "rule"]);
  });
});
