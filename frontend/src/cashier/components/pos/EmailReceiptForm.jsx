import { useState } from "react";
import { Mail } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { posApi } from "@/cashier/api/posApi";
import { submitReceiptEmail } from "@/cashier/api/receiptEmail";

// إرسال نسخة من الإيصال لإيميل العميل. السيرفر هو اللي يبعت، هنا بس بنطلب.
export default function EmailReceiptForm({ receiptId, initialEmail = "" }) {
  const [email, setEmail] = useState(initialEmail);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const send = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setResult(await submitReceiptEmail(posApi.emailReceipt, receiptId, email));
    setBusy(false);
  };

  return (
    <form onSubmit={send} className="flex flex-col gap-1" aria-label="إرسال الإيصال بالإيميل">
      <div className="flex items-center gap-2">
        <Input
          type="email"
          dir="ltr"
          inputMode="email"
          autoComplete="off"
          placeholder="إيميل العميل"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            setResult(null);
          }}
          className="h-9 flex-1 text-sm"
          aria-label="إيميل العميل"
        />
        <Button type="submit" variant="outline" className="h-9 gap-2" disabled={busy || !email.trim() || !receiptId}>
          <Mail className="h-4 w-4" />
          {busy ? "جاري الإرسال" : "إرسال"}
        </Button>
      </div>
      {result ? (
        <p role="status" className={`text-xs ${result.ok ? "text-emerald-600" : "text-destructive"}`}>
          {result.message}
        </p>
      ) : null}
    </form>
  );
}
