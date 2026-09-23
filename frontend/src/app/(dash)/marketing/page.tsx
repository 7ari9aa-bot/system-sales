"use client";

import * as React from "react";
import { Megaphone, Plus } from "lucide-react";
import { useCampaigns, useCreateCampaign, useMarketingSummary, useTenantCurrency, type Campaign, type CampaignBudgetRoas } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatMoney, scaleOf } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, PageHeader } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";

export default function MarketingPage() {
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [provider, setProvider] = React.useState("facebook");
  const [budget, setBudget] = React.useState("");

  const campaignsQuery = useCampaigns();
  const summaryQuery = useMarketingSummary();
  const createCampaign = useCreateCampaign();
  const currencyQuery = useTenantCurrency();
  // §47: `orders_summary` ships the tenant's ISO code with its money, so the
  // collected figures are labelled by the response itself. Campaign budgets and
  // attributed credit are the same tenant currency; the tenant read is the
  // fallback while the summary is still loading.
  const tenantCurrency = currencyQuery.data?.currency ?? null;
  const money = summaryQuery.data?.orders_summary;
  const currency = money?.currency || tenantCurrency;

  const campaigns = campaignsQuery.data ?? [];
  const summary = summaryQuery.data;

  React.useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("new") === "1") {
      setOpen(true);
    }
  }, []);

  function submit() {
    if (!name.trim()) return;
    createCampaign.mutate(
      { name, provider, budget: budget ? Number(budget) : null },
      {
        onSuccess: () => {
          setOpen(false);
          setName("");
          setBudget("");
        },
      },
    );
  }

  return (
    <div>
      <PageHeader
        title={t.marketing}
        description="حملاتك وأداء كل منصة"
        actions={
          <Button onClick={() => setOpen(true)} data-testid="open-campaign-form">
            <Plus aria-hidden="true" />
            {t.newCampaign}
          </Button>
        }
      />

      {campaignsQuery.isError || summaryQuery.isError ? (
        <EmptyState
          title={(campaignsQuery.error as Error | undefined ?? summaryQuery.error as Error).message}
        />
      ) : campaignsQuery.isLoading || summaryQuery.isLoading ? (
        <div className="space-y-4" aria-busy="true" aria-label={t.loading}>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-72" />
        </div>
      ) : (
        <>
          {money && (
            // ADR-053: collected money is gross, refunded and net — three named
            // figures, never one card called "الإيرادات". Attribution lives in
            // the campaign table below and is labelled as credit.
            <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Card data-testid="mk-gross-revenue">
                <CardContent className="p-5">
                  <div className="text-[26px] font-bold leading-tight" dir="ltr">
                    {formatMoney(money.gross_revenue, currency)}
                  </div>
                  <div className="mt-0.5 text-[13px] text-muted-foreground">
                    {t.grossRevenue30}
                  </div>
                </CardContent>
              </Card>
              <Card data-testid="mk-net-revenue">
                <CardContent className="p-5">
                  <div className="text-[26px] font-bold leading-tight" dir="ltr">
                    {formatMoney(money.net_revenue, currency)}
                  </div>
                  <div className="mt-0.5 text-[13px] text-muted-foreground">{t.netRevenue30}</div>
                  {scaleOf(money.refund_excess) > 0 && (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      {t.refundExcessNote(formatMoney(money.refund_excess, currency))}
                    </div>
                  )}
                </CardContent>
              </Card>
              <Card data-testid="mk-refunded">
                <CardContent className="p-5">
                  <div className="text-[26px] font-bold leading-tight" dir="ltr">
                    {formatMoney(money.refunded_amount, currency)}
                  </div>
                  <div className="mt-0.5 text-[13px] text-muted-foreground">{t.refunded30}</div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-5">
                  <div className="text-[26px] font-bold leading-tight" dir="ltr">
                    {money.orders_count}
                  </div>
                  <div className="mt-0.5 text-[13px] text-muted-foreground">{t.orders30}</div>
                </CardContent>
              </Card>
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>{t.campaigns}</CardTitle>
              </CardHeader>
              <CardContent className="p-0 pb-2">
                {campaigns.length === 0 ? (
                  <EmptyState
                    icon={<Megaphone aria-hidden="true" />}
                    title={t.noCampaigns}
                    description={t.noCampaignsHint}
                    action={
                      <Button size="sm" onClick={() => setOpen(true)}>
                        <Plus aria-hidden="true" />
                        {t.newCampaign}
                      </Button>
                    }
                  />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t.name}</TableHead>
                        <TableHead>{t.provider}</TableHead>
                        <TableHead>{t.budget}</TableHead>
                        <TableHead>{t.status}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {campaigns.map((c: Campaign) => (
                        <TableRow key={c.id}>
                          <TableCell className="font-semibold">{c.name}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{c.provider}</Badge>
                          </TableCell>
                          <TableCell dir="ltr">{formatMoney(c.budget, currency)}</TableCell>
                          <TableCell>
                            <Badge variant={c.status === "active" ? "success" : "default"}>{c.status}</Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <Card data-testid="campaign-return">
              <CardHeader>
                {/* §167: the ratio this table can produce today is return on the
                    PLANNED budget. Calling the card "ROAS" would promise a
                    spend-based number the backend has no feed for. */}
                <CardTitle>{t.campaignReturn}</CardTitle>
              </CardHeader>
              <CardContent className="p-0 pb-2">
                {(summary?.campaign_budget_roas ?? []).length === 0 ? (
                  <EmptyState title={t.noRoasData} />
                ) : (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t.campaigns}</TableHead>
                          <TableHead>{t.plannedBudgetCol}</TableHead>
                          <TableHead>{t.actualSpendCol}</TableHead>
                          <TableHead>{t.attributedRevenue}</TableHead>
                          <TableHead>{t.returnRatioCol}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {(summary?.campaign_budget_roas ?? []).map((r: CampaignBudgetRoas) => {
                          // §167: the backend already divided the revenue by ONE
                          // specific denominator — pick the matching number and
                          // the matching label. Never show `budget_roas` under a
                          // `ROAS` header, and never show `null` as 0 or NaN:
                          // an absent spend feed is its own stated state.
                          const isSpendBasis = r.basis === "actual_spend";
                          const ratio = isSpendBasis ? r.spend_roas : r.budget_roas;
                          const ratioLabel = isSpendBasis ? t.spendRoasLabel : t.budgetRoasLabel;
                          return (
                            <TableRow key={r.campaign_id}>
                              <TableCell className="font-semibold">{r.name}</TableCell>
                              <TableCell dir="ltr">
                                {r.planned_budget === null ? (
                                  <span
                                    data-testid="no-planned-budget"
                                    className="text-[12px] text-muted-foreground"
                                  >
                                    {t.noPlannedBudget}
                                  </span>
                                ) : (
                                  formatMoney(r.planned_budget, currency)
                                )}
                              </TableCell>
                              <TableCell dir="ltr">
                                {r.actual_spend === null ? (
                                  <span
                                    data-testid="no-spend-feed"
                                    className="text-[12px] text-muted-foreground"
                                  >
                                    {t.noSpendFeed}
                                  </span>
                                ) : (
                                  formatMoney(r.actual_spend, currency)
                                )}
                              </TableCell>
                              <TableCell dir="ltr" data-testid="attributed-credit">
                                {formatMoney(r.revenue, currency)}
                              </TableCell>
                              <TableCell dir="ltr">
                                {ratio === null ? (
                                  <span className="text-[12px] text-muted-foreground">
                                    {isSpendBasis ? t.noSpendFeed : t.noPlannedBudget}
                                  </span>
                                ) : (
                                  <div className="flex flex-col items-start gap-0.5">
                                    <Badge variant={ratio >= 1 ? "success" : "danger"}>
                                      {ratio.toFixed(2)}×
                                    </Badge>
                                    <span className="text-[11px] text-muted-foreground">
                                      {ratioLabel}
                                    </span>
                                  </div>
                                )}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                    <p className="px-4 pt-3 text-[11px] text-muted-foreground">
                      {t.attributedCreditHint}
                    </p>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.newCampaignTitle}</DialogTitle>
            <DialogDescription>سمِّ الحملة واختر المنصة لتتبع العائد.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="c-name">{t.campaignName}</Label>
              <Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="c-provider">{t.provider}</Label>
              <Select id="c-provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="facebook">Facebook</option>
                <option value="google">Google</option>
                <option value="tiktok">TikTok</option>
                <option value="snapchat">Snapchat</option>
                <option value="manual">يدوي</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="c-budget">{t.budget}</Label>
              <Input
                id="c-budget"
                type="number"
                dir="ltr"
                min="0"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={submit} disabled={createCampaign.isPending || !name.trim()}>
              {t.save}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t.cancel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
