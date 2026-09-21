"use client";

import * as React from "react";
import { Activity, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { t } from "@/lib/t";
import { PageHeader } from "@/components/ui/states";

interface SLOStatus {
  name: string;
  compliance_percent: number;
  target_percent: number;
  status: string;
  total: number;
  met: number;
}

interface HealthCheck {
  name: string;
  healthy: boolean;
  latency_ms: number;
  error: string | null;
}

export default function OperationsPage() {
  const [slos, setSlos] = React.useState<SLOStatus[]>([]);
  const [health, setHealth] = React.useState<HealthCheck[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    async function load() {
      try {
        const [sloRes, healthRes] = await Promise.all([
          fetch("/api/operations/slos").then((r) => r.json()),
          fetch("/api/operations/health").then((r) => r.json()),
        ]);
        setSlos(sloRes.items ?? []);
        setHealth(healthRes.items ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 30000); // refresh every 30s
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <PageHeader title={t.health} subtitle={t.health} />

      {error && (
        <div className="mb-6 rounded-lg border border-danger/20 bg-danger-soft/50 p-4 text-sm text-danger">
          {error}
        </div>
      )}

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
                {h.healthy ? (
                  <CheckCircle2 className="text-success" aria-hidden="true" />
                ) : (
                  <XCircle className="text-danger" aria-hidden="true" />
                )}
                <div className="flex-1">
                  <p className="text-sm font-medium">{h.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {h.healthy ? `${h.latency_ms}ms` : h.error ?? "unhealthy"}
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
