import React from "react";
import MembersSettings from "../MembersSettings";

/** The roster on its own: who is in the workspace and what role they carry.
 *
 * The markup lives in MembersSettings, which takes a ``view``. Duplicating the table
 * here would mean two places to fix the next time the roster changes shape.
 */
export default function TeamMembersSection() {
  return <MembersSettings view="members" />;
}
