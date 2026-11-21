import { CHANNELS } from "@/lib/channels";

/** "?channel=messenger" on /inbox opens that channel. Unknown ids are ignored. */
export function channelFromSearch(search) {
  if (!search) return null;
  const id = new URLSearchParams(search).get("channel");
  return id && CHANNELS.some((channel) => channel.id === id) ? id : null;
}

/** The /inbox link that opens a given channel. */
export function inboxPathFor(channelId) {
  return `/inbox?channel=${encodeURIComponent(channelId)}`;
}
