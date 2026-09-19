import { copyNotices } from "./copy-notices.mjs";
import { defineConfig } from "vite";
import { cpSync, copyFileSync, mkdirSync } from "node:fs";
export default defineConfig({
  base: "/board-assets/",
  build: { outDir: "../session-canvas/board-assets", emptyOutDir: true },
  plugins: [
    {
      name: "local-editor-assets",
      writeBundle() {
        const out = "../session-canvas/board-assets";
        copyNotices(out);
        cpSync(
          "node_modules/@excalidraw/excalidraw/dist/prod/fonts",
          out + "/fonts",
          { recursive: true },
        );
        copyFileSync(out + "/index.html", "../session-canvas/index.html");
      },
    },
  ],
});
