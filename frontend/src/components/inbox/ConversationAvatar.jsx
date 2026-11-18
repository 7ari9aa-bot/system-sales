import React, { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { IgDefaultAvatar } from "@/components/instagram/IgAvatar";

// WhatsApp's default avatar is a grey disc with a person, never a coloured tile with
// initials (those read as bright patches in dark mode and as white-on-pastel in light).
function PersonGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="h-[62%] w-[62%]" fill="currentColor" aria-hidden="true">
      <path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm0 2c-4.1 0-8 2-8 5v1.5h16V19c0-3-3.9-5-8-5Z" />
    </svg>
  );
}

export default function ConversationAvatar({ conversation, className, initialsClassName }) {
  const [imageFailed, setImageFailed] = useState(false);
  const isWhatsApp = conversation?.channel === "whatsapp";
  const isInstagram = conversation?.channel === "instagram";
  const imageUrl = conversation?.avatarUrl || conversation?.profileImageUrl || conversation?.avatar || "";

  useEffect(() => {
    setImageFailed(false);
  }, [imageUrl]);

  return (
    <div
      aria-hidden="true"
      className={cn("relative grid shrink-0 place-items-center overflow-hidden rounded-full font-semibold", className)}
      style={isWhatsApp ? { background: "var(--wa-avatar-bg)", color: "var(--wa-avatar-fg)" } : { background: conversation?.color || "#d9e2e9", color: "#fff" }}
    >
      {isInstagram ? <IgDefaultAvatar className="h-full w-full" /> : isWhatsApp ? <PersonGlyph /> : <span className={initialsClassName}>{conversation?.initials || "—"}</span>}
      {imageUrl && !imageFailed && (
        <img
          src={imageUrl}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          onError={() => setImageFailed(true)}
        />
      )}
    </div>
  );
}
