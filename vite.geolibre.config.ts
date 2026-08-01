import { defineConfig } from "vite"

export default defineConfig({
  build: {
    outDir: "geolibre-plugin/dist",
    emptyOutDir: true,
    lib: {
      entry: "src/plugin.ts",
      formats: ["es"],
      fileName: () => "index.js"
    },
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        assetFileNames: asset => asset.name?.endsWith(".css") ? "style.css" : "[name][extname]"
      }
    },
    sourcemap: false,
    minify: "esbuild"
  }
})
