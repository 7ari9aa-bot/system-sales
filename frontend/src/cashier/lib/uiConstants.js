// UI-only constants: the colour swatches and size sets offered on the product form, and the colour chip
// used in tables. These are pickers, not shop data: nothing here is read as a record of what the shop sells.
// (Which colours and sizes a shop offers is the shop's own choice and belongs in its settings, later.)

export const COLORS = [
  { name: "أسود", hex: "#18181B" },
  { name: "أبيض", hex: "#F4F4F5" },
  { name: "كحلي", hex: "#1E3A8A" },
  { name: "أزرق فاتح", hex: "#60A5FA" },
  { name: "رمادي", hex: "#6B7280" },
  { name: "بيج", hex: "#D6C3A5" },
  { name: "أحمر", hex: "#B91C1C" },
  { name: "أخضر زيتي", hex: "#4D7C0F" },
  { name: "وردي", hex: "#F472B6" },
  { name: "بني", hex: "#78350F" },
];

export const SIZE_SETS = {
  clothing: ["S", "M", "L", "XL", "XXL"],
  kids: ["2 سنة", "4 سنوات", "6 سنوات", "8 سنوات"],
  shoes: ["39", "40", "41", "42", "43"],
  one: ["مقاس واحد"],
};

export function colorHex(name) {
  return COLORS.find((c) => c.name === name)?.hex ?? "#A1A1AA";
}

/** Stock level of a quantity against a reorder level. The level comes from the backend; there is no default. */
export function stockStatus(qty, threshold) {
  if (qty <= 0) return "out";
  if (Number.isFinite(threshold) && qty <= threshold) return "low";
  return "in";
}
