/** One place decides what an account's avatar shows: a stored picture, or the
 * account's own letters on a colour that never changes for the same account. */

// Chosen for contrast against white letters, not for variety alone.
const PALETTE = [
  "#c2410c",
  "#b45309",
  "#4d7c0f",
  "#15803d",
  "#0f766e",
  "#0369a1",
  "#4338ca",
  "#7e22ce",
  "#be185d",
  "#9f1239",
  "#52525b",
  "#78716c",
];

function hashSeed(seed) {
  let hash = 2166136261;
  for (const char of seed) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  return hash;
}

export function avatarColor(seed) {
  const normalized = String(seed ?? "").trim().toLowerCase();
  return PALETTE[hashSeed(normalized) % PALETTE.length];
}

export function initialsOf(user) {
  const localPart = String(user?.email || "").split("@")[0] || "";
  const source = String(user?.full_name || "").trim() || localPart;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return "؟";
}
