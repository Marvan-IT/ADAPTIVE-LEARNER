import { createContext, useContext, useState, useRef, useEffect, useCallback } from "react";
import { jwtDecode } from "jwt-decode";
import * as authApi from "../api/auth";

const AuthContext = createContext(null);

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const accessTokenRef = useRef(null);
  const refreshTimerRef = useRef(null);
  const refreshPromiseRef = useRef(null);

  const scheduleRefresh = useCallback((accessToken, refreshFn) => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    if (!accessToken) return;
    try {
      const decoded = jwtDecode(accessToken);
      const expiresIn = decoded.exp * 1000 - Date.now() - 60000; // 1 min before expiry
      if (expiresIn > 0) {
        refreshTimerRef.current = setTimeout(refreshFn, expiresIn);
      }
    } catch {
      // Invalid token — do not schedule
    }
  }, []);

  const setTokens = useCallback(
    (accessToken, refreshTokenValue) => {
      accessTokenRef.current = accessToken;
      if (refreshTokenValue) {
        localStorage.setItem("ada_refresh_token", refreshTokenValue);
      }
    },
    []
  );

  const doRefresh = useCallback(async () => {
    // Deduplicate concurrent refresh calls (prevents token rotation race)
    if (refreshPromiseRef.current) return refreshPromiseRef.current;

    const rt = localStorage.getItem("ada_refresh_token");
    if (!rt) return null;

    refreshPromiseRef.current = (async () => {
      try {
        const { data } = await authApi.refreshToken(rt);
        accessTokenRef.current = data.access_token;
        if (data.refresh_token) {
          localStorage.setItem("ada_refresh_token", data.refresh_token);
        }
        setUser(data.user);
        scheduleRefresh(data.access_token, doRefresh);
        return data.access_token;
      } catch (err) {
        const status = err?.response?.status;
        if (status === 401 || status === 403) {
          // Genuine auth failure — token invalid/expired/reused. Clear session.
          accessTokenRef.current = null;
          localStorage.removeItem("ada_refresh_token");
          setUser(null);
        } else {
          // Transient error (network, 5xx, timeout) — keep tokens, retry later.
          console.warn("[auth] Token refresh failed (transient), will retry:", err?.message);
          scheduleRefresh(accessTokenRef.current, doRefresh);
        }
        return null;
      } finally {
        refreshPromiseRef.current = null;
      }
    })();

    return refreshPromiseRef.current;
  }, [scheduleRefresh]);

  // On mount: restore session and expose window helpers for the API client
  useEffect(() => {
    const init = async () => {
      const rt = localStorage.getItem("ada_refresh_token");
      if (rt) {
        await doRefresh();
      }
      setLoading(false);
    };

    window.__ada_get_access_token = () => accessTokenRef.current;
    window.__ada_refresh_token = doRefresh;

    // Refresh token when tab becomes visible after being inactive
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        const token = accessTokenRef.current;
        if (!token) return;
        try {
          const decoded = jwtDecode(token);
          const timeLeft = decoded.exp * 1000 - Date.now();
          if (timeLeft < 120000) doRefresh(); // less than 2 min left
        } catch {
          doRefresh();
        }
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);

    init();

    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      document.removeEventListener("visibilitychange", handleVisibility);
      delete window.__ada_get_access_token;
      delete window.__ada_refresh_token;
    };
  }, [doRefresh]);

  const login = useCallback(async (email, password) => {
    const { data } = await authApi.loginUser(email, password);
    accessTokenRef.current = data.access_token;
    if (data.refresh_token) {
      localStorage.setItem("ada_refresh_token", data.refresh_token);
    }
    setUser(data.user);
    scheduleRefresh(data.access_token, doRefresh);
    return data.user;
  }, [scheduleRefresh, doRefresh]);

  const logout = useCallback(async () => {
    const rt = localStorage.getItem("ada_refresh_token");
    if (rt) {
      try { await authApi.logoutUser(rt); } catch { /* ignore */ }
    }
    accessTokenRef.current = null;
    localStorage.removeItem("ada_refresh_token");
    localStorage.removeItem("ada_student_id");
    localStorage.removeItem("ada_language");
    setUser(null);
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
  }, []);

  const getAccessToken = useCallback(() => accessTokenRef.current, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        getAccessToken,
        doRefresh,
        setUser,
        setTokens,
        isAuthenticated: !!user,
        isAdmin: user?.role === "admin",
        isStudent: user?.role === "student",
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
