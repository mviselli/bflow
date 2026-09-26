import { defineConfig } from 'vite';

// The page talks to the Python server on /ws (and /api). In development and
// preview Vite forwards these paths to it, so the page uses its own address.
const pythonServer = {
  '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
  '/api': { target: 'http://127.0.0.1:8000' },
};

export default defineConfig({
  server: { proxy: pythonServer },
  preview: { proxy: pythonServer },
});
