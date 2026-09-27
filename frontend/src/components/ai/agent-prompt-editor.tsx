"use client";

import * as React from "react";
import { Sparkles } from "lucide-react";
import {
  useAgentPrompt,
  useUpdateAgentPrompt,
  type Agent,
} from "@/lib/queries";
import { t } from "@/lib/t";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";
import { QueryErrorState } from "@/components/query-error";

/* -------------------------------------------------- agent settings (owner) */

/** Owner directive 2026-09-27: the client sees and edits THEIR OWN agent's
 *  prompt and settings — tenant-scoped by the backend's tenant WHERE, so one
 *  tenant's edit never reaches another tenant's agent. If-Match (the row
 *  version) rides along: two tabs editing the same agent = one 409, re-read. */
export function AgentPromptEditor({ agents }: { agents: Agent[] }) {
  const [selectedId, setSelectedId] = React.useState<string | null>(agents[0]?.id ?? null);
  const promptQuery = useAgentPrompt(selectedId);
  const detail = promptQuery.data ?? null;
  const [draft, setDraft] = React.useState<string | null>(null);
  const saveMutation = useUpdateAgentPrompt();

  React.useEffect(() => {
    setDraft(null);
  }, [selectedId, detail?.version]);

  if (agents.length === 0) {
    return <EmptyState icon={<Sparkles aria-hidden="true" />} title={t.agentPromptEmpty} />;
  }

  const dirty = detail !== null && draft !== null && draft !== detail.system_prompt;
  const error = saveMutation.error ?? promptQuery.error;

  return (
    <Card>
      <CardHeader className="space-y-1">
        <CardTitle>{t.agentSettings}</CardTitle>
        <p className="text-[13px] text-muted-foreground">{t.agentSettingsHint}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {error ? <QueryErrorState queries={[promptQuery]} /> : null}

        {agents.length > 1 && (
          <div className="space-y-1">
            <Label htmlFor="agent-select">{t.agents}</Label>
            <select
              id="agent-select"
              className="w-full rounded-lg border border-border bg-surface p-2 text-sm"
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {promptQuery.isLoading || !detail ? (
          <Skeleton className="h-40" />
        ) : (
          <>
            <div className="space-y-1">
              <Label htmlFor="agent-prompt">{t.agentPromptLabel}</Label>
              <Textarea
                id="agent-prompt"
                dir="auto"
                rows={10}
                value={draft ?? detail.system_prompt ?? ""}
                onChange={(e) => setDraft(e.target.value)}
                data-testid="agent-prompt-input"
              />
            </div>
            <div className="flex items-center gap-3">
              <Button
                disabled={!dirty || saveMutation.isPending}
                data-testid="agent-prompt-save"
                onClick={() => {
                  if (!dirty || draft === null) return;
                  saveMutation.mutate({
                    agentId: detail.id,
                    system_prompt: draft,
                    version: detail.version,
                  });
                }}
              >
                {saveMutation.isPending ? "..." : t.save}
              </Button>
              {saveMutation.isSuccess && !dirty ? (
                <span className="text-sm text-success" role="status" data-testid="agent-prompt-saved">
                  {t.agentPromptSaved}
                </span>
              ) : null}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
