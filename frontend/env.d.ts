/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

/**
 * `*.vue` 모듈 선언.
 *
 * vue-tsc 는 실제 `.vue` 파일을 직접 해석하므로 이 선언이 없어도 되지만,
 * 라우터가 **아직 만들어지지 않은 페이지**를 lazy import 하는 동안(병렬 작업)
 * 타입체크가 "모듈을 찾을 수 없음"으로 멈추지 않게 하려고 유지한다.
 * 페이지가 서로를 import 하지 않는다는 계약(CONTRACT §5.6) 덕분에 부작용은 없다.
 */
declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

/**
 * 크롬 계열 전용 `beforeinstallprompt` 이벤트 — 표준이 아니라 lib.dom 에 없다.
 * 홈 화면 설치 안내(stores/app.ts)가 쓴다.
 */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>
}

interface WindowEventMap {
  beforeinstallprompt: BeforeInstallPromptEvent
}
