import axios from "axios";
import { API_BASE_URL } from "../utils/constants";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

// Bearer token + language request interceptor
// Skip auth header for public auth endpoints (except /me which requires auth)
api.interceptors.request.use((config) => {
  config.headers = config.headers || {};

  // Always send current language
  const lang = localStorage.getItem("ada_language") || "en";
  config.headers["Accept-Language"] = lang;

  const isAuthEndpoint =
    config.url?.startsWith("/api/v1/auth/") && !config.url?.endsWith("/me");
  if (!isAuthEndpoint) {
    const token = window.__ada_get_access_token?.();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// 401 response interceptor — attempt token refresh then retry once
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const isAuthEndpoint = original?.url?.startsWith("/api/v1/auth/");
    if (
      error.response?.status === 401 &&
      !original._retry &&
      !isAuthEndpoint
    ) {
      original._retry = true;
      try {
        const newToken = await window.__ada_refresh_token?.();
        if (newToken) {
          original.headers = original.headers || {};
          original.headers.Authorization = `Bearer ${newToken}`;
          return api(original);
        }
      } catch {
        // Fall through to reject
      }
    }
    return Promise.reject(error);
  }
);

export default api;

export const resolveImageUrl = (url) => {
  if (!url) return url;
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  return `${API_BASE_URL}${url}`;
};
