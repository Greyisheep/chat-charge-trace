/** Central runtime configuration (values come from the repo root .env). */

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const MONNIFY_API_KEY = import.meta.env.VITE_MONNIFY_API_KEY || "";
export const MONNIFY_CONTRACT_CODE =
  import.meta.env.VITE_MONNIFY_CONTRACT_CODE || "";
