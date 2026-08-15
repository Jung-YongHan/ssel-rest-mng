import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { VitePWA } from 'vite-plugin-pwa'

// 브랜드 색 — index.html / PWA manifest / main.ts 의 primary 와 동일하게 유지한다.
const THEME_COLOR = '#234E9E'

export default defineConfig({
  plugins: [
    vue(),
    // Vuetify 컴포넌트 자동 import + 스타일 트리셰이킹
    vuetify({ autoImport: true }),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'apple-touch-icon-v2.png'],
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
        // 경로는 절대(/로 시작)로 쓴다. 상대 경로는 manifest 기준으로 풀리는데
        // 일부 브라우저가 문서 URL 기준으로 잘못 푸는 사례가 있다.
        //
        // ⚠️ 아이콘 그림을 바꿀 때는 파일 내용만 갈아끼우지 말고 -vN 을 올릴 것.
        //    iOS 는 홈 화면 아이콘을 URL 단위로 캐시해서, 같은 이름이면
        //    Safari 데이터를 지워도 예전 아이콘(또는 실패 결과)을 계속 쓴다.
        // purpose 를 생략하면 규격상 'any' 지만, iOS 는 'any' 가 명시된 아이콘을
        // 고르는 쪽이 확실하다. maskable 만 있는 목록은 홈 화면 아이콘 선택에서
        // 통째로 건너뛸 수 있으므로 'any' 를 반드시 함께 둔다.
        icons: [
          {
            src: '/pwa-192x192-v2.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any',
          },
          {
            src: '/pwa-512x512-v2.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any',
          },
          {
            // macOS Safari / iOS 26 Liquid Glass 용 대형 아이콘
            src: '/apple-touch-icon-1024.png',
            sizes: '1024x1024',
            type: 'image/png',
            purpose: 'any',
          },
          {
            // maskable 은 런처가 원/스퀘어클 등 임의 모양으로 잘라낸다.
            // 투명 모서리가 있으면 잘린 자리가 검게 보이므로 불투명 사본을 쓴다.
            src: '/pwa-512x512-maskable-v2.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // 본문 폰트(Pretendard)는 웨이트당 ~750KB 라 프리캐시에 넣으면 설치가 무거워진다.
        // 서비스워커는 첫 화면에 필요한 것만 미리 받고, 폰트는 런타임 캐시에 맡긴다.
        globPatterns: ['**/*.{js,css,html,ico,png,svg}'],
        cleanupOutdatedCaches: true,
        navigateFallback: 'index.html',
        // API 응답은 절대 캐시/오프라인 셸로 대체하지 않는다.
        // icon-test.html 은 서비스워커의 영향을 받지 않아야 대조군이 된다.
        navigateFallbackDenylist: [/^\/api/, /^\/icon-test\d*\.html$/],
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.destination === 'font',
            handler: 'CacheFirst',
            options: {
              cacheName: 'ssel-fonts',
              expiration: { maxEntries: 12, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
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
