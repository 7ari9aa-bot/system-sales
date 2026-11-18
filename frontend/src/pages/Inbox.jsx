import React from "react";
import { InboxProvider } from "@/pages/inbox/InboxProvider";
import InboxWorkspace from "@/pages/inbox/InboxWorkspace";

/** /inbox: the classic multi-channel inbox. The state lives in InboxProvider so the
 *  Instagram pages (/instagram/*) share the same conversations without reloading. */
export default function Inbox() {
  return (
    <InboxProvider>
      <InboxWorkspace />
    </InboxProvider>
  );
}
