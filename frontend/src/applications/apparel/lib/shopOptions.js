// The shop's own size sets and colours. The backend (GET /apparel/options) answers with the shop's list, or the
// built-in one when the owner saved nothing. The constants in uiConstants.js are only the fallback for the moment
// before that answer arrives (or if it fails), so the product form is never empty.
import { COLORS, SIZE_SETS } from "@/applications/apparel/lib/uiConstants";

const DEFAULT_LABELS = {
  clothing: "ملابس (S — XXL)",
  kids: "مقاسات أطفال",
  shoes: "مقاسات أحذية",
  one: "مقاس واحد",
};
const FALLBACK_HEX = "#A1A1AA";

/** What the screens use when the backend has not answered: the built-in lists, unchanged. */
export const BUILT_IN_OPTIONS = Object.freeze(normaliseOptions({ size_sets: SIZE_SETS, colours: COLORS }));

/** Backend answer -> { sizeSets: {name: [sizes]}, colours: [{name, hex}] }. A malformed answer keeps the built-ins. */
export function normaliseOptions(raw) {
  const sets = raw && typeof raw.size_sets === "object" && raw.size_sets && !Array.isArray(raw.size_sets) ? raw.size_sets : null;
  const cols = raw && Array.isArray(raw.colours) ? raw.colours : null;
  const sizeSets = {};
  if (sets) {
    for (const [name, sizes] of Object.entries(sets)) {
      if (Array.isArray(sizes) && sizes.length) sizeSets[name] = sizes.map(String);
    }
  }
  const colours = (cols ?? [])
    .filter((c) => c && typeof c.name === "string" && c.name.trim())
    .map((c) => ({ name: c.name, hex: typeof c.hex === "string" && c.hex ? c.hex : null }));
  return {
    sizeSets: Object.keys(sizeSets).length ? sizeSets : { ...SIZE_SETS },
    colours: colours.length ? colours : COLORS.map((c) => ({ ...c })),
    customised: !!raw?.customised,
  };
}

/** The choices for the size-system dropdown: built-in names keep their Arabic label, the shop's own use their name. */
export function sizePresetChoices(sizeSets) {
  return Object.keys(sizeSets).map((key) => ({ key, label: DEFAULT_LABELS[key] ?? key }));
}

/** The set to show now: the one chosen if it still exists, otherwise the first the shop has. */
export function resolveSizePreset(sizeSets, chosen) {
  const keys = Object.keys(sizeSets);
  return keys.includes(chosen) ? chosen : (keys[0] ?? "");
}

/** Colour name -> swatch. A colour the shop no longer lists (old stock) still gets a neutral swatch, never a crash. */
export function colourHex(colours, name) {
  return colours.find((c) => c.name === name)?.hex ?? FALLBACK_HEX;
}

/** The swatch to draw: the shop's own colour wins, then whatever the caller passed, then a neutral grey. */
export function swatchHex(colours, name, passed) {
  const own = colours.find((c) => c.name === name)?.hex;
  return own ?? passed ?? FALLBACK_HEX;
}
