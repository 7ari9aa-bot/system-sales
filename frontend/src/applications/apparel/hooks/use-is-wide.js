import { useEffect, useRef, useState } from "react";

/**
 * هل الحاوية نفسها أعرض من الحد؟ (نقطة تحوّل جدول التركيبات 860px)
 *
 * الجدول كان بيبني نسختين كاملتين من كل صف (كروت موبايل + جدول ديسكتوب) والـCSS بيخفي واحدة،
 * فمنتج بـ500 تركيبة كان بيرسم 1,000 صف في الـDOM. بالهوك ده بتترسم نسخة واحدة بس،
 * والقياس على عرض الكارت نفسه مش عرض الشاشة (الكارت أضيق بكتير من الشاشة).
 */
export function useContainerWide(minWidth = 860) {
  const ref = useRef(null);
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const measure = (width) => setWide(width >= minWidth);
    measure(el.getBoundingClientRect().width);
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) measure(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [minWidth]);
  return [ref, wide];
}
