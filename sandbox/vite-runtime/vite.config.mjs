import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    target: "es2020",
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 4096
  }
});
