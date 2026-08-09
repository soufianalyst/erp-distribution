import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
  },
  server: {
    port: 5173,
    proxy: {
      // The FastAPI backend during development.
      "/api": "http://127.0.0.1:8000",
    },
  },
});
