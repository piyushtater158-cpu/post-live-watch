import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api is forwarded to the local FastAPI server (uvicorn on 8420), the
// same way vercel.json forwards it to Render in production — the app only ever
// calls relative /api paths.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8420",
      "/healthz": "http://127.0.0.1:8420",
    },
  },
});
