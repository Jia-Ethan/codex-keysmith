import { defineConfig } from "vite";

// Tauri 2 标准配置：固定端口，strictPort，清空输出目录
export default defineConfig({
  clearScreen: false,
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
});
