// رسم أعمدة الباركود من أرقامه (بديل بصري مطبوع).
export default function BarcodeBars({ code, className }) {
  const bars = String(code ?? "")
    .split("")
    .map((d, i) => ({ width: (Number(d) % 3) + 1, tall: i % 2 === 0, key: `${d}-${i}` }));

  return (
    <div className={className ?? "flex h-8 items-end gap-[1px]"}>
      {bars.map((b) => (
        <span key={b.key} className="bg-black" style={{ width: b.width, height: b.tall ? "100%" : "82%" }} />
      ))}
    </div>
  );
}