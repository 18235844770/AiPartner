import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

const root = fileURLToPath(new URL(".", import.meta.url));
const midnight = fileURLToPath(new URL("../../static/Midnight-static-assets", import.meta.url));
const slices = fileURLToPath(new URL("../../static/slices", import.meta.url));

export default defineConfig({
  base: "/mobile/",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@slices": slices,
      "@midnight": midnight,
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    fs: {
      allow: [root, slices, midnight],
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
