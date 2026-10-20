import { cn } from "@/cashier/lib/utils";

// سطر إحصاءات الشاشة: أربع خلايا أرقام متصلة أسفل الجدول.
export default function LedgerStats({ stats, className }) {
  return (
    <div className={cn("grid grid-cols-2 border border-[#DED8CD] border-t-2 border-t-[#33322E] bg-white lg:grid-cols-4", className)}>
      {stats.map((stat, index) => (
        <div
          key={stat.label}
          className={cn(
            "px-4 py-3",
            index % 2 === 1 && "border-s border-[#DED8CD]",
            index === 2 && "lg:border-s lg:border-[#DED8CD]",
          )}
        >
          <span className="block text-[11px] text-[#7A766C]">{stat.label}</span>
          <b className={cn("num mt-0.5 mb-0.5 block text-[15px] font-semibold", stat.accent && "text-[#E8761A]")}>
            {stat.value}
          </b>
          <i className="block text-[10px] not-italic text-[#7A766C]">{stat.hint}</i>
        </div>
      ))}
    </div>
  );
}