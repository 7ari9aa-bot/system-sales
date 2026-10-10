/** Bottom composer — Enter sends, Shift+Enter newline, disabled while a turn
 *  runs. The DRAFT lives in the page (keyed by thread id) so switching threads
 *  never loses what the merchant typed. */

import React from "react";
import { SendHorizontal } from "lucide-react";
import { useT } from "@/lib/i18n";

export default function Composer({ value, onChange, onSend, disabled }) {
  const t = useT();
  const ref = React.useRef(null);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    ref.current?.focus();
  };

  return (
    <div className="border-t border-border bg-card/60 p-3">
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          rows={1}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={t("salesAssistant.composerPlaceholder")}
          className="max-h-40 min-h-[42px] w-full resize-y rounded-xl border border-border bg-card px-3 py-2.5 text-[13.5px] leading-6 outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary/40 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="inline-flex h-[42px] shrink-0 items-center justify-center gap-1.5 rounded-xl bg-primary px-3.5 text-[13px] font-medium text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-40"
        >
          <SendHorizontal className="h-4 w-4" />
          {t("salesAssistant.send")}
        </button>
      </div>
    </div>
  );
}
