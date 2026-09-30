import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api, getTokens, setTokens, prefetchDashboard } from "@/lib/api";

/** مصادقة حقيقية على /auth/* — login و register و logout و me.
 *  بيتحمل مرة واحدة: لو فيه توكنات بيجيب /auth/me، ولو فشلت بيمسح
 *  الجلسة. مفيش Base44 ولا Google — المصادقة من الـbackend فقط. */

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoadingAuth, setLoadingAuth] = useState(() => Boolean(getTokens()));
  const [authError, setAuthError] = useState(null);
  const navigate = useNavigate();

  const checkUserAuth = useCallback(async () => {
    if (!getTokens()) {
      setUser(null);
      setLoadingAuth(false);
      return false;
    }
    setLoadingAuth(true);
    try {
      const me = await api("/auth/me");
      setUser(me);
      setAuthError(null);
      prefetchDashboard(); // بيانات الداشبورد تتجهز أول ما الجلسة تفتح
      return true;
    } catch {
      setTokens(null);
      setUser(null);
      setAuthError({ type: "auth_required" });
      return false;
    } finally {
      setLoadingAuth(false);
    }
  }, []);

  useEffect(() => {
    void checkUserAuth();
  }, [checkUserAuth]);

  const login = useCallback(async (email, password) => {
    const data = await api("/auth/login", { method: "POST", body: { email, password } });
    setTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
    const me = await api("/auth/me");
    setUser(me);
    setAuthError(null);
    prefetchDashboard(); // بعد الدخول: البيانات بتتحمل قبل ما الداشبورد يفتح
    return me;
  }, []);

  const register = useCallback(async (payload) => {
    const data = await api("/auth/register", { method: "POST", body: payload });
    if (data?.access_token) {
      setTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
      const me = await api("/auth/me");
      setUser(me);
      setAuthError(null);
      return me;
    }
    return null;
  }, []);

  const logout = useCallback(async () => {
    const tokens = getTokens();
    if (tokens?.refresh_token) {
      try {
        await api("/auth/logout", { method: "POST", body: { refresh_token: tokens.refresh_token } });
      } catch {
        /* الشبكة غير متاحة — نكمل الخروج */
      }
    }
    setTokens(null);
    setUser(null);
  }, []);

  const navigateToLogin = useCallback(() => navigate("/login"), [navigate]);

  const value = {
    user,
    isAuthenticated: Boolean(user),
    isLoadingAuth,
    isLoadingPublicSettings: false,
    authChecked: !isLoadingAuth,
    authError,
    checkUserAuth,
    login,
    register,
    logout,
    navigateToLogin,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
