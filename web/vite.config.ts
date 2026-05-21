import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
    fs: {
      // prompts/ 디렉터리 (vite root 외부) 접근 허용
      allow: [path.resolve(__dirname, "..")],
    },
  },
});
