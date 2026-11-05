import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Relative paths, so the build can be served from any folder of a static server.
export default defineConfig({ plugins: [react()], base: "./" });
