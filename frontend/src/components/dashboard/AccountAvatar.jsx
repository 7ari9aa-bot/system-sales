import React, { useEffect, useState } from "react";
import { avatarColor, initialsOf } from "@/lib/accountAvatar";
import { cn } from "@/lib/utils";

const SIZES = { sm: "h-8 w-8 text-[12px]", md: "h-9 w-9 text-[12.5px]", lg: "h-14 w-14 text-[18px]" };

/** The account's own picture when it has one; otherwise its letters on a colour
 * that stays put for the same account. A broken image URL falls back to the
 * letters instead of leaving an empty circle. */
export default function AccountAvatar({ user, size = "sm", className }) {
  const [imageFailed, setImageFailed] = useState(false);
  const imageUrl = user?.avatar_url || "";

  useEffect(() => {
    setImageFailed(false);
  }, [imageUrl]);

  return (
    <div
      aria-hidden="true"
      className={cn(
        "relative grid shrink-0 place-items-center overflow-hidden rounded-full font-semibold text-white shadow-xs",
        SIZES[size] ?? SIZES.sm,
        className,
      )}
      style={{ background: avatarColor(user?.id || user?.email || "") }}
    >
      <span className={cn(imageUrl && !imageFailed && "invisible")}>{initialsOf(user)}</span>
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
