/**
 * 전역 스낵바 + 서버 설정 + 앱 업데이트 스토어 (CONTRACT §5.5).
 *
 * 페이지는 자체 스낵바를 만들지 말고 `useAppStore().toast(...)` 만 호출한다.
 * 실제 렌더는 `App.vue` 의 단일 `<v-snackbar>` 가 담당한다.
 */
import { ref } from 'vue'
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

  return {
    ocrEnabled,
    lowBalanceThreshold,
    healthLoaded,
    snackbar,
    snackbarMessage,
    snackbarColor,
    toastKey,
    updateReady,
    loadHealth,
    toast,
    initAppUpdates,
    applyUpdate,
  }
})
