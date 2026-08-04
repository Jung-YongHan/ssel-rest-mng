/**
 * 전역 스낵바 + 서버 설정 스토어 (CONTRACT §5.5).
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

  return {
    ocrEnabled,
    lowBalanceThreshold,
    healthLoaded,
    snackbar,
    snackbarMessage,
    snackbarColor,
    toastKey,
    loadHealth,
    toast,
  }
})
