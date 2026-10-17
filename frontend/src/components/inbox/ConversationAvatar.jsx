import React, { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export default function ConversationAvatar({ conversation, className, initialsClassName }) {
  const [imageFailed, setImageFailed] = useState(false);
  const imageUrl = conversation?.avatarUrl || conversation?.profileImageUrl || conversation?.avatar || "";

  useEffect(() => {
    setImageFailed(false);
  }, [imageUrl]);

  return (
    <div
      aria-hidden="true"
      className={cn("relative grid shrink-0 place-items-center overflow-hidden rounded-full font-semibold", className)}
      style={{ background: conversation?.color || "#d9e2e9", color: "#fff" }}
    >
      <span className={initialsClassName}>{conversation?.initials || "—"}</span>
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
