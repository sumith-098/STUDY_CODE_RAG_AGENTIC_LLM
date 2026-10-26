// Vite config: React plugin + dev server port 5173 (backend CORS isi port ko allow karta hai).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({ plugins: [react()], server: { port: 5173 } });
