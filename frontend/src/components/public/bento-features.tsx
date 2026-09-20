"use client";

/** شبكة Bento لقسم المميزات — نمط Linear/Vercel: بطاقات بأحجام متفاوتة */
export function BentoFeatures({ items }: { items: [string, string][] }) {
  return (
    <div className="fh-bento">
      {items.map(([title, desc], i) => (
        <div key={title} className={`fh-bento-card${i < 2 ? " is-wide" : ""}`}>
          <span className="fh-bento-ico" aria-hidden="true">◆</span>
          <b>{title}</b>
          <p>{desc}</p>
        </div>
      ))}
    </div>
  );
}
