// How Facebook lists notifications: "New" (the last day) above "Earlier", an All / Unread switch,
// and the older ones folded behind "See previous notifications".

export const NEW_WINDOW_MS = 24 * 60 * 60 * 1000;
export const FIRST_SHOWN = 8;

const time = (item) => {
  const t = new Date(item.comment?.commentedAt || 0).getTime();
  return Number.isFinite(t) ? t : 0;
};

/**
 * items: [{ comment, post, waiting }]. "Unread" is what still waits for the Page's answer: the API
 * has no read state for a Page's comments, so this is the honest equivalent.
 */
export function groupNotifications(items, { now = Date.now(), onlyUnread = false, showAll = false } = {}) {
  const kept = (onlyUnread ? items.filter((i) => i.waiting) : items).slice().sort((a, b) => time(b) - time(a));
  const fresh = kept.filter((i) => time(i) > 0 && now - time(i) < NEW_WINDOW_MS);
  const older = kept.filter((i) => !(time(i) > 0 && now - time(i) < NEW_WINDOW_MS));
  const earlier = showAll ? older : older.slice(0, FIRST_SHOWN);
  return { fresh, earlier, hiddenCount: older.length - earlier.length };
}
