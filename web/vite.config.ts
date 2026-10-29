/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { host: "localhost", port: 5173, strictPort: true },
  build: { sourcemap: false, target: "es2022" },
  test: { environment: "node", include: ["src/**/*.test.ts"], css: { include: [/styles\.css/] } },
});
