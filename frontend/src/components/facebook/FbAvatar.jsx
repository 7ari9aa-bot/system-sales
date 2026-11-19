import React, { useState } from "react";
import { cn } from "@/lib/utils";

export default function FbAvatar({ src, name, size = "h-10 w-10" }) {
  const [failed, setFailed] = useState(false);
  const letter = String(name || "F").trim().slice(0, 1).toUpperCase();
  return src && !failed
    ? <img src={src} alt="" className={cn(size, "shrink-0 rounded-full object-cover")} onError={() => setFailed(true)} />
    : <span className={cn(size, "grid shrink-0 place-items-center rounded-full bg-[#e7f3ff] text-[15px] font-bold text-[#0866ff]")}>{letter}</span>;
}
