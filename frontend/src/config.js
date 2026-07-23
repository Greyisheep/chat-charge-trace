/** Central runtime configuration (values come from the repo root .env). */

// Unset falls back to the local dev backend. An explicitly EMPTY value means
// same-origin: in the docker image, nginx proxies /v1, /api and /webhooks to
// the backend container, so relative URLs are all the browser needs.
const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
export const API_BASE_URL =
  rawApiBaseUrl === undefined ? "http://localhost:8000" : rawApiBaseUrl;

export const MONNIFY_API_KEY = import.meta.env.VITE_MONNIFY_API_KEY || "";
export const MONNIFY_CONTRACT_CODE =
  import.meta.env.VITE_MONNIFY_CONTRACT_CODE || "";
