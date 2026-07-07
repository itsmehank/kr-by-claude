import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// .md 정적 파일(public/library 등)을 charset 없이 보내면 브라우저가
// 한글을 깨뜨림 → dev/preview 서버 모두 utf-8 명시
function mdCharset(): Plugin {
  const setHeader = (server: {
    middlewares: import("vite").Connect.Server;
  }) => {
    server.middlewares.use((req, res, next) => {
      if (req.url?.split("?")[0].endsWith(".md")) {
        res.setHeader("Content-Type", "text/markdown; charset=utf-8");
      }
      next();
    });
  };
  return {
    name: "md-charset",
    configureServer: setHeader,
    configurePreviewServer: setHeader,
  };
}

export default defineConfig({
  plugins: [react(), mdCharset()],
  server: {
    proxy: {
      "/api": process.env.VITE_API_TARGET || "http://localhost:8000",
    },
    fs: {
      // prompts/ 디렉터리 (vite root 외부) 접근 허용
      allow: [path.resolve(__dirname, "..")],
    },
  },
});
