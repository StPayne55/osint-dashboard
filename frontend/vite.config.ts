import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 43145,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8742",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 43145,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8742",
        changeOrigin: true,
      },
    },
  },
});
