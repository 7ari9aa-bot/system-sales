// Instagram draws a run of messages from one person as a tight stack: 2px apart inside the run and
// a wider gap between runs, the same way its own DM thread reads. Two messages belong to one run
// when they come from the same side and arrive within a minute of each other. A missing timestamp
// never joins two messages, and a system line always breaks the run.

export const IG_GROUP_GAP_MS = 60 * 1000;

const sideOf = (message) => (message?.side === "out" ? "out" : "in");

export function instagramGroup(messages, index, gapMs = IG_GROUP_GAP_MS) {
  const list = Array.isArray(messages) ? messages : [];
  const current = list[index];
  if (!current) return { first: true, last: true, alone: true, size: 1 };
  const side = sideOf(current);
  const at = (i) => {
    const message = list[i];
    if (!message) return false;
    if (sideOf(message) !== side) return false;
    if (message.senderType === "system" || current.senderType === "system") return false;
    const a = new Date(current.createdAt || 0).getTime();
    const b = new Date(message.createdAt || 0).getTime();
    if (!a || !b) return false;
    return Math.abs(a - b) <= gapMs;
  };
  const first = !at(index - 1);
  const last = !at(index + 1);
  let size = 1;
  for (let i = index - 1; at(i); i -= 1) size += 1;
  for (let i = index + 1; at(i); i += 1) size += 1;
  return { first, last, alone: first && last, size };
}
