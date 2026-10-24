import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Локально API может жить не на 8000 (порт занят) — тогда AEZA_API_TARGET=http://127.0.0.1:8011
const apiTarget = process.env.AEZA_API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": apiTarget,
      "/metrics": apiTarget,
    },
  },
});
