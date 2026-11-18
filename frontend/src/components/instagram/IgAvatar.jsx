import React, { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

/** Instagram's default picture: a light grey disc with a white person. Never initials. */
export function IgDefaultAvatar({ className }) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden="true">
      <circle cx="50" cy="50" r="50" fill="#dbdfe4" />
      <circle cx="50" cy="40" r="17" fill="#fff" />
      <path d="M17 86c5-15 18-23 33-23s28 8 33 23a50 50 0 0 1-66 0Z" fill="#fff" />
    </svg>
  );
}

/** A round profile picture, optionally inside the gradient story ring. */
export default function IgAvatar({ src, size = 44, ring = false, className, alt = "" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);
  const inner = (
    <span className="relative block overflow-hidden rounded-full bg-white" style={{ width: size, height: size }}>
      {src && !failed
        ? <img src={src} alt={alt} className="h-full w-full object-cover" onError={() => setFailed(true)} />
        : <IgDefaultAvatar className="h-full w-full" />}
    </span>
  );
  if (!ring) return <span className={cn("inline-block shrink-0 rounded-full", className)}>{inner}</span>;
  return (
    <span className={cn("inline-block shrink-0 rounded-full p-[2px]", className)} style={{ background: "conic-gradient(from 45deg, #feda75, #fa7e1e, #d62976, #962fbf, #4f5bd5, #feda75)" }}>
      <span className="block rounded-full bg-white p-[2px]">{inner}</span>
    </span>
  );
}
