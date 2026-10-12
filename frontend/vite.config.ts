import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy API calls to the FastAPI backend so the browser sees one origin
    // in development. Production deployments should serve the built assets
    // behind the same host, or configure CORS_ORIGINS on the backend.
    proxy: {
      '/api': {
        // The end-to-end tests run their own backend on another port.
        target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
