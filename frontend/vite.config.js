import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// envDir points at the repo root so the root .env feeds VITE_* vars.
export default defineConfig({
  plugins: [react()],
  envDir: "..",
  server: {
    port: 5173,
  },
});
