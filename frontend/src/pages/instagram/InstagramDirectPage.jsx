import React from "react";
import InboxWorkspace from "@/pages/inbox/InboxWorkspace";
import { useInbox } from "@/pages/inbox/InboxProvider";

/** /instagram/direct and /instagram/direct/:conversationId — the Instagram DM list and chat. */
export default function InstagramDirectPage() {
  const { setInstagramMode } = useInbox();
  React.useEffect(() => { setInstagramMode("direct"); }, [setInstagramMode]);
  return <InboxWorkspace embedded />;
}
