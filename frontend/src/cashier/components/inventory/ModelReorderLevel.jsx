import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { useSetProductReorderLevel } from "@/cashier/api/useStock";
import { levelErrorMessage, parseLevel } from "@/cashier/components/inventory/ReorderLevelCell";

/**
 * حد طلب واحد للموديل كله.
 *
 * A clothing shop restocks a size run, not a size: typing a threshold into eight sizes is how a
 * model ends up with no low-stock alert at all. One number here, then every size of the model
 * carries it. Sizes that are archived are left alone by the server.
 */
export default function ModelReorderLevel({ productId, sizes = 0 }) {
  const [text, setText] = useState("");
  const [bad, setBad] = useState(false);
  const save = useSetProductReorderLevel();

  function apply() {
    const level = parseLevel(text);
    if (level === null) {
      setBad(true);
      return;
    }
    setBad(false);
    save.mutate(
      { productId, level },
      {
        onSuccess: (r) => {
          const count = Number(r?.variants) || sizes;
          toast.success(`تم ضبط حد الطلب ${level} على ${count} مقاس`);
          setText("");
        },
        onError: (error) => toast.error(levelErrorMessage(error)),
      },
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[#E3DED4] bg-white px-3 py-2">
      <span className="text-[11px] font-semibold text-[#3B3A36]">حد الطلب لكل المقاسات</span>
      <Input
        inputMode="numeric"
        dir="ltr"
        value={text}
        disabled={save.isPending}
        aria-invalid={bad}
        aria-label="حد الطلب لكل مقاسات الموديل"
        placeholder="0"
        onChange={(e) => {
          setText(e.target.value);
          setBad(false);
        }}
        onKeyDown={(e) => e.key === "Enter" && apply()}
        className={`num h-8 w-20 text-center text-xs ${bad ? "border-red-500" : ""}`}
      />
      <Button
        type="button"
        size="sm"
        className="h-8"
        disabled={save.isPending || !String(text).trim()}
        onClick={apply}
      >
        {save.isPending ? "جارٍ الضبط…" : "طبّق على الموديل"}
      </Button>
      <span className="text-[10px] text-[#9A958A]">
        بيُكتب على كل مقاسات الموديل مرة واحدة. 0 = من غير تنبيه.
      </span>
    </div>
  );
}
