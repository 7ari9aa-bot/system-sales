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
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    ref.current?.focus();
  };

  return (
    <div data-testid="assistant-composer" className="mx-auto w-full max-w-3xl shrink-0 bg-background px-4 pb-3 pt-2">
      <div
        data-testid="assistant-composer-field"
        className={`flex items-end gap-2 rounded-[28px] border bg-card py-2 ps-5 pe-2 shadow-sm transition-colors ${
          disabled ? "border-border opacity-70" : "border-border focus-within:border-foreground/25"
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
          className="max-h-40 min-h-[40px] w-full resize-none bg-transparent py-2 text-[14.5px] leading-6 outline-none placeholder:text-muted-foreground"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !value.trim()}
          title={t("salesAssistant.send")}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground shadow-sm hover:opacity-90 active:scale-95 transition-all disabled:opacity-35 disabled:shadow-none"
        >
          <ArrowUp className="h-4.5 w-4.5" />
        </button>
      </div>
      <p className="mt-2 px-1 text-center text-[11px] text-muted-foreground/70">
        {t("salesAssistant.composerHint")}
      </p>
    </div>
  );
}
