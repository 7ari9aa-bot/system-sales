"use client";

import { useEffect, useState } from "react";

/** عنوان متحرك — يبدّل الكلمة الأخيرة كل 2.6 ثانية (نمط Linear الحركي) */
export function KineticHeadline({ base, words }: { base: string; words: string[] }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!words || words.length < 2) return;
    const len = words.length;
    const id = setInterval(() => setI((a) => (a + 1) % len), 2600);
    return () => clearInterval(id);
  }, [words]);
  if (!words || words.length < 2) return <h1>{base}</h1>;
  return (
    <h1>
      {base}{" "}
      <span key={i} className="fh-kinetic">{words[i]}</span>
    </h1>
  );
}
