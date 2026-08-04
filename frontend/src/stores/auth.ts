/**
 * 로그인 상태 스토어 (CONTRACT §5.5).
 *
 * 인증 토큰은 httpOnly 쿠키라서 프론트가 직접 읽을 수 없다. 따라서 앱 시작 시
 * `fetchMe()` 로 서버에 물어보고, 그 결과로 라우터 가드가 판단한다.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi } from '@/api/endpoints'
import type { UserOut } from '@/api/types'

export type RegisterBody = {
  email: string
  name: string
  password: string
  invite_code: string
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserOut | null>(null)
  /** 부트스트랩(`fetchMe`) 이 한 번 끝났는지 — 라우터 가드가 이 값을 기다린다. */
  const ready = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.role === 'admin')

  /** 동시 네비게이션이 겹쳐도 `/auth/me` 는 한 번만 호출한다. */
  let inflight: Promise<void> | null = null

  async function fetchMe(): Promise<void> {
    if (inflight) return inflight

    inflight = (async () => {
      try {
        user.value = await authApi.me()
      } catch {
        // 401(미로그인)/네트워크 오류 모두 '로그인 안 된 상태'로 취급한다.
        user.value = null
      } finally {
        // finally 에서 세워야 가드가 영원히 대기하지 않는다.
        ready.value = true
        inflight = null
      }
    })()

    return inflight
  }

  async function login(email: string, password: string): Promise<void> {
    user.value = await authApi.login({ email, password })
    ready.value = true
  }

  async function register(body: RegisterBody): Promise<void> {
    user.value = await authApi.register(body)
    ready.value = true
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } finally {
      user.value = null
      ready.value = true
    }
  }

  return { user, ready, isAuthenticated, isAdmin, fetchMe, login, register, logout }
})
