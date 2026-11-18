import React from "react";
import InboxWorkspace from "@/pages/inbox/InboxWorkspace";
import { useInbox } from "@/pages/inbox/InboxProvider";

/** /instagram/requests — message requests: the Direct list opened on its "Requests" folder. */
export default function InstagramRequestsPage() {
  const { setInstagramMode, setInstagramFolder } = useInbox();
  React.useEffect(() => {
    setInstagramMode("direct");
    setInstagramFolder("requests");
  }, [setInstagramMode, setInstagramFolder]);
  return <InboxWorkspace embedded />;
}
