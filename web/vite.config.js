import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // dev: Vite serves the SPA and proxies the API to Flask (python web/server.py)
  server: { proxy: { "/api": "http://localhost:5055" } },
  // prod: Flask serves this straight out of web/dist/
  build: { outDir: "dist" },
});
