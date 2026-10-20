import { cn } from "@/cashier/lib/utils";

// شارات سجل المبيعات: حبّة ملوّنة بحلقة داخلية بنفس مفردات التصميم الجديد.
const TONES = {
  success: "bg-[#ecfdf5] text-[#047857] shadow-[inset_0_0_0_1px_#a7f3d0]",
  warning: "bg-[#fffbeb] text-[#b45309] shadow-[inset_0_0_0_1px_#fde68a]",
  neutral: "bg-[#fffbeb] text-[#b45309] shadow-[inset_0_0_0_1px_#fde68a]",
  info: "bg-[#f0f9ff] text-[#0369a1] shadow-[inset_0_0_0_1px_#bae6fd]",
  violet: "bg-[#f5f3ff] text-[#6d28d9] shadow-[inset_0_0_0_1px_#ddd6fe]",
  danger: "bg-[#fef2f2] text-[#b91c1c] shadow-[inset_0_0_0_1px_#fecaca]",
  primary: "bg-[#fff7ed] text-[#c2410c] shadow-[inset_0_0_0_1px_#fed7aa]",
};

export default function LogBadge({ label, tone = "neutral", className }) {
  return (
    <span
      className={cn(
        "inline-block whitespace-nowrap rounded-full px-[10px] py-[3px] text-[11px] font-bold",
        TONES[tone] ?? TONES.neutral,
        className,
      )}
    >
      {label}
    </span>
  );
}