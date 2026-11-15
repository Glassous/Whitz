import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [vue(), tailwindcss()],
    server: {
      // 127.0.0.1 instead of localhost keeps the admin refresh cookie separate from web during dev.
      host: "127.0.0.1",
      port: 5174,
      proxy: {
        "/api": {
          target: env.VITE_API_TARGET || "http://localhost:8001",
          changeOrigin: true,
        },
      },
    },
  };
});
