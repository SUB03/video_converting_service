import { defineConfig } from 'vite'
import { devtools } from '@tanstack/devtools-vite'

import { tanstackStart } from '@tanstack/react-start/plugin/vite'

import viteReact from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { nitro } from 'nitro/vite'

// FastAPI video_converter_service; /api/videos -> http://localhost:8000/videos
const API_URL = process.env.API_URL ?? 'http://localhost:8000'

const config = defineConfig({
  resolve: { tsconfigPaths: true },
  plugins: [
    devtools(),
    nitro({
      rollupConfig: { external: [/^@sentry\//] },
      routeRules: { '/api/**': { proxy: `${API_URL}/**` } },
    }),
    tailwindcss(),
    tanstackStart(),
    viteReact(),
  ],
})

export default config
