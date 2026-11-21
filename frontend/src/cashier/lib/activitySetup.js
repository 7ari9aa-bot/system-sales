/**
 * The first-run activity setup (backend: GET /activity-setup, POST /activity-setup/complete and
 * /skip). The server decides who is asked (`needs_setup`: a new owner who may change settings and
 * has not answered); this module only turns its answer into what the screen shows and sends.
 *
 * Three rules this file keeps:
 *  - It never traps anyone. A missing, odd or failed answer reads as "do not ask".
 *  - Only the sectors that behave differently can be chosen. The rest are listed as "coming soon"
 *    and cannot be picked, so no sector the platform does not serve yet can reach the server.
 *  - The preset is sent only when the owner left "apply these settings" on.
 */

/** Sectors the platform serves today (backend CHOOSABLE_VERTICALS). Their ids are the server's. */
export const CHOOSABLE = Object.freeze(["apparel", "general"]);

/** Shown for what is coming, in the order the owner reads them. They carry no server id. */
export const COMING_SOON = Object.freeze([
  { key: "pharmacy", label: "صيدلية" },
  { key: "supermarket", label: "سوبر ماركت" },
  { key: "restaurant", label: "مطعم" },
  { key: "electronics", label: "إلكترونيات" },
  { key: "wholesale", label: "جملة وتوزيع" },
]);

const LABELS = Object.freeze({
  apparel: { label: "ملابس", hint: "مقاسات وألوان، وإعدادات جاهزة لمحل ملابس" },
  general: { label: "نشاط عام", hint: "من غير إعدادات جاهزة، وتضبط كل حاجة بنفسك" },
});

/** The state the screen acts on. Anything but a clear "yes, ask" is "do not ask". */
export function normaliseSetup(raw) {
  const none = { needsSetup: false, state: "done", choices: [], presets: {}, presetKeys: {} };
  if (!raw || typeof raw !== "object" || raw.needs_setup !== true) return none;
  const choices = Array.isArray(raw.choices) ? raw.choices.filter((c) => CHOOSABLE.includes(c)) : [];
  // A server that offers nothing we can show has nothing to ask.
  if (choices.length === 0) return none;
  const presets = raw.presets && typeof raw.presets === "object" ? raw.presets : {};
  const presetKeys = raw.preset_keys && typeof raw.preset_keys === "object" ? raw.preset_keys : {};
  return { needsSetup: true, state: String(raw.state ?? "not_started"), choices, presets, presetKeys };
}

/** What the owner can reopen from settings: only after the setup was answered, never while it is due. */
export function canReopen(raw) {
  return !!raw && typeof raw === "object" && (raw.state === "done" || raw.state === "skipped");
}

/** The cards: the choosable sectors first (selectable), then the coming-soon ones (disabled). */
export function sectorCards(setup) {
  const live = (setup?.choices ?? []).map((id) => ({
    id,
    label: LABELS[id]?.label ?? id,
    hint: LABELS[id]?.hint ?? "",
    disabled: false,
  }));
  const soon = COMING_SOON.map((s) => ({ id: s.key, label: s.label, hint: "قريباً", disabled: true }));
  return [...live, ...soon];
}

/** Whether a card can be picked. A coming-soon card, or anything the server did not offer, cannot. */
export function isSelectable(setup, id) {
  return (setup?.choices ?? []).includes(id) && CHOOSABLE.includes(id);
}

/** The preset a sector offers, or null when it offers none (a general shop sets nothing). */
export function presetFor(setup, id) {
  const name = setup?.presets?.[id];
  return typeof name === "string" && name ? name : null;
}

/** How many switches the preset would set, so the owner sees what "apply" means. 0 when none. */
export function presetCount(setup, id) {
  const keys = setup?.presetKeys?.[id];
  return Array.isArray(keys) ? keys.length : 0;
}

/**
 * The body for POST /activity-setup/complete, or null when the choice cannot be sent. A sector
 * that is not selectable is never sent, and the preset flag is true only for a sector that has a
 * preset and only when the owner left it on.
 */
export function completeBody(setup, id, applyPreset) {
  if (!isSelectable(setup, id)) return null;
  return { vertical: id, apply_preset: presetFor(setup, id) !== null && applyPreset === true };
}
