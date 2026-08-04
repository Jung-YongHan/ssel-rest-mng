import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { VitePWA } from 'vite-plugin-pwa'

// 테마 색(인디고) — index.html / PWA manifest / Vuetify 테마와 동일하게 유지한다.
const THEME_COLOR = '#3F51B5'

export default defineConfig({
  plugins: [
    vue(),
    // Vuetify 컴포넌트 자동 import + 스타일 트리셰이킹
    vuetify({ autoImport: true }),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png'],
      manifest: {
        name: '연구실 선결제 관리',
        short_name: '선결제',
        description: '연구실 식당 선결제 잔액을 기록하고 관리합니다.',
        lang: 'ko',
        dir: 'ltr',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#FFFFFF',
        theme_color: THEME_COLOR,
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff,woff2,ttf,eot}'],
        cleanupOutdatedCaches: true,
        navigateFallback: 'index.html',
        // API 응답은 절대 캐시/오프라인 셸로 대체하지 않는다.
        navigateFallbackDenylist: [/^\/api/],
      },
      devOptions: { enabled: false },
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: false,
    // host: true → LAN 의 휴대폰에서 http://<PC-IP>:5173 으로 접속 가능
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // FastAPI 의 trailing-slash 307 리다이렉트가 백엔드 주소로 새지 않도록
        // Location 헤더를 프록시 호스트로 고쳐 쓴다.
        autoRewrite: true,
      },
    },
  },
  // 빌드 결과는 dist/ (FastAPI 가 그대로 서빙한다)
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
})
