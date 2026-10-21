import { useState } from "react";
import { toast } from "sonner";
import { Input } from "@/cashier/components/ui/input";
import { MAX_REORDER_LEVEL } from "@/cashier/api/posApi";
import { useSetReorderLevel } from "@/cashier/api/useStock";

/** Parse what was typed. Only a whole number from 0 up is a level; everything else is null. */
export function parseLevel(text) {
  const t = String(text ?? "").trim();
  if (!/^\d{1,7}$/.test(t)) return null;
  const n = Number(t);
  return n <= MAX_REORDER_LEVEL ? n : null;
}

/** Why the server said no, in words the cashier can act on. */
export function levelErrorMessage(error) {
  if (error?.status === 403) return "هذا التعديل للمدير أو المالك فقط";
  if (error?.status === 404) return "هذا الصنف لم يعد موجودًا";
  return "تعذّر حفظ حد الطلب، حاول مرة أخرى";
}

// خلية تعديل حد إعادة الطلب: تحفظ عند الخروج من الحقل أو بالضغط على Enter، ولا ترسل شيئًا إن لم تتغير القيمة.
export default function ReorderLevelCell({ variantId, value }) {
  const [text, setText] = useState(String(value));
  const [bad, setBad] = useState(false);
  const save = useSetReorderLevel();

  function commit() {
    const level = parseLevel(text);
    if (level === null) {
      setBad(true);
      return;
    }
    setBad(false);
    if (level === value) return;
    save.mutate(
      { variantId, level },
      {
        onSuccess: () => toast.success("تم حفظ حد الطلب"),
        onError: (error) => {
          setText(String(value)); // show the level that is really stored
          toast.error(levelErrorMessage(error));
        },
      },
    );
  }

  return (
    <Input
      inputMode="numeric"
      dir="ltr"
      value={text}
      disabled={save.isPending}
      aria-invalid={bad}
      aria-label="حد إعادة الطلب"
      onChange={(e) => {
        setText(e.target.value);
        setBad(false);
      }}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      className={`num h-8 w-20 text-center text-xs ${bad ? "border-red-500" : ""}`}
    />
  );
}
