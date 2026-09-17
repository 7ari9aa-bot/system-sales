"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type KnowledgeItem = { id: string; title: string; status: string; created_at: string };
type Agent = { id: string; name: string; model: string | null; is_active: boolean };
type UsageRow = { period_date: string; tokens_in: number; tokens_out: number; cost: string };
type SearchHit = { id: string; title: string; distance: number };

export default function AIPage() {
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const load = useCallback(async () => {
    try {
      const [k, a, u] = await Promise.all([
        api<KnowledgeItem[]>("/ai/knowledge"),
        api<Agent[]>("/ai/agents"),
        api<UsageRow[]>("/ai/usage/summary"),
      ]);
      setItems(k);
      setAgents(a);
      setUsage(u);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function addKnowledge() {
    setError("");
    setOk("");
    try {
      await api("/ai/knowledge", { method: "POST", body: { title, content } });
      setTitle("");
      setContent("");
      setOk("تمت الإضافة");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }

  async function doSearch() {
    setError("");
    setHits(null);
    try {
      const res = await api<SearchHit[]>(
        `/ai/knowledge/search?q=${encodeURIComponent(query.trim())}`,
      );
      setHits(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }

  const totalCost = usage.reduce((sum, r) => sum + Number(r.cost), 0);
  const totalTokens = usage.reduce((sum, r) => sum + r.tokens_in + r.tokens_out, 0);

  return (
    <div>
      <h1 className="page-title">{t.ai}</h1>
      {error && <p className="error-text">{error}</p>}
      {ok && <p className="ok-text">{ok}</p>}

      <div className="stats-grid">
        <div className="card stat">
          <div className="value" dir="ltr">{totalTokens.toLocaleString("en-US")}</div>
          <div className="label">إجمالي التوكنات</div>
        </div>
        <div className="card stat">
          <div className="value" dir="ltr">{totalCost.toFixed(2)}</div>
          <div className="label">{t.usageCost} ($)</div>
        </div>
        <div className="card stat">
          <div className="value" dir="ltr">{agents.length}</div>
          <div className="label">{t.agents}</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t.addKnowledge}</h3>
        <div className="form-grid">
          <div>
            <label htmlFor="k-title">العنوان</label>
            <input id="k-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <label htmlFor="k-content">المحتوى</label>
            <textarea id="k-content" rows={3} value={content} onChange={(e) => setContent(e.target.value)} />
          </div>
          <div style={{ alignSelf: "end" }}>
            <button className="btn" onClick={addKnowledge} disabled={!title.trim() || !content.trim()}>
              {t.save}
            </button>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t.searchKnowledge}</h3>
        <div className="form-grid">
          <div style={{ gridColumn: "1 / -1" }}>
            <input
              placeholder="اكتب سؤالك…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && query.trim() && doSearch()}
            />
          </div>
          <div>
            <button className="btn" onClick={doSearch} disabled={!query.trim()}>
              بحث
            </button>
          </div>
        </div>
        {hits && (
          <ul>
            {hits.length === 0 && <li className="muted">لا نتائج</li>}
            {hits.map((h) => (
              <li key={h.id}>
                {h.title} <span className="muted" dir="ltr">(distance {h.distance.toFixed(3)})</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>{t.knowledge}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>العنوان</th>
              <th>{t.status}</th>
              <th>{t.date}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((k) => (
              <tr key={k.id}>
                <td>{k.title}</td>
                <td>
                  <span className={`badge ${k.status === "indexed" ? "badge-success" : "badge-warning"}`}>
                    {k.status === "indexed" ? "مفهرس" : "قيد المعالجة"}
                  </span>
                </td>
                <td dir="ltr" style={{ fontSize: 12 }}>
                  {new Date(k.created_at).toLocaleDateString("ar-EG-u-nu-latn")}
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={3} className="empty">
                  قاعدة المعرفة فارغة
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
