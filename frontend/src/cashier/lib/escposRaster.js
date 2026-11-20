/**
 * Receipt as a picture, for thermal printers that cannot print Arabic text.
 *
 * Most receipt printers take UTF-8 bytes as if they were a Latin code page, so an Arabic shop or
 * product name comes out as symbols. A bitmap does not depend on the printer's code page or fonts,
 * so it prints the same on any ESC/POS model. The pure part (pixels to bytes) is here and tested;
 * drawing the receipt onto a canvas is the thin part at the bottom.
 */

const GS = 0x1d;
const ESC = 0x1b;

/** Dots across the paper: 58mm heads are 384 wide, 80mm heads 576 (the common values). */
export const PAPER_DOTS = { 58: 384, 80: 576 };

/** A slice taller than this is split, because some printers' buffers refuse a taller one. */
export const MAX_SLICE_ROWS = 255;

const DARK_BELOW = 128;

/**
 * RGBA pixels to one bit per dot, 1 = black. A transparent pixel is paper, not black, because a
 * canvas starts transparent and an unpainted corner must not print as a black block.
 */
export function toBits(rgba, width, height) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
    throw new RangeError("the picture needs a positive width and height");
  }
  if (rgba.length !== width * height * 4) {
    throw new RangeError("the pixel data does not match the picture size");
  }
  const bytesPerRow = Math.ceil(width / 8);
  const out = new Uint8Array(bytesPerRow * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4;
      // integer maths: the weights sum to 1000, so a grey of 128 is exactly 128 and sits on the
      // paper side of the line instead of a float's 127.99999 tipping it to black
      const a = rgba[i + 3];
      const mixed = (rgba[i] * 299 + rgba[i + 1] * 587 + rgba[i + 2] * 114) * a + 255000 * (255 - a);
      const lum = mixed / (1000 * 255);
      if (lum < DARK_BELOW) out[y * bytesPerRow + (x >> 3)] |= 0x80 >> (x & 7);
    }
  }
  return { bits: out, bytesPerRow };
}

/** GS v 0: print a raster slice. xL xH are bytes per row, yL yH the rows in this slice. */
export function rasterCommand(bits, bytesPerRow, rows) {
  if (rows < 1 || rows > 0xffff || bytesPerRow < 1 || bytesPerRow > 0xffff) {
    throw new RangeError("raster slice is out of range");
  }
  if (bits.length !== bytesPerRow * rows) {
    throw new RangeError("the slice does not match its size");
  }
  const head = [GS, 0x76, 0x30, 0x00, bytesPerRow & 0xff, bytesPerRow >> 8, rows & 0xff, rows >> 8];
  const out = new Uint8Array(head.length + bits.length);
  out.set(head, 0);
  out.set(bits, head.length);
  return out;
}

/**
 * The full byte stream for a picture: initialise, the picture in slices, feed, cut.
 * Slices keep every row of the picture, in order, none repeated or dropped.
 */
export function pictureToEscPos(rgba, width, height, { cut = true, feed = 3 } = {}) {
  const { bits, bytesPerRow } = toBits(rgba, width, height);
  const parts = [new Uint8Array([ESC, 0x40])];
  for (let row = 0; row < height; row += MAX_SLICE_ROWS) {
    const rows = Math.min(MAX_SLICE_ROWS, height - row);
    parts.push(
      rasterCommand(bits.subarray(row * bytesPerRow, (row + rows) * bytesPerRow), bytesPerRow, rows),
    );
  }
  parts.push(new Uint8Array([ESC, 0x64, Math.max(0, Math.min(255, feed))]));
  if (cut) parts.push(new Uint8Array([GS, 0x56, 0x01]));
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

/** One printed line of the receipt: label on one side, amount on the other. */
export function receiptLines({
  shopName,
  receiptNumber,
  date,
  items = [],
  total,
  discount,
  tax,
  footerNote,
}) {
  const money = (v) => Number(v || 0).toFixed(2);
  const lines = [{ kind: "title", text: String(shopName ?? "") }];
  if (receiptNumber) lines.push({ kind: "center", text: `رقم الإيصال: ${receiptNumber}` });
  if (date) lines.push({ kind: "center", text: String(date) });
  lines.push({ kind: "rule" });
  for (const it of items) {
    const qty = Number(it.quantity);
    const price = Number(it.unit_price || 0);
    const lineTotal = it.total ?? qty * price;
    lines.push({ kind: "row", left: money(lineTotal), right: String(it.name ?? "") });
    if (qty > 1) lines.push({ kind: "sub", text: `${qty} × ${money(price)}` });
  }
  lines.push({ kind: "rule" });
  if (Number(discount) > 0) lines.push({ kind: "row", left: `-${money(discount)}`, right: "الخصم" });
  if (Number(tax) > 0) lines.push({ kind: "row", left: money(tax), right: "الضريبة" });
  lines.push({ kind: "total", left: money(total), right: "الإجمالي" });
  lines.push({ kind: "rule" });
  if (footerNote) lines.push({ kind: "center", text: String(footerNote) });
  return lines;
}

/**
 * Draw the lines on a canvas and return the pixels. Browser only (needs a canvas), so it is kept
 * thin: all the decisions are in the functions above.
 */
export function drawReceipt(lines, { paperMm = 80, font = "Tahoma, 'Noto Naskh Arabic', Arial, sans-serif" } = {}) {
  const width = PAPER_DOTS[paperMm] ?? PAPER_DOTS[80];
  const pad = 12;
  const lineHeight = 34;
  const height = lines.reduce((h, l) => h + (l.kind === "title" ? 52 : l.kind === "rule" ? 16 : lineHeight), pad * 2);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#000";
  ctx.direction = "rtl";
  ctx.textBaseline = "middle";
  let y = pad;
  for (const l of lines) {
    if (l.kind === "title") {
      ctx.font = `bold 32px ${font}`;
      ctx.textAlign = "center";
      ctx.fillText(l.text, width / 2, y + 26);
      y += 52;
    } else if (l.kind === "rule") {
      ctx.fillRect(pad, y + 7, width - pad * 2, 2);
      y += 16;
    } else if (l.kind === "row" || l.kind === "total") {
      ctx.font = `${l.kind === "total" ? "bold " : ""}24px ${font}`;
      ctx.textAlign = "right";
      ctx.fillText(l.right, width - pad, y + lineHeight / 2);
      ctx.textAlign = "left";
      ctx.fillText(l.left, pad, y + lineHeight / 2);
      y += lineHeight;
    } else {
      ctx.font = `22px ${font}`;
      ctx.textAlign = l.kind === "sub" ? "right" : "center";
      ctx.fillText(l.text, l.kind === "sub" ? width - pad - 16 : width / 2, y + lineHeight / 2);
      y += lineHeight;
    }
  }
  const { data } = ctx.getImageData(0, 0, width, height);
  return { rgba: data, width, height };
}

/** The whole job: receipt data in, printer bytes out. */
export function buildReceiptRaster(receipt, { paperMm = 80, cut = true } = {}) {
  const { rgba, width, height } = drawReceipt(receiptLines(receipt), { paperMm });
  return pictureToEscPos(rgba, width, height, { cut });
}
