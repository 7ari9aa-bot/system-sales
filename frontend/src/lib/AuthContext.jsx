import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api, getTokens, setTokens, prefetchDashboard, ApiError } from "@/lib/api";

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
      setAuthError(null);
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
    } catch (error) {
      setUser(null);
      if (error?.status === 401 || error?.code === "unauthorized") {
        setTokens(null);
        setAuthError({ type: "auth_required" });
      } else if (error?.code === "user_not_registered") {
        setTokens(null);
        setAuthError({ type: "user_not_registered" });
      } else {
        // A network/server failure is not proof that a saved session expired.
        setAuthError({ type: "auth_unavailable", message: error?.message });
      }
      return false;
    } finally {
      setLoadingAuth(false);
    }
  }, []);

  useEffect(() => {
    void checkUserAuth();
  }, [checkUserAuth]);

  const login = useCallback(async (email, password) => {
    let data;
    try {
      data = await api("/auth/login", { method: "POST", body: { email, password } });
    } catch (error) {
      if (error?.code === "mfa_required") {
        const challengeId = error?.details?.challenge_id ?? error?.details?.challengeId;
        if (challengeId) return { requiresMfa: true, challengeId };
        throw new ApiError("The server requires MFA but did not return a challenge ID.", {
          status: error.status,
          code: error.code,
        });
      }
      throw error;
    }
    if (!data?.access_token || !data?.refresh_token) {
      throw new ApiError("The server returned an incomplete login response.", { code: "invalid_token_pair" });
    }
    setTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
    const me = await api("/auth/me");
    setUser(me);
    setAuthError(null);
    prefetchDashboard(); // بعد الدخول: البيانات بتتحمل قبل ما الداشبورد يفتح
    return me;
  }, []);

  const verifyMfa = useCallback(async (challengeId, code) => {
    const data = await api("/auth/mfa/verify", {
      method: "POST",
      body: { challenge_id: challengeId, code },
    });
    if (!data?.access_token || !data?.refresh_token) {
      throw new ApiError("The server returned an incomplete login response.", { code: "invalid_token_pair" });
    }
    setTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
    const me = await api("/auth/me");
    setUser(me);
    setAuthError(null);
    prefetchDashboard();
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
    // كوكي الـrefresh هي اللي بتعرف السيرفر بالجلسة — الجسم فاضي، والسيرفر
    // بيلغي عائلة التوكن ويمسح الكوكي بنفسه. الشبكة الواقعة ما تمنعش الخروج.
    try {
      await api("/auth/logout", { method: "POST", body: {} });
    } catch {
      /* الشبكة غير متاحة — نكمل الخروج */
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
    verifyMfa,
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
