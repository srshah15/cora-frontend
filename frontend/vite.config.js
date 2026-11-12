import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // 5173 is the origin the backend's CORS list allows. strictPort makes Vite
  // fail instead of silently moving to 5174, which the backend would reject.
  server: { port: 5173, strictPort: true },
  test: {
    environment: "jsdom", // a simulated browser, so components can render in Node
    globals: true,
    setupFiles: "./src/test/setup.js",
    css: false,
    exclude: ["legacy/**", "node_modules/**", "dist/**"],
  },
});
