/** The conversation scroll — user turns right, assistant turns left (RTL-aware
 *  via the document direction). Assistant turns render validated blocks; a
 *  generating turn shows the honest "thinking" state (no fake streaming), and
 *  a failed turn shows the safe error code with a retry button. */

import React from "react";
import Markdown from "react-markdown";
import { Check, Copy, RotateCcw } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import BlockRenderer from "@/components/salesAssistant/BlockRenderer";
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

export default function MessageList({ messages, pending, onRetry }) {
  const t = useT();
  const items = [...(messages ?? [])];
  if (pending) {
    items.push({ id: "pending", role: "assistant", status: "generating", content: "" });
  }
  return (
    <div className="space-y-4">
      {items.map((m) => {
        const isUser = m.role === "user";
        const isGenerating = m.status === "generating" || m.status === "pending";
        const isFailed = m.status === "failed";
        const textBody =
          m.structured_content?.find?.((b) => b?.type === "text")?.body ?? m.content ?? "";
        return (
          <div key={m.id} className={isUser ? "flex justify-end" : "flex justify-start"}>
            <div
              className={
                isUser
                  ? "max-w-[85%] rounded-2xl rounded-br-md bg-primary text-primary-foreground px-3.5 py-2.5"
                  : "max-w-[92%] w-fit min-w-0 rounded-2xl rounded-bl-md bg-card border border-border px-3.5 py-3"
              }
            >
              {isUser ? (
                <p className="text-[13.5px] leading-6 whitespace-pre-wrap break-words">{m.content}</p>
              ) : isGenerating ? (
                <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
                  <span className="inline-flex gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-bounce [animation-delay:-0.2s]" />
                    <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-bounce [animation-delay:-0.1s]" />
                    <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-bounce" />
                  </span>
                  {t("salesAssistant.thinking")}
                </div>
              ) : isFailed ? (
                <div className="space-y-2">
                  <Badge tone="destructive">{m.error_code || "run_failed"}</Badge>
                  <div>
                    <button
                      type="button"
                      onClick={() => onRetry?.(m)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12.5px] hover:bg-surface transition-colors"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      {t("salesAssistant.retry")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-1">
                  <Markdown
                    components={{
                      p: ({ children }) => <p className="text-[13.5px] leading-6">{children}</p>,
                      table: ({ children }) => (
                        <div className="overflow-x-auto">
                          <table className="text-[12.5px]">{children}</table>
                        </div>
                      ),
                    }}
                  >
                    {textBody}
                  </Markdown>
                  <BlockRenderer blocks={m.structured_content} />
                  <div className="pt-0.5">
                    <CopyButton text={textBody} />
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
