"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { t } from "@/lib/t";
import { PageHeader } from "@/components/ui/states";
import { QueryErrorState } from "@/components/query-error";
import { apiClient } from "@/lib/api";

/** §103 — the operations surface answers the real contracts:
 *
 *  - `GET /api/v1/sla/slos/measure` (SLOMeasurementList) — the compliance
 *    rows the SLO framework defines, measured server-side.
 *  - `GET /api/v1/platform/health` (§103 envelope: overall + subsystems) —
 *    the same surface the top-bar HealthIndicator badge reads.
 *
 *  Both go through `api()`'s client — the page used to raw-`fetch`
 *  `/api/operations/*`, which carried no Authorization header and hit paths
 *  that do not exist, so it rendered a lying empty state instead of data. */

interface SloMeasurement {
  name: string;
  compliance_percent: number;
  target_percent: number;
  status: string;
  total: number;
  met: number;
}

interface HealthRow {
  name: string;
  status: string;
  detail?: string;
}

const SLO_REFRESH_MS = 30_000;

export default function OperationsPage() {
  const slosQuery = useQuery({
    queryKey: ["operations", "slos"],
    queryFn: () => apiClient.get<{ items: SloMeasurement[] }>("/sla/slos/measure"),
    refetchInterval: SLO_REFRESH_MS,
  });

  const healthQuery = useQuery({
    queryKey: ["operations", "health"],
    queryFn: () => apiClient.get<{ status: string; subsystems: HealthRow[] }>("/platform/health"),
    refetchInterval: SLO_REFRESH_MS,
  });

  const loading = slosQuery.isLoading || healthQuery.isLoading;
  const error = slosQuery.error || healthQuery.error;
  const slos = slosQuery.data?.items ?? [];
  const health = healthQuery.data?.subsystems ?? [];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <PageHeader title={t.health} description={t.health} />

      {error && <QueryErrorState queries={[slosQuery, healthQuery]} />}

      {/* Health checks */}
      <section className="mb-8">
        <h2 className="mb-4 text-lg font-bold">System Health</h2>
        {loading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-muted/30" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {health.map((h) => (
              <div
                key={h.name}
                className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4"
              >
                {h.status === "healthy" ? (
                  <CheckCircle2 className="text-success" aria-hidden="true" />
                ) : (
                  <XCircle className="text-danger" aria-hidden="true" />
                )}
                <div className="flex-1">
                  <p className="text-sm font-medium">{h.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {h.status === "healthy" ? "healthy" : (h.detail ?? h.status)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* SLO compliance */}
      <section>
        <h2 className="mb-4 text-lg font-bold">SLO Compliance</h2>
        {loading ? (
          <div className="h-32 animate-pulse rounded-xl border border-border bg-muted/30" />
        ) : slos.length === 0 ? (
          <p className="text-sm text-muted-foreground">No SLOs configured</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/30">
                <tr>
                  <th className="px-4 py-3 text-start font-medium">SLO</th>
                  <th className="px-4 py-3 text-end font-medium">Compliance</th>
                  <th className="px-4 py-3 text-end font-medium">Target</th>
                  <th className="px-4 py-3 text-end font-medium">Met/Total</th>
                  <th className="px-4 py-3 text-center font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {slos.map((s) => (
                  <tr key={s.name} className="border-t border-border">
                    <td className="px-4 py-3 font-mono text-xs">{s.name}</td>
                    <td className="px-4 py-3 text-end">
                      {s.compliance_percent.toFixed(1)}%
                    </td>
                    <td className="px-4 py-3 text-end text-muted-foreground">
                      {s.target_percent}%
                    </td>
                    <td className="px-4 py-3 text-end text-muted-foreground">
                      {s.met}/{s.total}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {s.status === "met" ? (
                        <span className="inline-flex items-center gap-1 text-success">
                          <CheckCircle2 className="size-3.5" />
                          met
                        </span>
                      ) : s.status === "breach" ? (
                        <span className="inline-flex items-center gap-1 text-danger">
                          <AlertTriangle className="size-3.5" />
                          breach
                        </span>
                      ) : (
                        <span className="text-muted-foreground">{s.status}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
