import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { VitePWA } from 'vite-plugin-pwa'

// 브랜드 색 — index.html / PWA manifest / main.ts 의 primary 와 동일하게 유지한다.
const THEME_COLOR = '#234E9E'

// manifest.webmanifest 를 SW 프리캐시에서 뺀다. registerType 'prompt' 는 사용자가
// '업데이트'를 누르기 전까지 옛 프리캐시를 유지하는데, iOS 는 홈 화면 추가 때
// 서비스워커 캐시를 거쳐 manifest 를 읽으므로(7ad89ad) 프리캐시에 있으면 갓 배포한
// 아이콘·설정이 기기에 영영 닿지 않는다. 프리캐시에서 빠지면 요청이 네트워크로
// 통과하고, 서버가 no-cache 를 붙이므로(main.py SHELL_FILES) 항상 최신을 받는다.
// workbox 의 manifestTransforms 로는 못 뺀다 — vite-plugin-pwa 가 manifest 엔트리를
// 밀어 넣는 additionalManifestEntries 는 transforms 가 끝난 **뒤에** 합쳐진다.
const pwa = VitePWA({
  // 'autoUpdate' 는 새 서비스워커가 곧바로 skipWaiting + clientsClaim 을 한다.
  // 그러면 이미 떠 있는 화면이 옛 JS 를 돌리는 채로 프리캐시만 새것으로 바뀌어,
  // 그 뒤에 다른 탭(lazy import)으로 넘어가면 사라진 청크를 요청하다 죽는다.
  // 'prompt' 는 사용자가 받아들일 때까지 옛 버전을 온전히 유지한다.
  registerType: 'prompt',
  // 등록은 stores/app.ts 가 직접 한다 (갱신 확인·안내를 앱이 제어해야 하므로).
  // 여기서 registerSW.js 를 심으면 등록이 두 번 일어난다.
  injectRegister: null,
  includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'apple-touch-icon-v2.png'],
  manifest: {
    name: '연구실 선결제 관리',
    short_name: '연구실 선결제 관리',
    description: '연구실 식당 선결제 잔액을 기록하고 관리합니다.',
    lang: 'ko',
    dir: 'ltr',
    start_url: '/',
    scope: '/',
    // 없으면 크롬이 start_url 로 정체성을 유도한다 — 주소가 바뀌어도 같은 앱으로 남게 명시
    id: '/',
    display: 'standalone',
    orientation: 'portrait',
    // 스플래시 배경(index.html --splash-bg)·main.ts 라이트 background 와 동일하게 —
    // 흰색이면 실행 순간 스플래시 톤과 어긋나 흰 플래시가 보인다.
    background_color: '#F5F6F8',
    theme_color: THEME_COLOR,
    // 진단 실험(HANDOFF §4-6): 아이콘이 정상 동작하는 대조 사이트와 선언 모양을
    // 동일하게 맞췄다 — 2개(192/512)·상대 경로·purpose 'any maskable' 결합.
    // (원래는 절대 경로 + purpose 분리 + 1024 포함이었다. 1024/maskable-v2 파일은
    //  기기에 캐시된 옛 manifest 가 참조하므로 디스크에는 남긴다)
    //
    // ⚠️ 아이콘 그림을 바꿀 때는 파일 내용만 갈아끼우지 말고 -vN 을 올릴 것.
    //    iOS 는 홈 화면 아이콘을 URL 단위로 캐시해서, 같은 이름이면
    //    Safari 데이터를 지워도 예전 아이콘(또는 실패 결과)을 계속 쓴다.
    // ⚠️ 아이콘은 반드시 불투명 풀블리드로. 알파가 있으면 iOS 가 검정으로
    //    합성하거나 글자 타일로 폴백한다 (-v2 가 투명 모서리 때문에 그랬다).
    icons: [
      {
        src: 'pwa-192x192-v5.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'any maskable',
      },
      {
        src: 'pwa-512x512-v5.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any maskable',
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
    navigateFallbackDenylist: [/^\/api/],
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
})

const pwaApi = pwa.find((p) => p.name === 'vite-plugin-pwa')?.api

export default defineConfig({
  plugins: [
    vue(),
    // Vuetify 컴포넌트 자동 import + 스타일 트리셰이킹
    vuetify({ autoImport: true }),
    pwa,
    {
      // 위 주석 참조 — 프리캐시 엔트리는 configResolved 에서 확정되고 SW 는
      // closeBundle 에서 생성되므로, 그 사이(buildStart)에 걸러낸다.
      name: 'ssel:manifest-no-precache',
      buildStart() {
        pwaApi?.extendManifestEntries((entries) =>
          entries.filter((e) => (typeof e === 'string' ? e : e.url) !== 'manifest.webmanifest'),
        )
      },
    },
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
