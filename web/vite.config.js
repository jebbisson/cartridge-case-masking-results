import { defineConfig } from 'vite';

export default defineConfig({
  esbuild: { jsx: 'automatic' },
  server: {
    host: '127.0.0.1',
    proxy: { '/api': process.env.REVIEW_API_URL || 'http://127.0.0.1:8787' },
  },
});
