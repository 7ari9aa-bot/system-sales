/** What to show while the assistant works, from what the server has really recorded.
 *
 *  The server writes a short Arabic line each time the assistant truly starts something (reading
 *  sales, checking stock). This file only decides how to PRESENT those lines; it never invents one.
 *  It is plain functions so the rules can be tested without a browser.
 */

/** The row the server is still writing: the newest assistant message that is not finished. */
export function generatingRow(messages) {
  const open = (messages ?? []).filter(
    (m) => m?.role === "assistant" && (m.status === "generating" || m.status === "pending"),
  );
  if (open.length === 0) return null;
  return open.reduce((a, b) => ((b.sequence_no ?? 0) >= (a.sequence_no ?? 0) ? b : a));
}

/** The lines to show, oldest first: only real, non-empty strings, each once. */
export function stepsOf(row) {
  const raw = Array.isArray(row?.progress) ? row.progress : [];
  const seen = new Set();
  const out = [];
  for (const line of raw) {
    if (typeof line !== "string") continue;
    const text = line.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
  }
  return out;
}

/** Messages with the unfinished assistant row taken out.
 *
 *  That row is shown by the thinking indicator (with its steps); leaving it in the list as well
 *  would draw the same pending answer twice. */
export function withoutUnfinished(messages) {
  return (messages ?? []).filter(
    (m) => !(m?.role === "assistant" && (m.status === "generating" || m.status === "pending")),
  );
}

/** Poll only while a question is in flight, and not faster than the server can add a step. */
export const POLL_MS = 1500;

export function pollInterval(sending) {
  return sending ? POLL_MS : false;
}

/** Whether the question just typed is already in the list the server returned.
 *
 *  The server saves the question before it starts on the answer, so once the list is polled during
 *  the wait the same question comes back from the server. The temporary copy shown at once must
 *  then go, or the owner sees what they asked twice. Matching is by text AND by the answer still
 *  being open: asking the very same thing a second time later must still show the new copy. */
export function questionAlreadyListed(messages, outgoingText) {
  if (!outgoingText) return false;
  const row = generatingRow(messages);
  if (!row) return false;
  const asked = (messages ?? []).find(
    (m) => m?.role === "user" && (m.sequence_no ?? 0) === (row.sequence_no ?? 0) - 1,
  );
  return !!asked && (asked.content ?? "").trim() === outgoingText.trim();
}

/** Whether the answer to the question just sent is already in the list.
 *
 *  The server saves the answer and then keeps working for a moment (it tidies the thread and
 *  writes a title) before the send request returns. A poll in that gap already holds the finished
 *  answer, and the wait indicator must not sit under it.
 *
 *  It must be THE question just sent, not merely the newest one in the list: right after the owner
 *  presses send the list still ends with an older, already answered question, and reading that as
 *  "answered" would hide the indicator for the whole first second. So the sent text is matched to
 *  a user row, and that row's own next-numbered answer must be finished (completed or failed). */
export function sentQuestionIsAnswered(messages, sentText) {
  if (!sentText) return false;
  const list = messages ?? [];
  const wanted = sentText.trim();
  const rows = list.filter((m) => m?.role === "user" && (m.content ?? "").trim() === wanted);
  if (rows.length === 0) return false;
  // the same words may have been asked before: the newest one is the one just sent
  const row = rows.reduce((a, b) => ((b.sequence_no ?? 0) >= (a.sequence_no ?? 0) ? b : a));
  return list.some(
    (m) =>
      m?.role === "assistant" &&
      (m.sequence_no ?? 0) === (row.sequence_no ?? 0) + 1 &&
      (m.status === "completed" || m.status === "failed"),
  );
}
