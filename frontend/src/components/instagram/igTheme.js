// Instagram's own web palette and type, in one place so every page matches.
export const IG = {
  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
  text: "#0c1014",
  secondary: "#6a717a",
  border: "#dbdfe4",
  separator: "#dbdfe4",
  hover: "#f3f5f7",
  selected: "#f3f5f7",
  blue: "#0095f6",
  blueHover: "#1877f2",
  blueDisabled: "#4cb5f9",
  link: "#00376b",
  red: "#ff3040",
  error: "#ed4956",
  button: "#f0f2f5",
  buttonHover: "#dbdfe4",
  bubbleOut: "#4a5df9",
  bubbleIn: "#f3f5f7",
  storyRing: "conic-gradient(from 45deg, #feda75, #fa7e1e, #d62976, #962fbf, #4f5bd5, #feda75)",
};

/** "2h", "3d", "1w" like Instagram's lists (Arabic: "٢ س"-style short units, western digits). */
export function igShortTime(iso, lang = "ar") {
  if (!iso) return "";
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  if (!Number.isFinite(diff)) return "";
  const m = Math.floor(diff / 60000);
  const units = lang === "ar"
    ? [["د", 60], ["س", 24], ["ي", 7], ["أ", Infinity]]
    : [["m", 60], ["h", 24], ["d", 7], ["w", Infinity]];
  if (m < 1) return lang === "ar" ? "الآن" : "now";
  let value = m;
  for (const [label, size] of units) {
    if (value < size) return lang === "ar" ? `${value} ${label}` : `${value}${label}`;
    value = Math.floor(value / size);
  }
  return "";
}

/** 1,520 / 15.2K / 1.2M as on a profile ("ألف" / "مليون" in Arabic). */
export function igCount(value, lang = "ar") {
  if (value == null || !Number.isFinite(Number(value))) return null;
  const n = Number(value);
  if (n < 10000) return n.toLocaleString(lang === "ar" ? "ar-EG" : "en-US");
  return new Intl.NumberFormat(lang === "ar" ? "ar-EG" : "en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

/** "November 18" or "18 نوفمبر" under a post, like Instagram. */
export function igLongDate(iso, lang = "ar") {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US", { month: "long", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) });
}
