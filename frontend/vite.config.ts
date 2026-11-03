import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const apiProxy = {
  // Browser always calls same-origin /api; the proxy strips the prefix so the
  // existing FastAPI routes (/repos, /events/stream, ...) are untouched.
  // Port is the API default from the repo README (SENTINEL_API_PORT).
  '/api': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // `vite preview` serves the production build; it needs the same proxy so the
  // built bundle can be exercised against the real API before deployment.
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
});
