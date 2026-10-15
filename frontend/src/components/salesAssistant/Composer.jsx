/** Bottom composer — Enter sends, Shift+Enter newline, auto-grows to ~6 rows,
 *  disabled while a turn runs. The DRAFT lives in the page (keyed by thread
 *  id) so switching threads never loses what the merchant typed. */

import React from "react";
import { ArrowUp } from "lucide-react";
import { useT } from "@/lib/i18n";

export default function Composer({ value, onChange, onSend, disabled }) {
  const t = useT();
  const ref = React.useRef(null);

  // auto-grow: the textarea tracks its content height up to a ceiling
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 144)}px`;
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    ref.current?.focus();
  };

  return (
    <div className="border-t border-border bg-card/70 backdrop-blur p-3">
      <div
        className={`flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm transition-colors ${
          disabled ? "border-border opacity-70" : "border-border focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/20"
        }`}
      >
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
          className="max-h-36 min-h-[36px] w-full resize-none bg-transparent px-2 py-1.5 text-[13.5px] leading-6 outline-none placeholder:text-muted-foreground"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !value.trim()}
          title={t("salesAssistant.send")}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm hover:opacity-90 active:scale-95 transition-all disabled:opacity-35 disabled:shadow-none"
        >
          <ArrowUp className="h-4.5 w-4.5" />
        </button>
      </div>
      <p className="mt-1.5 px-1 text-[10.5px] text-muted-foreground/70">
        {t("salesAssistant.composerHint")}
      </p>
    </div>
  );
}
