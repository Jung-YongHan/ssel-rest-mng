/**
 * 페이지가 쓰는 **유일한 API 표면** (CONTRACT §5.3).
 *
 * 페이지에서 axios 를 직접 쓰지 말고 항상 여기 함수를 쓴다.
 * 에러는 `appStore.toast(errorMessage(e), 'error')` 로 노출한다.
 */
import type { AxiosError, AxiosProgressEvent } from 'axios'

import client from './client'
import type {
  ConfirmIn,
  ConfirmOut,
  HealthOut,
  MonthlyOut,
  ReceiptUploadOut,
  RestaurantCreateIn,
  RestaurantDetail,
  RestaurantListOut,
  RestaurantStatRow,
  RestaurantUpdateIn,
  SummaryOut,
  TransactionCreateIn,
  TransactionCreateOut,
  TransactionListOut,
  TransactionQuery,
  UserOut,
  UserStatRow,
} from './types'

export type { TransactionQuery } from './types'

// ── 내부 유틸 ───────────────────────────────────────────────────

type Params = Record<string, unknown>

/** undefined/null/빈문자 파라미터는 아예 보내지 않는다 (서버 기본값을 존중). */
function clean(params?: Params): Params | undefined {
  if (!params) return undefined
  const out: Params = {}
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    out[key] = value
  }
  return Object.keys(out).length ? out : undefined
}

// ── 파일 내려받기 ───────────────────────────────────────────────

/** 파일을 사용자에게 넘긴 결과 (페이지가 안내 문구를 고르는 데 쓴다). */
export type DownloadResult = 'shared' | 'downloaded' | 'cancelled'

/** 서버가 `Content-Disposition` 으로 준 파일명을 뽑는다 (없으면 fallback). */
function filenameFrom(disposition: unknown, fallback: string): string {
  if (typeof disposition !== 'string') return fallback
  const encoded = /filename\*=\s*UTF-8''([^;]+)/i.exec(disposition)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1])
    } catch {
      /* 잘못 인코딩된 헤더는 무시하고 아래 plain 형식을 본다 */
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1].trim() : fallback
}

/**
 * iOS/iPadOS 인지. 여기서만 UA 를 본다.
 *
 * 기능 감지로는 구분할 수 없는 **동작 차이**를 다루기 때문이다: 다른 플랫폼은
 * 파일을 내려받아도 보던 화면에 그대로 남지만, iOS 는 문서 미리보기가 화면을
 * 덮으면서 뒤로가기·닫기를 주지 않아 앱으로 돌아올 수단이 사라진다.
 * (iPadOS 는 데스크톱 UA 를 보내므로 터치 지원 여부로 한 번 더 거른다)
 */
function isIosLike(): boolean {
  const ua = navigator.userAgent
  if (/iPad|iPhone|iPod/.test(ua)) return true
  return ua.includes('Macintosh') && navigator.maxTouchPoints > 1
}

/**
 * 받은 파일을 사용자에게 넘긴다.
 *
 * iOS 에서는 공유 시트를 먼저 쓴다 — 시트에는 항상 '취소'가 있어 어떤 경우에도
 * 원래 화면으로 돌아올 수 있다. 그 외 플랫폼은 평소대로 blob 링크로 내려받는다
 * (데스크톱에서 공유 시트를 띄우면 오히려 낯설다).
 */
async function saveFile(blob: Blob, filename: string): Promise<DownloadResult> {
  const file = new File([blob], filename, {
    type: blob.type || 'application/octet-stream',
  })

  const canShareFile =
    typeof navigator.canShare === 'function' && navigator.canShare({ files: [file] })
  if (isIosLike() && canShareFile) {
    try {
      await navigator.share({ files: [file] })
      return 'shared'
    } catch (e) {
      // 사용자가 시트를 닫은 것뿐이면 다운로드로 다시 밀어붙이지 않는다.
      if ((e as DOMException | undefined)?.name === 'AbortError') return 'cancelled'
      // 사용자 제스처 만료(NotAllowedError) 등은 아래 다운로드로 넘어간다.
    }
  }

  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  // 사파리는 클릭 직후 revoke 하면 내려받기가 취소된다 → 넉넉히 미뤄서 해제한다.
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
  return 'downloaded'
}

// ── 인증 ────────────────────────────────────────────────────────

export const authApi = {
  async register(body: {
    email: string
    name: string
    password: string
    invite_code: string
  }): Promise<UserOut> {
    // 네트워크가 끊겨 요청이 서버까지 못 간 경우 한 번 다시 보낸다.
    // 중복으로 도착해도 서버가 409(이미 등록된 이메일)로 막으므로 안전하다.
    const { data } = await client.post<UserOut>('/auth/register', body, {
      retryOnNetworkError: true,
    })
    return data
  },

  async login(body: { email: string; password: string }): Promise<UserOut> {
    // 로그인은 멱등이라 재시도해도 부수효과가 없다.
    const { data } = await client.post<UserOut>('/auth/login', body, {
      retryOnNetworkError: true,
    })
    return data
  },

  async logout(): Promise<void> {
    await client.post('/auth/logout')
  },

  async me(): Promise<UserOut> {
    // 부트스트랩 호출: 401 이어도 리다이렉트하지 않는다 (라우터 가드가 판단).
    const { data } = await client.get<UserOut>('/auth/me', { skipAuthRedirect: true })
    return data
  },
}

// ── 식당 ────────────────────────────────────────────────────────

export const restaurantApi = {
  async list(params?: {
    query?: string
    sort?: string
    include_archived?: boolean
    low_only?: boolean
  }): Promise<RestaurantListOut> {
    const { data } = await client.get<RestaurantListOut>('/restaurants', { params: clean(params) })
    return data
  },

  async get(id: number): Promise<RestaurantDetail> {
    const { data } = await client.get<RestaurantDetail>(`/restaurants/${id}`)
    return data
  },

  async create(body: RestaurantCreateIn): Promise<RestaurantDetail> {
    const { data } = await client.post<RestaurantDetail>('/restaurants', body)
    return data
  },

  async update(id: number, body: RestaurantUpdateIn): Promise<RestaurantDetail> {
    const { data } = await client.patch<RestaurantDetail>(`/restaurants/${id}`, body)
    return data
  },

  async transactions(
    id: number,
    params?: { limit?: number; offset?: number; include_voided?: boolean },
  ): Promise<TransactionListOut> {
    const { data } = await client.get<TransactionListOut>(`/restaurants/${id}/transactions`, {
      params: clean(params),
    })
    return data
  },
}

// ── 영수증 ──────────────────────────────────────────────────────

export const receiptApi = {
  async upload(file: File, onProgress?: (pct: number) => void): Promise<ReceiptUploadOut> {
    const form = new FormData()
    form.append('file', file)
    const { data } = await client.post<ReceiptUploadOut>('/receipts', form, {
      onUploadProgress: (event: AxiosProgressEvent) => {
        if (!onProgress) return
        const total = event.total ?? file.size
        if (!total) return
        onProgress(Math.min(100, Math.round((event.loaded / total) * 100)))
      },
    })
    return data
  },

  async get(id: number): Promise<ReceiptUploadOut> {
    const { data } = await client.get<ReceiptUploadOut>(`/receipts/${id}`)
    return data
  },

  async reocr(id: number): Promise<ReceiptUploadOut> {
    const { data } = await client.post<ReceiptUploadOut>(`/receipts/${id}/reocr`)
    return data
  },

  async confirm(id: number, body: ConfirmIn): Promise<ConfirmOut> {
    const { data } = await client.post<ConfirmOut>(`/receipts/${id}/confirm`, body)
    return data
  },

  /** `<img :src>` 에 그대로 넣는다 (쿠키 인증이므로 별도 헤더 불필요). */
  imageUrl(id: number): string {
    return `/api/receipts/${id}/image`
  },
}

// ── 거래 ────────────────────────────────────────────────────────

export const transactionApi = {
  async list(params?: TransactionQuery): Promise<TransactionListOut> {
    const { data } = await client.get<TransactionListOut>('/transactions', {
      params: clean(params as Params | undefined),
    })
    return data
  },

  async create(body: TransactionCreateIn): Promise<TransactionCreateOut> {
    const { data } = await client.post<TransactionCreateOut>('/transactions', body)
    return data
  },

  /** 기록 취소(void) — 사유 필수 */
  async void_(id: number, reason: string): Promise<TransactionCreateOut> {
    const { data } = await client.post<TransactionCreateOut>(`/transactions/${id}/void`, { reason })
    return data
  },

  /**
   * 현재 필터 그대로 CSV 를 받아 사용자에게 넘긴다.
   *
   * 링크로 곧장 이동시키지 않는다 — iOS 는 그 순간 앱 화면을 문서 미리보기로
   * 덮어 버리고 돌아올 수단을 주지 않는다. 본문을 먼저 받아 두고 공유 시트
   * (없으면 blob 다운로드)로 넘긴다.
   */
  async exportCsv(params?: TransactionQuery): Promise<DownloadResult> {
    const { data, headers } = await client.get<Blob>('/transactions/export.csv', {
      params: clean(params as Params | undefined),
      responseType: 'blob',
      headers: { Accept: 'text/csv' },
    })
    return saveFile(data, filenameFrom(headers['content-disposition'], 'transactions.csv'))
  },
}

// ── 통계 ────────────────────────────────────────────────────────

export const statsApi = {
  async summary(): Promise<SummaryOut> {
    const { data } = await client.get<SummaryOut>('/stats/summary')
    return data
  },

  async monthly(months?: number): Promise<MonthlyOut> {
    const { data } = await client.get<MonthlyOut>('/stats/monthly', { params: clean({ months }) })
    return data
  },

  async byRestaurant(p?: {
    date_from?: string
    date_to?: string
  }): Promise<{ items: RestaurantStatRow[] }> {
    const { data } = await client.get<{ items: RestaurantStatRow[] }>('/stats/by-restaurant', {
      params: clean(p),
    })
    return data
  },

  async byUser(p?: { date_from?: string; date_to?: string }): Promise<{ items: UserStatRow[] }> {
    const { data } = await client.get<{ items: UserStatRow[] }>('/stats/by-user', {
      params: clean(p),
    })
    return data
  },
}

// ── 관리 (admin 전용) ───────────────────────────────────────────

export const adminApi = {
  async users(): Promise<UserOut[]> {
    const { data } = await client.get<UserOut[]>('/admin/users')
    return data
  },

  async updateUser(
    id: number,
    body: { name?: string; role?: string; is_active?: boolean; password?: string },
  ): Promise<UserOut> {
    const { data } = await client.patch<UserOut>(`/admin/users/${id}`, body)
    return data
  },

  async inviteCode(): Promise<{ invite_code: string }> {
    const { data } = await client.get<{ invite_code: string }>('/admin/invite-code')
    return data
  },
}

// ── 메타 ────────────────────────────────────────────────────────

export const healthApi = {
  async get(): Promise<HealthOut> {
    const { data } = await client.get<HealthOut>('/health')
    return data
  },
}

// ── 에러 해석 ───────────────────────────────────────────────────

type ErrorBody = { detail?: unknown }

/** FastAPI 의 `detail` 을 문자열로 뽑아낸다 (422 검증 에러 배열도 처리). */
function extractDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail.trim() || null
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item) return String((item as { msg: unknown }).msg)
        return ''
      })
      .filter(Boolean)
    return messages.length ? messages.join('\n') : null
  }
  if (detail && typeof detail === 'object' && 'msg' in detail) {
    return String((detail as { msg: unknown }).msg) || null
  }
  return null
}

/** axios 에러 → 사용자에게 보여줄 한국어 메시지 */
export function errorMessage(e: unknown): string {
  const error = e as AxiosError<ErrorBody> | undefined

  const detail = extractDetail(error?.response?.data?.detail)
  if (detail) return detail

  const status = error?.response?.status
  if (status === 401) return '로그인이 필요합니다. 다시 로그인해 주세요.'
  if (status === 403) return '권한이 없습니다.'
  if (status === 404) return '요청한 정보를 찾을 수 없습니다.'
  if (status === 413) return '파일이 너무 큽니다. 더 작은 이미지를 사용해 주세요.'
  if (status === 429) return '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.'
  if (status && status >= 500) return '서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'

  const code = error?.code
  if (code === 'ECONNABORTED' || code === 'ETIMEDOUT') {
    return '요청 시간이 초과되었습니다. 네트워크 상태를 확인하고 다시 시도해 주세요.'
  }

  // 여기까지 오면 응답 자체를 받지 못한 것이다. client.ts 가 이미 한 번
  // 다시 보내 본 뒤이므로, 사용자에게도 재시도를 권한다.
  return '서버에 연결하지 못했습니다. 네트워크 상태를 확인하고 다시 시도해 주세요.'
}

/** 서버가 409 로 음수잔액을 거부했는지 (→ 확인 모달 후 `allow_negative: true` 로 재요청) */
export function isInsufficientBalance(e: unknown): boolean {
  const error = e as AxiosError<ErrorBody> | undefined
  if (error?.response?.status !== 409) return false
  const detail = extractDetail(error.response?.data?.detail) ?? ''
  return detail.includes('잔액')
}
