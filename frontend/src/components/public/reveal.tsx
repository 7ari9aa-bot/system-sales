"use client";

/** Scroll-reveal: بيضيف .fh-in لما العنصر يدخل الشاشة (مرة واحدة).
 *  Reduced-motion بيتعامل معاه CSS من غير JS. */

import { useEffect, useRef } from "react";

export function Reveal({
  children,
  className = "",
  stagger = false,
  as: Tag = "div",
  ...rest
}: {
  children: React.ReactNode;
  className?: string;
  stagger?: boolean;
  as?: "div" | "section" | "header" | "p";
} & Omit<React.HTMLAttributes<HTMLElement>, "children" | "className">) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // الافتراضي ظاهر — الإخفاء فقط للعناصر تحت الفولد ومع توفر JS
    if (
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      el.getBoundingClientRect().top <= window.innerHeight
    ) {
      el.classList.add("fh-in");
      return;
    }
    el.classList.add("fh-pre");
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.classList.add("fh-in");
          io.disconnect();
        }
      },
      { threshold: 0.1 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <Tag
      ref={ref as React.RefObject<never>}
      className={`fh-reveal${stagger ? " fh-reveal-stagger" : ""} ${className}`.trim()}
      {...rest}
    >
      {children}
    </Tag>
  );
}
