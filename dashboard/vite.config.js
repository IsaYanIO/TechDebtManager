import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const dataDir = fileURLToPath(new URL('../data', import.meta.url));
const apiTarget = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000';

// В dev-режиме отдаём файлы пайплайна по /data/..., как это делает nginx в Docker.
function pipelineData() {
  return {
    name: 'techdebt-pipeline-data',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const requestPath = decodeURIComponent((req.url || '').split('?')[0]);
        const match = requestPath.match(/^\/data\/(.+)$/);
        if (!match) {
          next();
          return;
        }

        const file = path.resolve(dataDir, match[1]);
        const allowedRoot = path.resolve(dataDir) + path.sep;
        if (!file.startsWith(allowedRoot) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
          next();
          return;
        }

        res.setHeader(
          'Content-Type',
          file.endsWith('.json')
            ? 'application/json; charset=utf-8'
            : 'text/plain; charset=utf-8',
        );
        res.setHeader('Cache-Control', 'no-store');
        fs.createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), pipelineData()],
  server: {
    proxy: {
      // Локальный API: docker compose up -d api (порт 8000)
      '/api': {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
});
