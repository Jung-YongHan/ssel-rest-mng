/**
 * axios 인스턴스 — 모든 API 호출은 이 클라이언트를 통과한다.
 *
 * - 인증은 httpOnly 쿠키(`ssel_token`) 이므로 `withCredentials: true` 가 필수다.
 * - 401 이면 auth 스토어를 비우고 `/login?redirect=<현재경로>` 로 보낸다.
 *   단, 부트스트랩용 `GET /auth/me` 는 `skipAuthRedirect: true` 로 호출되므로
 *   리다이렉트 루프가 생기지 않는다.
 * - 응답을 아예 못 받은 요청은 한 번만 자동으로 다시 보낸다 (아래 주석 참고).
 */
import axios, { type AxiosError } from 'axios'

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** true 면 401 응답에서 로그인 페이지로 보내지 않는다 (`/auth/me` 부트스트랩용). */
    skipAuthRedirect?: boolean
    /**
     * 응답을 아예 못 받았을 때(네트워크 단절) 한 번만 자동 재시도한다.
     * GET/HEAD 는 이 값과 무관하게 항상 재시도하므로, **부수효과가 있는 요청 중
     * 중복 실행이 안전한 것**에만 켠다 (가입=중복이면 409, 로그인=멱등).
     */
    retryOnNetworkError?: boolean
    /**
     * 내부용 — 이미 한 번 다시 보냈다는 표시. 재시도는 요청당 한 번뿐이다.
     * axios 는 재요청마다 config 객체를 새로 만들지만(참조 비교 불가) 커스텀
     * 키는 그대로 옮겨 주므로, 플래그를 config 에 얹어야 무한 루프를 막을 수 있다.
     */
    networkRetryDone?: boolean
  }
}

const NETWORK_RETRY_DELAY_MS = 400

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
    const config = error.config
    const skip = config?.skipAuthRedirect === true

    // 응답이 아예 없는 실패 = 요청이 서버까지 가지 못했다.
    // 모바일 브라우저가 서버 쪽에서 이미 닫힌 keep-alive 커넥션에 요청을 실어
    // 보내면 이렇게 되는데, 브라우저는 POST 를 자동으로 다시 보내지 않는다
    // (실제로 iOS 인앱 브라우저에서 가입 요청이 ingress 로그에 아예 남지 않았다).
    // 여기서 한 번만 새 커넥션으로 다시 보낸다.
    const noResponse =
      !error.response && error.code !== 'ECONNABORTED' && error.code !== 'ERR_CANCELED'
    if (config && noResponse && !config.networkRetryDone) {
      const method = (config.method ?? 'get').toLowerCase()
      // 거래 생성처럼 중복 실행이 기록을 망치는 요청은 절대 자동 재시도하지 않는다.
      const safeToRetry =
        method === 'get' || method === 'head' || config.retryOnNetworkError === true
      if (safeToRetry) {
        config.networkRetryDone = true
        await new Promise((resolve) => setTimeout(resolve, NETWORK_RETRY_DELAY_MS))
        return client(config)
      }
    }

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
