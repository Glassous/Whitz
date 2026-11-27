import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
import type { Plugin } from "vite";

const webSrc = resolve(__dirname, "../web/src");

// Electron 38 (Chromium) natively supports woff2; drop legacy .woff/.ttf fallbacks from KaTeX CSS and assets.
function katexWoff2OnlyPlugin(): Plugin {
  return {
    name: "whitz-katex-woff2-only",
    enforce: "post",
    generateBundle(_options, bundle) {
      for (const [fileName, item] of Object.entries(bundle)) {
        if (item.type === "asset" && /(?:^|\/)KaTeX_[^/]+\.(?:woff|ttf)$/.test(fileName)) {
          delete bundle[fileName];
        } else if (item.type === "asset" && fileName.endsWith(".css")) {
          const css = typeof item.source === "string" ? item.source : Buffer.from(item.source).toString("utf8");
          item.source = css.replace(
            /,\s*url\(["']?[^)"']*KaTeX_[^)"']+\.(?:woff|ttf)["']?\)\s*format\(["'](?:woff|truetype)["']\)/g,
            "",
          );
        }
      }
    },
  };
}

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: {
        "@shared": resolve(__dirname, "src/shared"),
        "@main": resolve(__dirname, "src/main"),
      },
    },
    build: {
      rollupOptions: {
        input: { index: resolve(__dirname, "src/main/index.ts") },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: { "@shared": resolve(__dirname, "src/shared") },
    },
    build: {
      rollupOptions: {
        input: { index: resolve(__dirname, "src/preload/index.ts") },
        output: { format: "cjs", entryFileNames: "index.js" },
      },
    },
  },
  renderer: {
    root: resolve(__dirname, "src/renderer"),
    publicDir: resolve(__dirname, "../web/public"),
    resolve: {
      dedupe: ["vue", "pinia", "vue-router"],
      alias: {
        "@web": webSrc,
        "@shared": resolve(__dirname, "src/shared"),
        "@renderer": resolve(__dirname, "src/renderer"),
      },
    },
    plugins: [katexWoff2OnlyPlugin(), vue(), tailwindcss()],
    server: {
      port: 5174,
      strictPort: true,
    },
    build: {
      rollupOptions: {
        input: { index: resolve(__dirname, "src/renderer/index.html") },
      },
    },
  },
});
