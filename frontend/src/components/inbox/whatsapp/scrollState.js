// Pure helpers for the "jump to latest" button, kept free of React so they test.

// Far enough from the bottom that the user is reading history, not following.
export const AWAY_FROM_BOTTOM_PX = 240;

export function distanceFromBottom({ scrollHeight, scrollTop, clientHeight }) {
  return Math.max(0, scrollHeight - scrollTop - clientHeight);
}

export function isAwayFromBottom(metrics, threshold = AWAY_FROM_BOTTOM_PX) {
  return distanceFromBottom(metrics) > threshold;
}

// Incoming messages that arrived while the user was scrolled up. Our own sends
// never count: the chat jumps to them anyway.
export function unreadSince(messages, lastSeenId) {
  const list = Array.isArray(messages) ? messages : [];
  if (lastSeenId == null) return 0;
  const at = list.findIndex((m) => m.id === lastSeenId);
  if (at === -1) return 0;
  return list.slice(at + 1).filter((m) => m.side === "in" && m.senderType !== "system").length;
}
