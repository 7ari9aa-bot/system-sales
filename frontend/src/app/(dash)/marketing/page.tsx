"use client";

import * as React from "react";
import { Megaphone, Plus } from "lucide-react";
import { useCampaigns, useCreateCampaign, useMarketingSummary, type Campaign } from "@/lib/queries";
import { t } from "@/lib/t";
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
          {summary && (
            <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Card>
                <CardContent className="p-5">
                  <div className="text-[26px] font-bold leading-tight" dir="ltr">
                    {Number(summary.orders_summary.revenue).toFixed(0)}
                  </div>
                  <div className="mt-0.5 text-[13px] text-muted-foreground">{t.revenue30}</div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-5">
                  <div className="text-[26px] font-bold leading-tight" dir="ltr">
                    {summary.orders_summary.orders_count}
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
                          <TableCell dir="ltr">{c.budget ? Number(c.budget).toFixed(0) : "—"}</TableCell>
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

            <Card>
              <CardHeader>
                <CardTitle>{t.roas}</CardTitle>
              </CardHeader>
              <CardContent className="p-0 pb-2">
                {(summary?.campaign_roas ?? []).length === 0 ? (
                  <EmptyState title={t.noRoasData} />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t.campaigns}</TableHead>
                        <TableHead>{t.spend}</TableHead>
                        <TableHead>{t.revenue}</TableHead>
                        <TableHead>ROAS</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(summary?.campaign_roas ?? []).map((r) => (
                        <TableRow key={r.campaign_id}>
                          <TableCell className="font-semibold">{r.name}</TableCell>
                          <TableCell dir="ltr">{Number(r.spend).toFixed(0)}</TableCell>
                          <TableCell dir="ltr">{Number(r.revenue).toFixed(0)}</TableCell>
                          <TableCell dir="ltr">
                            {r.roas === null ? (
                              "—"
                            ) : (
                              <Badge variant={r.roas >= 1 ? "success" : "danger"}>{r.roas.toFixed(2)}×</Badge>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
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
