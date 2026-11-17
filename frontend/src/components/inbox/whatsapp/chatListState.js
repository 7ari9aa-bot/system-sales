// The rules of the WhatsApp-style chat list, kept free of React so they can be
// tested on their own. The server owns the facts (pinned_at, muted_until,
// archived_at, marked_unread); this file only decides how a list of rows is
// filtered, searched and ordered.

export const TABS = ["all", "unread", "waiting", "approvals"];

// Muted until a date. The server writes year 9999 for "always".
export function isMuted(row, now = Date.now()) {
  if (!row?.mutedUntil) return false;
  const until = new Date(row.mutedUntil).getTime();
  return Number.isFinite(until) && until > now;
}

export function isMutedForever(row, now = Date.now()) {
  return isMuted(row, now) && new Date(row.mutedUntil).getUTCFullYear() >= 9000;
}

// A chat counts as unread when it has unread messages OR staff marked it so by hand.
export function isUnread(row) {
  return (Number(row?.unread) || 0) > 0 || Boolean(row?.markedUnread);
}

// The number in the green badge. A manual "mark as unread" has no count, so it
// shows a dot instead (null), exactly like WhatsApp.
export function badgeCount(row) {
  const n = Number(row?.unread) || 0;
  return n > 0 ? n : null;
}

const matchesTab = {
  all: () => true,
  unread: (row) => isUnread(row),
  waiting: (row) => row.status !== "resolved" && row.status !== "approval",
  approvals: (row) => Boolean(row.approval) || row.status === "approval",
};

// Arabic search that behaves: ignore diacritics and tatweel, fold the alef and
// ya/ta-marbuta variants, and read Arabic-Indic digits as ASCII so a phone number
// typed either way finds the same chat.
export function normalizeSearch(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[\u064B-\u065F\u0670\u0640]/g, "")
    .replace(/[أإآٱ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .trim();
}

export function matchesQuery(row, query) {
  const needle = normalizeSearch(query);
  if (!needle) return true;
  const hay = normalizeSearch(`${row.customer ?? ""} ${row.phone ?? ""} ${row.preview ?? ""}`);
  return hay.includes(needle);
}

// Pinned chats first (newest pin first), then everyone else in the order the
// server sent them (newest message first). The sort is stable and never
// reorders the unpinned rows, so paging cannot make a row jump.
export function orderRows(rows) {
  const pinned = [];
  const rest = [];
  for (const row of rows) (row.pinnedAt ? pinned : rest).push(row);
  pinned.sort((a, b) => new Date(b.pinnedAt).getTime() - new Date(a.pinnedAt).getTime());
  return [...pinned, ...rest];
}

export function visibleRows(rows, { tab = "all", query = "", archived = false } = {}) {
  const test = matchesTab[tab] || matchesTab.all;
  const inView = rows.filter((row) => Boolean(row.archivedAt) === archived);
  return orderRows(inView.filter((row) => test(row) && matchesQuery(row, query)));
}

export function tabCounts(rows) {
  const live = rows.filter((row) => !row.archivedAt);
  return {
    all: live.length,
    unread: live.filter(matchesTab.unread).length,
    waiting: live.filter(matchesTab.waiting).length,
    approvals: live.filter(matchesTab.approvals).length,
    archived: rows.length - live.length,
  };
}

// "Today" shows the time, "Yesterday" the word, within a week the weekday, then a date.
export function listTimestamp(iso, lang = "ar", now = new Date()) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const loc = lang === "ar" ? "ar-EG" : "en-GB";
  const startOf = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(date)) / 86400000);
  if (days <= 0) return date.toLocaleTimeString(loc, { hour: "2-digit", minute: "2-digit" });
  if (days === 1) return lang === "ar" ? "أمس" : "Yesterday";
  if (days < 7) return date.toLocaleDateString(loc, { weekday: "long" });
  return date.toLocaleDateString(loc, { day: "2-digit", month: "2-digit", year: "numeric" });
}

export const MUTE_CHOICES = ["8h", "1w", "always"];
