import { Navigate } from "react-router-dom";

export const MESSENGER_INBOX = "/inbox?channel=messenger";

/** Messenger has its own channel. Old /facebook/messages links open it there. */
export default function FacebookMessagesRedirect() {
  return <Navigate to={MESSENGER_INBOX} replace />;
}
