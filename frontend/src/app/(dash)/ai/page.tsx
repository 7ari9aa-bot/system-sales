"use client";

import * as React from "react";
import { BookOpen, Plus } from "lucide-react";
import {
  useAddKnowledge,
  useAgents,
  useKnowledge,
  useKnowledgeSearch,
  useUsageSummary,
  type KnowledgeItem,
} from "@/lib/queries";
import { useCreateDialog } from "@/lib/use-create-dialog";
import { AgentPromptEditor } from "@/components/ai/agent-prompt-editor";
import { t } from "@/lib/t";
import { formatDate, formatNumber } from "@/lib/utils";
import { fixedDecimal } from "@/components/orders/money";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, PageHeader } from "@/components/ui/states";
import { QueryErrorState } from "@/components/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="text-[26px] font-bold leading-tight" dir="ltr">
          {value}
        </div>
        <div className="mt-0.5 text-[13px] text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  );
}

export default function AIPage() {
  const [addOpen, setAddOpen] = useCreateDialog();
  const [title, setTitle] = React.useState("");
  const [content, setContent] = React.useState("");
  const [query, setQuery] = React.useState("");

  const knowledgeQuery = useKnowledge();
  const agentsQuery = useAgents();
  const usageQuery = useUsageSummary();
  const addKnowledge = useAddKnowledge();
  const search = useKnowledgeSearch();

  const items = knowledgeQuery.data ?? [];
  const agents = agentsQuery.data ?? [];
  const usage = usageQuery.data?.summary ?? [];
  const usageTotals = usageQuery.data?.totals;

  // §55: the period totals come from the ROUTE, already summed in Decimal.
  // Adding them here would be the business aggregation the spec forbids the
  // browser, and `cost` is money in `Numeric(18,8)` — so the total renders at 4
  // places from the string (`formatMoney` would flatten a real spend to 0.00).
  const totalCost = usageTotals ? fixedDecimal(usageTotals.cost, 4) : null;
  const totalTokens = usageTotals ? usageTotals.tokens_in + usageTotals.tokens_out : 0;

  function submitKnowledge() {
    if (!title.trim() || !content.trim()) return;
    addKnowledge.mutate(
      { title, content },
      {
        onSuccess: () => {
          setAddOpen(false);
          setTitle("");
          setContent("");
        },
      },
    );
  }

  function doSearch() {
    const q = query.trim();
    if (q) search.mutate(q);
  }

  return (
    <div>
      <PageHeader
        title={t.agentSettings}
        description={t.agentSettingsHint}
        actions={
          <Button onClick={() => setAddOpen(true)} data-testid="open-knowledge-form">
            <Plus aria-hidden="true" />
            {t.addKnowledge}
          </Button>
        }
      />

      {knowledgeQuery.isError || agentsQuery.isError || usageQuery.isError ? (
        <QueryErrorState queries={[knowledgeQuery, agentsQuery, usageQuery]} />
      ) : knowledgeQuery.isLoading || agentsQuery.isLoading || usageQuery.isLoading ? (
        <div className="space-y-4" aria-busy="true" aria-label={t.loading}>
          <div className="grid gap-4 sm:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-64" />
        </div>
      ) : (
        <>
          <div className="mb-4 grid gap-4 sm:grid-cols-3">
            <StatCard label={t.totalTokens} value={formatNumber(totalTokens)} />
            <StatCard label={`${t.usageCost} ($)`} value={totalCost ?? "—"} />
            <StatCard label={t.agents} value={agents.length} />
          </div>

          <Tabs defaultValue="agent">
            <TabsList>
              <TabsTrigger value="agent">{t.agentSettings}</TabsTrigger>
              <TabsTrigger value="knowledge">{t.aiTabKnowledge}</TabsTrigger>
              <TabsTrigger value="search">{t.aiTabSearch}</TabsTrigger>
              <TabsTrigger value="usage">{t.aiTabUsage}</TabsTrigger>
            </TabsList>

            <TabsContent value="agent">
              <AgentPromptEditor agents={agents} />
            </TabsContent>

            {/* knowledge list */}
            <TabsContent value="knowledge">
              <Card>
                <CardContent className="p-0 pb-2">
                  {items.length === 0 ? (
                    <EmptyState
                      icon={<BookOpen aria-hidden="true" />}
                      title={t.knowledgeEmpty}
                      description={t.knowledgeEmptyHint}
                      action={
                        <Button size="sm" onClick={() => setAddOpen(true)}>
                          {t.addKnowledge}
                        </Button>
                      }
                    />
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t.title}</TableHead>
                          <TableHead>{t.status}</TableHead>
                          <TableHead>{t.date}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {items.map((k: KnowledgeItem) => (
                          <TableRow key={k.id}>
                            <TableCell className="font-semibold">{k.title}</TableCell>
                            <TableCell>
                              <Badge variant={k.status === "indexed" ? "success" : "warning"}>
                                {k.status === "indexed" ? t.indexed : t.aiProcessing}
                              </Badge>
                            </TableCell>
                            <TableCell dir="ltr" className="text-xs text-muted-foreground">
                              {formatDate(k.created_at)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* semantic search */}
            <TabsContent value="search">
              <Card>
                <CardHeader>
                  <CardTitle>{t.searchKnowledge}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-2">
                    <Input
                      placeholder={t.askPlaceholder}
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && doSearch()}
                      data-testid="knowledge-search-input"
                      className="flex-1"
                    />
                    <Button onClick={doSearch} disabled={!query.trim() || search.isPending}>
                      {t.ask}
                    </Button>
                  </div>
                  {search.data && (
                    <ul className="mt-4 space-y-2">
                      {search.data.length === 0 && (
                        <li className="text-[13px] text-muted-foreground">{t.noHits}</li>
                      )}
                      {search.data.map((h) => (
                        <li
                          key={h.id}
                          className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-sm"
                        >
                          <span className="font-semibold">{h.title}</span>
                          <span className="text-xs text-muted-foreground" dir="ltr">
                            ({t.distance} {h.distance.toFixed(3)})
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* usage rows */}
            <TabsContent value="usage">
              <Card>
                <CardHeader>
                  <CardTitle>{t.usageCost}</CardTitle>
                </CardHeader>
                <CardContent className="p-0 pb-2">
                  {usage.length === 0 ? (
                    <EmptyState title="لا يوجد استهلاك بعد" />
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t.date}</TableHead>
                          <TableHead dir="ltr">Tokens in</TableHead>
                          <TableHead dir="ltr">Tokens out</TableHead>
                          <TableHead>التكلفة ($)</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {usage.map((r) => (
                          <TableRow key={r.date}>
                            <TableCell dir="ltr" className="text-xs text-muted-foreground">
                              {r.date}
                            </TableCell>
                            <TableCell dir="ltr">{formatNumber(r.tokens_in)}</TableCell>
                            <TableCell dir="ltr">{formatNumber(r.tokens_out)}</TableCell>
                            {/* AI cost is `Numeric(18,8)` — sub-cent money on
                              * purpose — so it renders at 4 places from the
                              * string itself. `formatMoney` would flatten a real
                              * call to 0.00. */}
                            <TableCell dir="ltr">{fixedDecimal(r.cost, 4) ?? "—"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </>
      )}

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.addKnowledge}</DialogTitle>
            <DialogDescription>علّم الوكيل إجابات الأسئلة المتكررة.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="k-title">{t.title}</Label>
              <Input id="k-title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="k-content">{t.content}</Label>
              <Textarea id="k-content" rows={4} value={content} onChange={(e) => setContent(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={submitKnowledge} disabled={addKnowledge.isPending || !title.trim() || !content.trim()}>
              {t.save}
            </Button>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>
              {t.cancel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
