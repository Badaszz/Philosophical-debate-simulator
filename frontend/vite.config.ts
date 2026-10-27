import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/debate": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
    },
  },
});