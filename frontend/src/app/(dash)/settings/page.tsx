"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type Invitation = { id: string; email: string; status: string; role_code: string | null; token?: string };
type Integration = { id: string; provider: string; kind: string; status: string };

export default function SettingsPage() {
  const [email, setEmail] = useState("");
  const [roleCode, setRoleCode] = useState("staff");
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const load = useCallback(async () => {
    try {
      const [inv, integ] = await Promise.all([
        api<Invitation[]>("/invitations"),
        api<Integration[]>("/integrations"),
      ]);
      setInvitations(inv);
      setIntegrations(integ);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function invite() {
    setError("");
    setOk("");
    try {
      const tenantId = await api<{ id: string; tenants: { id: string }[] }>("/auth/me");
      const tenant_id = tenantId.tenants?.[0]?.id ?? tenantId.id;
      const created = await api<Invitation>(`/tenants/${tenant_id}/invitations`, {
        method: "POST",
        body: { email, role_code: roleCode },
      });
      setInvitation(created);
      setEmail("");
      setOk("تم إنشاء الدعوة — أرسل الرابط لعضو الفريق");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }

  return (
    <div>
      <h1 className="page-title">{t.settings}</h1>
      {error && <p className="error-text">{error}</p>}
      {ok && <p className="ok-text">{ok}</p>}

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t.invite}</h3>
        <div className="form-grid">
          <div>
            <label htmlFor="inv-email">{t.email}</label>
            <input id="inv-email" type="email" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label htmlFor="inv-role">{t.role}</label>
            <select id="inv-role" value={roleCode} onChange={(e) => setRoleCode(e.target.value)}>
              <option value="staff">{t.staff}</option>
              <option value="manager">{t.manager}</option>
              <option value="owner">{t.owner}</option>
            </select>
          </div>
          <div style={{ alignSelf: "end" }}>
            <button className="btn" onClick={invite} disabled={!email.trim()} data-testid="create-invitation">
              {t.invite}
            </button>
          </div>
        </div>
        {invitation && (
          <p className="muted">
            رابط القبول:{" "}
            <code dir="ltr" style={{ fontSize: 12 }}>
              /accept?token={invitation.token}
            </code>
          </p>
        )}
        {invitations.length > 0 && (
          <table className="table" style={{ marginTop: "0.75rem" }}>
            <thead>
              <tr>
                <th>{t.email}</th>
                <th>{t.role}</th>
                <th>{t.status}</th>
              </tr>
            </thead>
            <tbody>
              {invitations.map((inv) => (
                <tr key={inv.id}>
                  <td dir="ltr">{inv.email}</td>
                  <td>{inv.role_code ?? "—"}</td>
                  <td>
                    <span className={`badge ${inv.status === "pending" ? "badge-warning" : "badge-success"}`}>
                      {inv.status === "pending" ? "قيد الانتظار" : inv.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>{t.integrations}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>القناة / المزوّد</th>
              <th>النوع</th>
              <th>{t.status}</th>
            </tr>
          </thead>
          <tbody>
            {integrations.map((i) => (
              <tr key={i.id}>
                <td>{i.provider}</td>
                <td>{i.kind}</td>
                <td>
                  <span className={`badge ${i.status === "connected" ? "badge-success" : "badge-danger"}`}>
                    {i.status === "connected" ? "متصل" : "غير متصل"}
                  </span>
                </td>
              </tr>
            ))}
            {integrations.length === 0 && (
              <tr>
                <td colSpan={3} className="empty">
                  لا توجد تكاملات — أضف قناة واتساب أو تليجرام من لوحة التحكم
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
