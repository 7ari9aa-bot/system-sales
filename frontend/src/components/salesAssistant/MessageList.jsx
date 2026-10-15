/** The conversation scroll — user turns right, assistant turns left (RTL-aware
 *  via the document direction). Assistant turns carry the FIHRIST avatar, a
 *  timestamp, validated render blocks, and the honest thinking state (no fake
 *  streaming). Failed turns keep their retry button. */

import React from "react";
import Markdown from "react-markdown";
import { Check, Copy, RotateCcw } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import Logo from "@/components/dashboard/Logo";
import BlockRenderer from "@/components/salesAssistant/BlockRenderer";
import { useFormatters } from "@/lib/dates";
import { useT } from "@/lib/i18n";

function CopyButton({ text }) {
  const t = useT();
  const [copied, setCopied] = React.useState(false);
  return (
    <button
      type="button"
      title={t("salesAssistant.copy")}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard unavailable — the button stays silent */
        }
      }}
      className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11.5px] text-muted-foreground hover:bg-surface hover:text-foreground transition-colors"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t("salesAssistant.copied") : t("salesAssistant.copy")}
    </button>
  );
}

function Thinking() {
  return (
    <div className="flex items-center gap-2.5 py-1">
      <span className="inline-flex gap-1">
        <span className="h-1.5 w-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:-0.25s]" />
        <span className="h-1.5 w-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 rounded-full bg-primary/70 animate-bounce" />
      </span>
      <span className="text-[12.5px] text-muted-foreground">…</span>
    </div>
  );
}

export default function MessageList({ messages, pending, onRetry }) {
  const t = useT();
  const { ago } = useFormatters();
  const items = [...(messages ?? [])];
  if (pending) {
    items.push({ id: "pending", role: "assistant", status: "generating", content: "" });
  }
  return (
    <div className="space-y-5">
      {items.map((m) => {
        const isUser = m.role === "user";
        const isGenerating = m.status === "generating" || m.status === "pending";
        const isFailed = m.status === "failed";
        const textBody =
          m.structured_content?.find?.((b) => b?.type === "text")?.body ?? m.content ?? "";
        return (
          <div key={m.id} className={`flex gap-2.5 animate-fade-in ${isUser ? "justify-end" : "justify-start"}`}>
            {!isUser && (
              <span className="mt-0.5 shrink-0">
                <Logo size={28} />
              </span>
            )}
            <div className={`min-w-0 max-w-[88%] ${isUser ? "flex flex-col items-end" : ""}`}>
              <div
                className={
                  isUser
                    ? "rounded-2xl rounded-br-md bg-primary text-primary-foreground px-4 py-2.5 shadow-sm"
                    : "w-fit min-w-0 rounded-2xl rounded-bl-md bg-card border border-border px-4 py-3 shadow-sm"
                }
              >
                {isUser ? (
                  <p className="text-[13.5px] leading-6 whitespace-pre-wrap break-words">{m.content}</p>
                ) : isGenerating ? (
                  <Thinking />
                ) : isFailed ? (
                  <div className="space-y-2.5">
                    <Badge tone="destructive">{m.error_code || "run_failed"}</Badge>
                    <div>
                      <button
                        type="button"
                        onClick={() => onRetry?.(m)}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-1.5 text-[12.5px] font-medium hover:bg-surface transition-colors"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        {t("salesAssistant.retry")}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Markdown
                      components={{
                        p: ({ children }) => <p className="text-[13.5px] leading-7">{children}</p>,
                        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                        table: ({ children }) => (
                          <div className="overflow-x-auto rounded-xl border border-border">
                            <table className="w-full text-[12.5px] [&_th]:bg-surface [&_th]:px-2.5 [&_th]:py-1.5 [&_th]:text-start [&_td]:px-2.5 [&_td]:py-1.5 [&_td]:border-t [&_td]:border-border">
                              {children}
                            </table>
                          </div>
                        ),
                      }}
                    >
                      {textBody}
                    </Markdown>
                    <BlockRenderer blocks={m.structured_content} />
                  </div>
                )}
              </div>
              {!isGenerating && (
                <div className={`mt-1 flex items-center gap-2 px-1 ${isUser ? "justify-end" : ""}`}>
                  <span className="text-[10.5px] text-muted-foreground/70">{ago(m.created_at)}</span>
                  {!isUser && !isFailed && textBody ? <CopyButton text={textBody} /> : null}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
