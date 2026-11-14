// The assistant's dialect setting, as pure functions so the screen stays thin and the rules are tested.
//
// The server owns the list: it returns `choices`, and a value outside it is never sent. "Automatic"
// is a UI choice, not a stored value: it means "clear my choice, use my currency's dialect", and the
// server clears on an explicit null. So the body for automatic carries `dialect: null` rather than
// omitting the key, because an omitted key and a null are different requests to this API.

export const AUTO = "auto";

const SOURCES = new Set(["owner", "currency", "default"]);

function listed(info) {
  const seen = [];
  for (const item of Array.isArray(info?.choices) ? info.choices : []) {
    if (typeof item === "string" && item && !seen.includes(item)) seen.push(item);
  }
  return seen;
}

export function dialectOptions(info) {
  return [AUTO, ...listed(info)].map((value) => ({ value }));
}

// What the select should show for what the server holds.
export function selectionFrom(info) {
  const stored = info?.dialect;
  return typeof stored === "string" && listed(info).includes(stored) ? stored : AUTO;
}

// The PUT body: only a key the server offered, otherwise an explicit null (clear).
export function dialectBody(selection, choices) {
  const ok = typeof selection === "string" && selection !== AUTO && (choices || []).includes(selection);
  return { dialect: ok ? selection : null };
}

// i18n key naming where the dialect in use came from.
export function sourceKey(info) {
  const source = info?.source;
  return `dialect.source.${SOURCES.has(source) ? source : "default"}`;
}

// Whether saving would change anything. False before the server has answered, so an empty screen
// cannot write over what is stored.
export function isDirty(selection, info) {
  if (!info || listed(info).length === 0) return false;
  return selection !== selectionFrom(info);
}
