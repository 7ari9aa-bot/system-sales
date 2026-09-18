"use client";

/** طبقة التوهّج الثابتة خلف الصفحة — عناصر ديكورية بحركة بطيئة جدًا. */

export function AmbientGlow() {
  return (
    <div className="fh-ambient" aria-hidden="true">
      <div className="fh-blob fh-blob-a" />
      <div className="fh-blob fh-blob-b" />
    </div>
  );
}
