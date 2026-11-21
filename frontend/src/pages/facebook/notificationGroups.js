// How Facebook lists notifications: "New" (the last day) above "Earlier", an All / Unread switch,
// and the older ones folded behind "See previous notifications".

export const NEW_WINDOW_MS = 24 * 60 * 60 * 1000;
export const FIRST_SHOWN = 8;

const time = (item) => {
  const t = new Date(item.comment?.commentedAt || 0).getTime();
  return Number.isFinite(t) ? t : 0;
};

/** Unread = still waits for the Page's answer and is newer than the "mark all as read" time. */
export function isUnread(item, readUpTo = 0) {
  return !!item.waiting && time(item) > readUpTo;
}

const key = (scope) => `fb-notif-read:${scope}`;

/** The "read up to" time kept in the browser (Meta gives no read state). 0 when absent or unreadable. */
export function loadReadMark(storage, scope) {
  try {
    const n = Number(storage?.getItem(key(scope)));
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

export function saveReadMark(storage, scope, at) {
  try {
    storage?.setItem(key(scope), String(at));
  } catch {
    /* storage full or blocked: the mark just isn't remembered */
  }
}

/**
 * items: [{ comment, post, waiting }]. "Unread" is what still waits for the Page's answer: the API
 * has no read state for a Page's comments, so this is the honest equivalent.
 */
export function groupNotifications(items, { now = Date.now(), onlyUnread = false, showAll = false, readUpTo = 0 } = {}) {
  const kept = (onlyUnread ? items.filter((i) => isUnread(i, readUpTo)) : items).slice().sort((a, b) => time(b) - time(a));
  const fresh = kept.filter((i) => time(i) > 0 && now - time(i) < NEW_WINDOW_MS);
  const older = kept.filter((i) => !(time(i) > 0 && now - time(i) < NEW_WINDOW_MS));
  const earlier = showAll ? older : older.slice(0, FIRST_SHOWN);
  return { fresh, earlier, hiddenCount: older.length - earlier.length };
}

/** What the "..." button in the header offers, in Facebook's order. Settings opens where the Page is connected. */
export function headerMenuItems(lang) {
  const ar = lang === "ar";
  return [
    { id: "markAllRead", label: ar ? "تمييز الكل كمقروء" : "Mark all as read" },
    { id: "settings", label: ar ? "إعدادات الإشعارات" : "Notification settings", to: "/settings/channels" },
  ];
}
