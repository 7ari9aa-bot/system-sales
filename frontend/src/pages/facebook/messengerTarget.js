/** Where the Messenger button goes. An unconnected channel would make the inbox bounce the owner
 *  straight back to Facebook, so that case sends them to where Messenger is connected instead. */
export function messengerTarget(channels) {
  const row = (channels || []).find((channel) => channel.id === "messenger");
  return row?.connected ? { kind: "channel", id: "messenger" } : { kind: "settings", path: "/settings/channels" };
}
