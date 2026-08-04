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

/** 링크(`<a href>`)로 바로 내려받을 수 있게 절대 경로 쿼리스트링을 만든다. */
function queryString(params?: Params): string {
  const cleaned = clean(params)
  if (!cleaned) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(cleaned)) search.append(key, String(value))
  return search.toString()
}

// ── 인증 ────────────────────────────────────────────────────────

export const authApi = {
  async register(body: {
    email: string
    name: string
    password: string
    invite_code: string
  }): Promise<UserOut> {
    const { data } = await client.post<UserOut>('/auth/register', body)
    return data
  },

  async login(body: { email: string; password: string }): Promise<UserOut> {
    const { data } = await client.post<UserOut>('/auth/login', body)
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

  /** CSV 내려받기 링크 (절대 경로 → `<a :href>` 로 바로 다운로드) */
  exportCsvUrl(params?: TransactionQuery): string {
    const qs = queryString(params as Params | undefined)
    return qs ? `/api/transactions/export.csv?${qs}` : '/api/transactions/export.csv'
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

  return '서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.'
}

/** 서버가 409 로 음수잔액을 거부했는지 (→ 확인 모달 후 `allow_negative: true` 로 재요청) */
export function isInsufficientBalance(e: unknown): boolean {
  const error = e as AxiosError<ErrorBody> | undefined
  if (error?.response?.status !== 409) return false
  const detail = extractDetail(error.response?.data?.detail) ?? ''
  return detail.includes('잔액')
}
