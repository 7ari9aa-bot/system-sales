/**
 * Forgiving text matching for the till, mirroring `arabic_regex` in the backend (core/sql.py).
 *
 * A catalogue is entered once, carefully ("أحمر", "حقيبة", "مِعطف"); it is searched all day on any
 * keyboard ("احمر", "حقيبه", "معطف", digits as ٠١٢). Both sides are folded to one spelling before
 * they are compared, so the browser-side search and the server-side search agree on what matches.
 * Keep the two tables below in step with the backend's `_ARABIC_CLASSES`.
 */

const ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩";
const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

// One folded letter per class of interchangeable spellings.
const FOLD = {
  أ: "ا", إ: "ا", آ: "ا", ٱ: "ا",
  ة: "ه",
  ى: "ي", ئ: "ي",
  ؤ: "و",
};

// Tashkeel (U+064B-U+065F, U+0670) and tatweel (U+0640): typed or stored, they never change the word.
const MARKS = /[\u064B-\u065F\u0670\u0640]/g;

/** Arabic-Indic and Persian digits to ASCII, so `٠٠٢٩٩٩` finds `002999`. */
export function toAsciiDigits(text) {
  return String(text ?? "").replace(/[٠-٩۰-۹]/g, (d) => {
    const i = ARABIC_DIGITS.indexOf(d);
    return String(i >= 0 ? i : PERSIAN_DIGITS.indexOf(d));
  });
}

/** Lower-case, ASCII digits, no tashkeel, one spelling per Arabic letter. */
export function foldText(text) {
  return toAsciiDigits(text)
    .toLowerCase()
    .replace(MARKS, "")
    .replace(/[أإآٱةىئؤ]/g, (ch) => FOLD[ch])
    .trim();
}

/** The same as `foldText` with separators dropped, for codes ("R-002999" == "R002999"). */
export function foldCode(text) {
  return foldText(text).replace(/[-/\s]+/g, "");
}

/** True when the typed term is a code: ASCII letters/digits and separators only. */
function isCode(folded) {
  return folded !== "" && /^[a-z0-9\-/\s]+$/.test(folded);
}

/** Does `haystack` contain `needle` once both are folded the same way? */
export function foldedIncludes(haystack, needle) {
  const n = foldText(needle);
  if (!n) return false;
  if (isCode(n)) return foldCode(haystack).includes(foldCode(n));
  return foldText(haystack).includes(n);
}
