import axios from "axios";
import { getToken } from "../auth/auth";

// In production, VITE_API_BASE_URL is set in Render (baked in at build time).
// Locally it's unset, so we fall back to the local backend.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1",
});

// Request interceptor: runs before EVERY request. If we have a token stored,
// attach it as an Authorization: Bearer <token> header automatically, so no
// individual api.get/api.post call has to think about auth.
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
