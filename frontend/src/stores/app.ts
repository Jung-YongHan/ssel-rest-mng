/**
 * 전역 스낵바 + 서버 설정 + 앱 업데이트·홈 화면 설치 안내 스토어 (CONTRACT §5.5).
 *
 * 페이지는 자체 스낵바를 만들지 말고 `useAppStore().toast(...)` 만 호출한다.
 * 실제 렌더는 `App.vue` 의 단일 `<v-snackbar>` 가 담당한다.
 */
import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { healthApi } from '@/api/endpoints'

export type ToastColor = 'success' | 'error' | 'info' | 'warning'

/** 서버가 응답하지 않을 때 쓰는 기본값 (.env 의 LOW_BALANCE_THRESHOLD 기본값과 동일) */
const DEFAULT_LOW_BALANCE_THRESHOLD = 30_000

/**
 * 새 버전 확인 주기.
 *
 * 홈 화면에 추가한 PWA 에는 주소창도 새로고침 버튼도 없어서, 앱이 스스로
 * 확인하지 않으면 사용자가 배포를 받을 방법이 사실상 없다. 화면이 보일 때만
 * 돈다(백그라운드 타이머는 iOS 에서 어차피 멈춘다).
 */
const UPDATE_CHECK_INTERVAL_MS = 30 * 60 * 1000

/* ── 홈 화면 설치 안내 (모듈 스코프) ──────────────────────────────
   `beforeinstallprompt` 는 페이지 로드 직후, 앱 마운트보다 먼저 올 수 있다.
   이 모듈은 App.vue 가 정적 import 하므로 마운트 전에 평가된다 — 여기서
   잡아야 이벤트를 놓치지 않는다. (SW 등록을 앱이 직접 하는 vite.config.ts
   `injectRegister: null` 과 같은 이유로, 설치 흐름도 이 스토어가 소유한다) */

/** 안내를 닫은 뒤(방식 불문) 이 기간은 다시 묻지 않는다 */
const INSTALL_SNOOZE_KEY = 'ssel.installSnoozedAt'
const INSTALL_SNOOZE_MS = 7 * 24 * 60 * 60 * 1000

let deferredInstallPrompt: BeforeInstallPromptEvent | null = null
/** 판정 시점에 이벤트가 아직 안 왔을 때 걸어 두는 콜백 — 늦게 와도 안내를 연다 */
let onInstallPromptAvailable: (() => void) | null = null

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    // 크롬 기본 미니 인포바 대신 우리 다이얼로그로 안내한다
    e.preventDefault()
    deferredInstallPrompt = e
    onInstallPromptAvailable?.()
  })
  window.addEventListener('appinstalled', () => {
    // 설치가 끝났으니 안내할 자격이 사라진다
    deferredInstallPrompt = null
    onInstallPromptAvailable = null
  })
}

/** 홈 화면 앱으로 실행 중이면 안내할 이유가 없다 */
function isStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  )
}

/** iPadOS 13+ 는 UA 를 MacIntel 로 위장하므로 터치 지점 수로 가른다 */
function isIosBrowser(): boolean {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  )
}

/** 인앱 브라우저에는 '홈 화면에 추가' 경로가 없다 — 안내해도 따라할 수 없다 */
const IN_APP_UA = /KAKAOTALK|NAVER|Instagram|FBAN|FBAV|Line\//i

export const useAppStore = defineStore('app', () => {
  // ── 서버 설정 (GET /api/health) ──
  const ocrEnabled = ref(false)
  const lowBalanceThreshold = ref(DEFAULT_LOW_BALANCE_THRESHOLD)
  const healthLoaded = ref(false)

  // ── 스낵바 ──
  const snackbar = ref(false)
  const snackbarMessage = ref('')
  const snackbarColor = ref<ToastColor>('info')
  /** 같은 문구를 연달아 띄워도 다시 보이도록 `<v-snackbar :key>` 에 쓰는 카운터 */
  const toastKey = ref(0)

  async function loadHealth(): Promise<void> {
    try {
      const health = await healthApi.get()
      ocrEnabled.value = health.ocr_enabled === true
      if (typeof health.low_balance_threshold === 'number') {
        lowBalanceThreshold.value = health.low_balance_threshold
      }
    } catch {
      // health 는 부가 정보다 — 실패해도 앱은 그대로 동작해야 한다.
    } finally {
      healthLoaded.value = true
    }
  }

  function toast(message: string, color: ToastColor = 'info'): void {
    snackbarMessage.value = message
    snackbarColor.value = color
    toastKey.value += 1
    snackbar.value = true
  }

  /* ── 앱 업데이트 (서비스워커) ───────────────────────────────────
     vite.config.ts 의 registerType 이 'prompt' 라, 새 서비스워커는 설치만 하고
     `waiting` 상태로 멈춘다. 그동안 화면은 옛 버전 그대로 안전하게 돌아간다.
     사용자가 받아들이면 그때 교체한다. */

  /** 새 버전이 설치를 마치고 교체를 기다리는 중 */
  const updateReady = ref(false)
  let registration: ServiceWorkerRegistration | null = null
  let checkTimer: ReturnType<typeof setInterval> | null = null

  /** `installing` 워커가 설치를 마치면 알림 상태를 세운다. */
  function watchInstalling(worker: ServiceWorker | null): void {
    if (!worker) return
    worker.addEventListener('statechange', () => {
      // controller 가 이미 있다는 것은 첫 설치가 아니라 '교체'라는 뜻이다.
      // 첫 방문에서 배너를 띄우면 안 된다.
      if (worker.state === 'installed' && navigator.serviceWorker.controller) {
        updateReady.value = true
      }
    })
  }

  /** 서버에 새 서비스워커가 있는지 물어본다 (없으면 아무 일도 없다). */
  function checkForUpdate(): void {
    void registration?.update().catch(() => {
      // 오프라인이면 그냥 실패한다 — 다음 기회에 다시 확인한다.
    })
  }

  /**
   * 서비스워커를 등록하고, 앱이 다시 보일 때마다 새 버전을 확인한다.
   * `App.vue` 가 마운트될 때 한 번만 호출한다.
   */
  async function initAppUpdates(): Promise<void> {
    if (!('serviceWorker' in navigator)) return
    try {
      registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
    } catch {
      // 서비스워커를 못 쓰는 환경(일부 인앱 브라우저 등)에서는 조용히 넘어간다.
      return
    }

    // 지난번에 받아 두고 아직 적용하지 않은 버전이 있을 수 있다.
    if (registration.waiting && navigator.serviceWorker.controller) updateReady.value = true
    watchInstalling(registration.installing)
    registration.addEventListener('updatefound', () => watchInstalling(registration!.installing))

    // 앱으로 돌아올 때마다 확인한다 — PWA 는 앱 전환 시 페이지를 다시 읽지 않고
    // 재개(resume)만 하므로, 이게 없으면 완전히 종료했다 켤 때까지 갱신되지 않는다.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return
      // '나중에' 로 닫았어도 다시 들어오면 한 번 더 알린다 ('영영 안 함'이 아니다).
      if (registration?.waiting && navigator.serviceWorker.controller) updateReady.value = true
      checkForUpdate()
    })

    checkTimer ??= setInterval(() => {
      if (document.visibilityState === 'visible') checkForUpdate()
    }, UPDATE_CHECK_INTERVAL_MS)

    checkForUpdate()
  }

  /** 대기 중인 새 버전으로 교체하고 화면을 다시 그린다. */
  function applyUpdate(): void {
    const waiting = registration?.waiting
    if (!waiting) {
      window.location.reload()
      return
    }
    // 교체가 끝나야(controllerchange) 새 프리캐시에서 읽어 온다. 그전에 새로고침하면
    // 옛 에셋이 그대로 나온다.
    navigator.serviceWorker.addEventListener(
      'controllerchange',
      () => window.location.reload(),
      { once: true },
    )
    waiting.postMessage({ type: 'SKIP_WAITING' })
  }

  /* ── 홈 화면 설치 안내 ──────────────────────────────────────────
     로그인한 모바일 화면에서 즉시 한 번 안내한다. Android(크롬 계열)는
     네이티브 설치 창을 띄울 수 있고, iOS 는 자동 설치 API 가 없어
     공유 → '홈 화면에 추가' 단계를 안내한다. */

  /** 설치 안내 다이얼로그 표시 여부 (App.vue 의 v-dialog 가 바인딩) */
  const installGuideOpen = ref(false)
  /** 어떤 안내를 그릴지 — 여는 시점에 결정한다 */
  const installPlatform = ref<'android' | 'ios' | null>(null)
  /** 페이지 로드(세션)당 한 번만 시도한다 */
  let installGuideRequested = false

  function installSnoozed(): boolean {
    try {
      const at = Number(localStorage.getItem(INSTALL_SNOOZE_KEY) ?? 0)
      return Date.now() - at < INSTALL_SNOOZE_MS
    } catch {
      return true // 저장소를 못 쓰는 환경에선 매번 뜨는 쪽보다 안 뜨는 쪽이 낫다
    }
  }

  function openInstallGuide(platform: 'android' | 'ios'): void {
    installPlatform.value = platform
    installGuideOpen.value = true
  }

  /** 로그인 후 모바일 화면에서 App.vue 가 호출한다. 조건이 안 되면 조용히 무시. */
  function maybeShowInstallGuide(): void {
    if (installGuideRequested) return
    installGuideRequested = true
    if (isStandalone() || installSnoozed()) return
    if (updateReady.value) return // 업데이트 안내가 떠 있으면 이번 세션은 양보한다
    if (deferredInstallPrompt) {
      openInstallGuide('android')
    } else if (isIosBrowser() && !IN_APP_UA.test(navigator.userAgent)) {
      openInstallGuide('ios')
    } else {
      // 크롬 계열은 beforeinstallprompt 가 이 판정보다 늦게 올 수 있다 — 오면 그때 연다.
      // 이벤트가 아예 없는 브라우저(삼성 인터넷·파폭·인앱)는 콜백이 불리지 않아
      // 조용히 끝난다. 따라할 수 없는 안내를 띄우는 것보다 침묵이 낫다.
      onInstallPromptAvailable = () => {
        onInstallPromptAvailable = null
        if (isStandalone() || installSnoozed() || updateReady.value) return
        openInstallGuide('android')
      }
    }
  }

  /** 안드로이드: 브라우저 네이티브 설치 프롬프트를 띄운다 */
  async function promptInstall(): Promise<void> {
    const deferred = deferredInstallPrompt
    installGuideOpen.value = false
    if (!deferred) return
    deferredInstallPrompt = null // prompt() 는 이벤트당 한 번만 허용된다
    try {
      await deferred.prompt()
      await deferred.userChoice
    } catch {
      // 이미 소비된 이벤트 등 — 스누즈가 끝나면 다시 안내된다
    }
  }

  // 어떤 방식으로 닫히든(나중에·스크림 탭·ESC·설치) 스누즈를 기록한다.
  // '나중에'만 기록하면 스크림 탭으로 닫은 사용자가 매번 다시 보게 된다.
  watch(installGuideOpen, (open) => {
    if (open) return
    try {
      localStorage.setItem(INSTALL_SNOOZE_KEY, String(Date.now()))
    } catch {
      /* 시크릿 모드 등 저장 실패는 무시 */
    }
  })

  return {
    ocrEnabled,
    lowBalanceThreshold,
    healthLoaded,
    snackbar,
    snackbarMessage,
    snackbarColor,
    toastKey,
    updateReady,
    installGuideOpen,
    installPlatform,
    loadHealth,
    toast,
    initAppUpdates,
    applyUpdate,
    maybeShowInstallGuide,
    promptInstall,
  }
})
