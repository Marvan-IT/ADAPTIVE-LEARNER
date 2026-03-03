import axios from "axios";
import { API_BASE_URL } from "../utils/constants";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const key = import.meta.env.VITE_API_SECRET_KEY;
  if (key) {
    config.headers = config.headers || {};
    config.headers["X-API-Key"] = key;
  }
  return config;
});

export default api;
