/**
 * ESC/POS binary command generator for 58mm (32 chars) and 80mm (48 chars) thermal printers.
 */

const ESC = 0x1b;
const GS = 0x1d;

export const COMMANDS = {
  INIT: new Uint8Array([ESC, 0x40]),
  ALIGN_LEFT: new Uint8Array([ESC, 0x61, 0x00]),
  ALIGN_CENTER: new Uint8Array([ESC, 0x61, 0x01]),
  ALIGN_RIGHT: new Uint8Array([ESC, 0x61, 0x02]),
  BOLD_ON: new Uint8Array([ESC, 0x45, 0x01]),
  BOLD_OFF: new Uint8Array([ESC, 0x45, 0x00]),
  DOUBLE_SIZE_ON: new Uint8Array([GS, 0x21, 0x11]),
  NORMAL_SIZE: new Uint8Array([GS, 0x21, 0x00]),
  CUT_FULL: new Uint8Array([GS, 0x56, 0x00]),
  CUT_PARTIAL: new Uint8Array([GS, 0x56, 0x01]),
  // Cash drawer kick: ESC p m t1 t2 (pin 2, 50ms on, 500ms off)
  DRAWER_KICK: new Uint8Array([ESC, 0x70, 0x00, 0x19, 0xfa]),
  DRAWER_KICK_PIN5: new Uint8Array([ESC, 0x70, 0x01, 0x19, 0xfa]),
};

function concatUint8Arrays(...arrays) {
  const totalLength = arrays.reduce((acc, curr) => acc + curr.length, 0);
  const result = new Uint8Array(totalLength);
  let offset = 0;
  for (const arr of arrays) {
    result.set(arr, offset);
    offset += arr.length;
  }
  return result;
}

function encodeText(text) {
  return new TextEncoder().encode(text);
}

function padLine(left, right, width = 42) {
  const leftStr = String(left || "");
  const rightStr = String(right || "");
  const spaceCount = Math.max(1, width - leftStr.length - rightStr.length);
  return leftStr + " ".repeat(spaceCount) + rightStr + "\n";
}

/**
 * Builds an ESC/POS byte array for a receipt.
 * @param {Object} options
 * @param {string} options.shopName
 * @param {string} options.receiptNumber
 * @param {string} options.date
 * @param {Array<{name: string, quantity: number, unit_price: string|number, total: string|number}>} options.items
 * @param {string|number} options.total
 * @param {string|number} [options.tax]
 * @param {string|number} [options.discount]
 * @param {string} [options.footerNote]
 * @param {boolean} [options.cut=true]
 * @param {number} [options.width=42]
 */
export function buildReceiptEscPos({
  shopName = "FIHRIST STORE",
  receiptNumber = "",
  date = new Date().toLocaleString(),
  items = [],
  total = "0.00",
  tax,
  discount,
  footerNote = "Thank you for your visit!",
  cut = true,
  width = 42,
} = {}) {
  const parts = [COMMANDS.INIT];

  // Header: Centered, Bold
  parts.push(COMMANDS.ALIGN_CENTER);
  parts.push(COMMANDS.BOLD_ON);
  parts.push(COMMANDS.DOUBLE_SIZE_ON);
  parts.push(encodeText(`${shopName}\n`));
  parts.push(COMMANDS.NORMAL_SIZE);
  parts.push(COMMANDS.BOLD_OFF);

  if (receiptNumber) {
    parts.push(encodeText(`Receipt #: ${receiptNumber}\n`));
  }
  parts.push(encodeText(`${date}\n`));
  parts.push(encodeText("-".repeat(width) + "\n"));

  // Line Items: Left-aligned
  parts.push(COMMANDS.ALIGN_LEFT);
  for (const item of items) {
    const name = item.name || "Item";
    const qtyPrice = `${item.quantity} x ${Number(item.unit_price || 0).toFixed(2)}`;
    const lineTotal = Number(item.total || (item.quantity * Number(item.unit_price || 0))).toFixed(2);
    parts.push(encodeText(padLine(name, lineTotal, width)));
    if (item.quantity > 1) {
      parts.push(encodeText(`  ${qtyPrice}\n`));
    }
  }

  parts.push(encodeText("-".repeat(width) + "\n"));

  // Totals
  if (discount && Number(discount) > 0) {
    parts.push(encodeText(padLine("Discount:", `-${Number(discount).toFixed(2)}`, width)));
  }
  if (tax && Number(tax) > 0) {
    parts.push(encodeText(padLine("Tax:", Number(tax).toFixed(2), width)));
  }

  parts.push(COMMANDS.BOLD_ON);
  parts.push(encodeText(padLine("TOTAL:", Number(total).toFixed(2), width)));
  parts.push(COMMANDS.BOLD_OFF);

  parts.push(encodeText("=".repeat(width) + "\n"));

  // Footer: Centered
  parts.push(COMMANDS.ALIGN_CENTER);
  if (footerNote) {
    parts.push(encodeText(`${footerNote}\n`));
  }
  parts.push(encodeText("\n\n\n")); // Feed paper

  if (cut) {
    parts.push(COMMANDS.CUT_PARTIAL);
  }

  return concatUint8Arrays(...parts);
}
