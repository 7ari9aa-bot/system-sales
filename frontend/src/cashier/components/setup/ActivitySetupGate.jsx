import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useActivitySetup } from "@/cashier/api/useActivitySetup";
import ActivitySetupDialog from "./ActivitySetupDialog";

/**
 * Mounted once in the dashboard layout, so it covers the dashboard and the till. It shows the
 * setup only when the server says this owner is due (a new owner who may change settings), and it
 * shows nothing at all while loading or if the answer cannot be read. A cashier, a returning
 * owner and an owner who skipped are never due, so for them this renders nothing.
 */
export default function ActivitySetupGate() {
  const { setup } = useActivitySetup();
  const navigate = useNavigate();
  const [closed, setClosed] = useState(false);
  if (!setup.needsSetup || closed) return null;
  return (
    <ActivitySetupDialog
      open
      setup={setup}
      onClose={() => setClosed(true)}
      onDone={() => { setClosed(true); navigate("/cashier/pos"); }}
    />
  );
}
