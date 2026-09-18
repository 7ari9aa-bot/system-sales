"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type Campaign = {
  id: string;
  name: string;
  provider: string;
  status: string;
  budget: string | null;
};

type Summary = {
  orders_summary: { orders_count: number; revenue: number; aov: number };
  revenue_by_source: { source: string; revenue: number; conversions: number }[];
  revenue_by_campaign: { campaign_id: string; campaign_name: string; revenue: number; conversions: number }[];
  campaign_roas: { campaign_id: string; name: string; spend: number; revenue: number; roas: number | null }[];
};

export default function MarketingPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("facebook");
  const [budget, setBudget] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        api<{ items: Campaign[] }>("/marketing/campaigns").then((r) => r.items),
        api<Summary>("/analytics/summary"),
      ]);
      setCampaigns(c);
      setSummary(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createCampaign() {
    setError("");
    try {
      await api("/marketing/campaigns", {
        method: "POST",
        body: {
          name,
          provider,
          budget: budget ? Number(budget) : null,
        },
      });
      setName("");
      setBudget("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }

  return (
    <div>
      <h1 className="page-title">{t.marketing}</h1>
      {error && <p className="error-text">{error}</p>}

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>حملة جديدة</h3>
        <div className="form-grid">
          <div>
            <label htmlFor="c-name">الاسم</label>
            <input id="c-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label htmlFor="c-provider">المنصة</label>
            <select id="c-provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="facebook">Facebook</option>
              <option value="google">Google</option>
              <option value="tiktok">TikTok</option>
              <option value="snapchat">Snapchat</option>
              <option value="manual">يدوي</option>
            </select>
          </div>
          <div>
            <label htmlFor="c-budget">الميزانية</label>
            <input
              id="c-budget"
              type="number"
              dir="ltr"
              min="0"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
            />
          </div>
          <div style={{ alignSelf: "end" }}>
            <button className="btn" onClick={createCampaign} disabled={!name.trim()}>
              {t.save}
            </button>
          </div>
        </div>
      </div>

      {summary && (
        <div className="stats-grid">
          <div className="card stat">
            <div className="value" dir="ltr">{Number(summary.orders_summary.revenue).toFixed(0)}</div>
            <div className="label">إيرادات 30 يوم</div>
          </div>
          <div className="card stat">
            <div className="value" dir="ltr">{summary.orders_summary.orders_count}</div>
            <div className="label">طلبات 30 يوم</div>
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>الحملات</h3>
          <table className="table">
            <thead>
              <tr>
                <th>الاسم</th>
                <th>المنصة</th>
                <th>الميزانية</th>
                <th>{t.status}</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td>{c.provider}</td>
                  <td dir="ltr">{c.budget ? Number(c.budget).toFixed(0) : "—"}</td>
                  <td>
                    <span className={`badge ${c.status === "active" ? "badge-success" : ""}`}>{c.status}</span>
                  </td>
                </tr>
              ))}
              {campaigns.length === 0 && (
                <tr>
                  <td colSpan={4} className="empty">لا توجد حملات</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3 style={{ marginTop: 0 }}>العائد على الإنفاق (ROAS)</h3>
          <table className="table">
            <thead>
              <tr>
                <th>الحملة</th>
                <th>الإنفاق</th>
                <th>الإيراد</th>
                <th>ROAS</th>
              </tr>
            </thead>
            <tbody>
              {(summary?.campaign_roas ?? []).map((r) => (
                <tr key={r.campaign_id}>
                  <td>{r.name}</td>
                  <td dir="ltr">{Number(r.spend).toFixed(0)}</td>
                  <td dir="ltr">{Number(r.revenue).toFixed(0)}</td>
                  <td dir="ltr">
                    {r.roas === null ? "—" : (
                      <span className={`badge ${r.roas >= 1 ? "badge-success" : "badge-danger"}`}>
                        {r.roas.toFixed(2)}×
                      </span>
                    )}
                  </td>
                </tr>
              ))}
              {(summary?.campaign_roas ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="empty">لا توجد بيانات عائد بعد</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
