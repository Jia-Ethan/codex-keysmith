import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { readFileSync } from "node:fs";

const packageJson = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8"),
);
const sourceCommit = process.env.CODEX_KEYSMITH_SOURCE_COMMIT || "";
if (sourceCommit && !/^[0-9a-f]{40}$/.test(sourceCommit)) {
  throw new Error("CODEX_KEYSMITH_SOURCE_COMMIT must be a full lowercase commit SHA");
}
const buildInfo = {
  desktopVersion: packageJson.version,
  sourceCommit: sourceCommit || null,
};

// Tauri 2 标准配置：固定端口，strictPort，清空输出目录
export default defineConfig({
  clearScreen: false,
  plugins: [react(), tailwindcss()],
  define: {
    __CODEX_KEYSMITH_BUILD_INFO__: JSON.stringify(buildInfo),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{js,jsx}"],
  },
});
