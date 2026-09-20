import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // Extra dev-server hostnames from the environment (e.g. the Compose
    // service name for in-network browser runs). The default stays locked
    // to localhost + the production dev domain (DNS-rebinding protection).
    allowedHosts: [
      "dev.docs.midtowntg.com",
      ...(process.env.VITE_DEV_ALLOWED_HOSTS ?? "")
        .split(",")
        .map((h) => h.trim())
        .filter(Boolean),
    ],
    proxy: {
      "/api": {
        target: process.env.API_URL || "http://localhost:8001",
        changeOrigin: true,
      },
      // Proxy /auth/* to backend EXCEPT /auth/callback/* which is handled client-side
      "/auth": {
        target: process.env.API_URL || "http://localhost:8001",
        changeOrigin: true,
        bypass: (req) => {
          // Let /auth/callback/* be handled by React Router (client-side)
          if (req.url?.startsWith("/auth/callback")) {
            return req.url;
          }
          return undefined;
        },
      },
      "/health": {
        target: process.env.API_URL || "http://localhost:8001",
        changeOrigin: true,
      },
      "/ws": {
        target: process.env.API_URL || "http://localhost:8001",
        changeOrigin: true,
        ws: true,
      },
      "/docs": {
        target: process.env.API_URL || "http://localhost:8001",
        changeOrigin: true,
      },
      "/redoc": {
        target: process.env.API_URL || "http://localhost:8001",
        changeOrigin: true,
      },
      "/openapi.json": {
        target: process.env.API_URL || "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
});
