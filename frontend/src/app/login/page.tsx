"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { API_BASE_URL, API_PREFIX, setTokens } from "@/lib/api";
import { t } from "@/lib/t";

type Mode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [storeName, setStoreName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const url =
        mode === "login"
          ? `${API_BASE_URL}${API_PREFIX}/auth/login`
          : `${API_BASE_URL}${API_PREFIX}/auth/register`;
      const body =
        mode === "login"
          ? { email, password }
          : {
              email,
              password,
              full_name: fullName,
              tenant_name: storeName,
              tenant_slug: storeName
                .trim()
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "-")
                .slice(0, 40) || `store-${Date.now()}`,
            };
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error?.message ?? data?.detail ?? `خطأ ${res.status}`);
      }
      const data = await res.json();
      if (data.access_token) {
        setTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
        router.replace("/inbox");
      } else {
        // registration returns profile → then log in
        const login = await fetch(`${API_BASE_URL}${API_PREFIX}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const pair = await login.json();
        setTokens({ access_token: pair.access_token, refresh_token: pair.refresh_token });
        router.replace("/inbox");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "حدث خطأ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-wrap">
      <div className="card auth-card">
        <h1>{t.brand}</h1>
        <div className="auth-tabs">
          <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")} data-testid="tab-login">
            {t.login}
          </button>
          <button
            className={mode === "register" ? "active" : ""}
            onClick={() => setMode("register")}
            data-testid="tab-register"
          >
            {t.register}
          </button>
        </div>
        <form className="auth-form" onSubmit={submit}>
          {mode === "register" && (
            <>
              <div>
                <label htmlFor="storeName">{t.storeName}</label>
                <input id="storeName" value={storeName} onChange={(e) => setStoreName(e.target.value)} required />
              </div>
              <div>
                <label htmlFor="fullName">{t.fullName}</label>
                <input id="fullName" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
              </div>
            </>
          )}
          <div>
            <label htmlFor="email">{t.email}</label>
            <input id="email" type="email" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label htmlFor="password">{t.password}</label>
            <input
              id="password"
              type="password"
              dir="ltr"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="error-text">{error}</p>}
          <button className="btn" disabled={busy} data-testid="submit-auth">
            {mode === "login" ? t.login : t.register}
          </button>
        </form>
      </div>
    </main>
  );
}
