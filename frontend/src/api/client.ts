/**
 * axios 인스턴스 — 모든 API 호출은 이 클라이언트를 통과한다.
 *
 * - 인증은 httpOnly 쿠키(`ssel_token`) 이므로 `withCredentials: true` 가 필수다.
 * - 401 이면 auth 스토어를 비우고 `/login?redirect=<현재경로>` 로 보낸다.
 *   단, 부트스트랩용 `GET /auth/me` 는 `skipAuthRedirect: true` 로 호출되므로
 *   리다이렉트 루프가 생기지 않는다.
 */
import axios, { type AxiosError } from 'axios'

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** true 면 401 응답에서 로그인 페이지로 보내지 않는다 (`/auth/me` 부트스트랩용). */
    skipAuthRedirect?: boolean
  }
}

const client = axios.create({
  baseURL: '/api',
  withCredentials: true,
  timeout: 180_000, // OCR 업로드가 오래 걸릴 수 있다
  headers: { Accept: 'application/json' },
})

/** 동시에 여러 요청이 401 을 받아도 리다이렉트는 한 번만 */
let redirecting = false

client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status
    const skip = error.config?.skipAuthRedirect === true

    if (status === 401 && !skip && !redirecting) {
      redirecting = true
      try {
        // 순환 import 를 피하려고 필요한 순간에만 불러온다.
        const [{ default: router }, { useAuthStore }] = await Promise.all([
          import('@/router'),
          import('@/stores/auth'),
        ])
        const auth = useAuthStore()
        auth.user = null

        const current = router.currentRoute.value
        if (current.path !== '/login') {
          const redirect = current.fullPath
          await router.replace({
            path: '/login',
            query: redirect && redirect !== '/' ? { redirect } : {},
          })
        }
      } finally {
        redirecting = false
      }
    }

    return Promise.reject(error)
  },
)

export default client
