"use client";

/** §47/M10 remainder — the merchant's own DAY, set beside the merchant's money.
 *
 *  analytics buckets a calendar day, and the zone it uses now comes from this
 *  tenant's row (`tenants.timezone`) instead of one deployment-wide setting.
 *  The surface is deliberately the sibling of §47's currency: the value is
 *  read from the server (never assumed), the write is audited, and an
 *  unresolvable zone is refused rather than stored.
 *
 *  `timezone: null` is a real answer, not a missing one — it means "the
 *  deployment's zone", which is what every tenant had before this column
 *  existed. The EFFECTIVE zone a merchant's reports were bucketed in is echoed
 *  by the analytics responses themselves (`timezone` + `timezone_source`),
 *  because only the code that did the bucketing can say which layer answered.
 */

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { api } from "@/lib/api";
import { useMe, useTenantCurrency } from "@/lib/queries";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

/** `GET`/`PUT /tenants/{id}/timezone`. Nullable by design: NULL = the
 *  deployment zone. Declared here rather than in lib/queries.ts so this card
 *  owns its own contract without widening a shared module. */
type TenantTimezone = { tenant_id: string; timezone: string | null };

const TIMEZONE_LABEL = "المنطقة الزمنية للمتجر";
const TIMEZONE_HINT =
  "اسم IANA مثل Africa/Cairo أو Asia/Dubai. اتركه فارغًا للرجوع إلى إعداد النظام.";

export function timezoneQueryKey(tenantId: string | null | undefined) {
  return ["tenants", tenantId ?? "", "timezone"] as const;
}

/** Why this is not a usable zone, or null.
 *
 *  The browser answers with its own IANA database (`Intl`, backed by the same
 *  tzdata naming the server validates through Python's `zoneinfo`), so the two
 *  agree on what "exists" means. This is the don't-send-a-known-wrong-value
 *  half of §47's currency rule; the server's refusal stays authoritative and is
 *  what actually protects the row.
 */
export function timezoneRefusal(value: string): string | null {
  const name = value.trim();
  if (!name) return null; // empty means "clear the setting" — the server accepts that
  try {
    const probe = new Intl.DateTimeFormat("en-US", { timeZone: name });
    void probe;
  } catch {
    return `"${name}" ليست منطقة زمنية صالحة. استخدم اسم IANA مثل Africa/Cairo`;
  }
  return null;
}

export function MerchantDayCard() {
  const me = useMe();
  const tenantId = me.data?.tenants?.[0]?.id ?? null;
  const queryClient = useQueryClient();
  const currencyQuery = useTenantCurrency(tenantId);

  const zoneQuery = useQuery<TenantTimezone>({
    queryKey: timezoneQueryKey(tenantId),
    queryFn: () => api<TenantTimezone>(`/tenants/${tenantId}/timezone`),
    enabled: Boolean(tenantId),
    retry: false,
  });

  const [draft, setDraft] = React.useState("");
  const stored = zoneQuery.data?.timezone ?? "";
  React.useEffect(() => {
    setDraft(stored);
  }, [stored]);

  const save = useMutation({
    mutationFn: (value: string) =>
      api<TenantTimezone>(`/tenants/${tenantId}/timezone`, {
        method: "PUT",
        body: { timezone: value.trim() },
      }),
    onSuccess: (row) => {
      queryClient.setQueryData(timezoneQueryKey(tenantId), row);
      setDraft(row.timezone ?? "");
    },
  });

  const refusal = timezoneRefusal(draft);
  const trimmed = draft.trim();
  const dirty = trimmed !== stored;

  return (
    <Card data-testid="merchant-day-card">
      <CardHeader>
        <CardTitle>يوم المتجر</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-[1fr_200px_auto] sm:items-end">
          <div>
            <Label htmlFor="tz">{TIMEZONE_LABEL}</Label>
            <Input
              id="tz"
              dir="ltr"
              placeholder="Africa/Cairo"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={zoneQuery.isLoading || save.isPending}
              aria-invalid={Boolean(refusal)}
              data-testid="timezone-input"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {refusal ?? TIMEZONE_HINT}
            </p>
          </div>
          <div className="text-[13px] text-muted-foreground">
            <span className="block font-semibold text-foreground">
              {currencyQuery.data?.currency ?? "—"}
            </span>
            عملة المتجر
          </div>
          <Button
            onClick={() => save.mutate(trimmed)}
            disabled={Boolean(refusal) || !dirty || save.isPending || !tenantId}
            data-testid="save-timezone"
          >
            <Clock aria-hidden="true" />
            حفظ
          </Button>
        </div>

        {zoneQuery.isLoading ? (
          <Skeleton className="mt-3 h-4 w-64" />
        ) : (
          <p className="mt-3 text-xs text-muted-foreground" data-testid="timezone-state">
            {stored
              ? `تُحسب أيامك وفق ${stored}.`
              : "لم تختر منطقة: التقارير تُحسب على المنطقة الافتراضية للنظام."}
          </p>
        )}

        {(zoneQuery.error ?? save.error) && (
          <p className="mt-2 text-sm text-danger" data-testid="timezone-error">
            {String((save.error ?? zoneQuery.error)?.message ?? "")}
          </p>
        )}
        {save.isSuccess && !save.isPending && (
          <p className="mt-2 text-sm text-success">تم حفظ المنطقة الزمنية.</p>
        )}
      </CardContent>
    </Card>
  );
}
