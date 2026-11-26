import React from "react";
import MembersSettings from "../MembersSettings";

/** Invitations on their own: create one, copy the link, revoke a pending one.
 *
 * Same implementation as the roster page, different view — the invite form and the
 * pending list are the whole page here.
 */
export default function TeamInvitationsSection() {
  return <MembersSettings view="invitations" />;
}
