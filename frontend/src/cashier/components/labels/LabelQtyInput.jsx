import { cn } from "@/cashier/lib/utils";

// خلية عدد الملصقات لكل متغير: رقم فقط فوق خط شعري يتحول برتقاليًا عند التحرير أو وجود قيمة.
export default function LabelQtyInput({ value, mixed = false, label, onChange }) {
  const filled = Number(value) > 0;

  return (
    <span className="flex flex-col items-center gap-1">
      <input
        type="number"
        min={0}
        max={99}
        inputMode="numeric"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={mixed ? "مختلط" : "0"}
        aria-label={label}
        className={cn(
          "num h-[30px] w-16 rounded-none border-x-0 border-t-0 border-b border-b-[#DED8CD] bg-white text-center text-[13px] font-semibold text-[#33322E] shadow-none transition-[border-color,box-shadow] duration-200 [appearance:textfield] placeholder:font-normal placeholder:text-[#9C978B] hover:border-b-[#E8761A] focus-visible:border-b-2 focus-visible:border-b-[#E8761A] focus-visible:shadow-[0_2px_0_#E8761A] focus-visible:outline-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
          filled && "animate-flash border-b-2 border-b-[#E8761A]",
        )}
      />
      {mixed && <span className="text-[10px] text-[#7A766C]">أعداد مختلفة لكل متغير</span>}
    </span>
  );
}