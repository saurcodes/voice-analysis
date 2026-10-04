import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  build: {
    rolldownOptions: {
      output: {
        // Long-lived vendor code in its own cacheable chunks, so an app-code change does not
        // re-download React or the UI primitives, and no single entry chunk passes 500 kB.
        codeSplitting: {
          groups: [
            { name: "vendor-react", test: /node_modules[\\/](react|react-dom|scheduler|react-router)[\\/]/ },
            { name: "vendor-ui", test: /node_modules[\\/](radix-ui|@radix-ui|motion|motion-dom|motion-utils|framer-motion|@phosphor-icons)[\\/]/ },
          ],
        },
      },
    },
  },
  server: { port: 5173, proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } } },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false },
});
