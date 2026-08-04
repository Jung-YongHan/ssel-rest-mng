/**
 * API 타입 — `docs/CONTRACT.md` §2 를 그대로 옮긴 것.
 *
 * 이 파일은 백엔드 응답의 단일 기준이다. 서버 스키마가 바뀌면 CONTRACT 를 먼저 고치고
 * 여기에 반영한다. 금액은 전부 **정수 원 단위**, 날짜/시간은 `...+00:00` ISO 문자열이다.
 */

// ── 인증 ────────────────────────────────────────────────────────

export type UserRole = 'admin' | 'member'

export type UserOut = {
  id: number
  email: string
  name: string
  role: 'admin' | 'member'
  is_active: boolean
  created_at: string
}

/** 기록의 '누가' — 이력 표시용 최소 정보 */
export type UserBrief = {
  id: number
  name: string
  email: string
}

// ── 식당 ────────────────────────────────────────────────────────

export type RestaurantSummary = {
  id: number
  name: string
  business_number: string | null
  address: string | null
  phone: string | null
  memo: string | null
  is_archived: boolean
  /** 현재 잔액 (음수 가능) */
  balance: number
  /** 누적 충전 */
  charge_total: number
  /** 누적 사용 */
  use_total: number
  /** 유효 거래 수 (void 제외) */
  tx_count: number
  last_used_at: string | null
  last_charged_at: string | null
  /** balance < LOW_BALANCE_THRESHOLD (음수 포함) */
  is_low_balance: boolean
  created_at: string
  updated_at: string
}

export type RestaurantDetail = RestaurantSummary & {
  /** 최근 20건 */
  recent_transactions: TransactionOut[]
}

export type RestaurantListOut = {
  items: RestaurantSummary[]
  total: number
  /** 전체 합계 (archived 제외) */
  total_balance: number
  low_balance_count: number
  low_balance_threshold: number
}

/**
 * 앱 도입 전 이미 선결제해둔 식당 백필용: `initial_balance` 를 주면
 * "초기 잔액 등록" 메모가 달린 CHARGE 거래를 함께 생성한다.
 */
export type RestaurantCreateIn = {
  /** 필수, 1~200자 */
  name: string
  /** 하이픈 허용, 서버가 숫자만 남김. 중복이면 409 */
  business_number?: string | null
  address?: string | null
  phone?: string | null
  memo?: string | null
  /** >=0, 기본 0. 0 이면 거래 생성 안 함 */
  initial_balance?: number
  /** 기본 "초기 잔액 등록" */
  initial_balance_memo?: string | null
  /** 기본 now */
  occurred_at?: string | null
}

/** 전부 optional */
export type RestaurantUpdateIn = {
  name?: string
  business_number?: string | null
  address?: string | null
  phone?: string | null
  memo?: string | null
  is_archived?: boolean
}

/** 식당 목록 정렬 (기본 balance_desc) */
export type RestaurantSort = 'balance_desc' | 'balance_asc' | 'name' | 'recent' | 'created'

// ── 영수증 ──────────────────────────────────────────────────────

export type ParsedReceipt = {
  store_name: string | null
  business_number: string | null
  address: string | null
  phone: string | null
  /** 부가세 포함 합계 */
  total_amount: number | null
  paid_at: string | null
}

export type ReceiptOut = {
  id: number
  /** "/api/receipts/{id}/image" */
  image_url: string
  ocr_status: 'pending' | 'done' | 'failed'
  ocr_error: string | null
  ocr_ms: number | null
  created_at: string
  consumed_at: string | null
  uploaded_by: UserBrief | null
}

export type MatchCandidate = {
  restaurant: RestaurantSummary
  score: number
  reason: 'business_number' | 'name'
}

export type MatchResult = {
  /** name 은 score>=88 자동확정 */
  matched_by: 'business_number' | 'name' | null
  /** 확정 매칭 */
  restaurant: RestaurantSummary | null
  /** 최대 5개, score 내림차순 */
  candidates: MatchCandidate[]
}

export type DuplicateInfo = {
  receipt_id: number
  transaction_id: number | null
  restaurant_name: string | null
  message: string
}

export type ReceiptUploadOut = {
  receipt: ReceiptOut
  parsed: ParsedReceipt
  match: MatchResult
  duplicate: DuplicateInfo | null
}

export type ConfirmIn = {
  action: 'register_and_charge' | 'charge' | 'use'
  /** charge/use 필수 */
  restaurant_id?: number | null
  /** register_and_charge 필수 */
  restaurant?: {
    name: string
    business_number?: string | null
    address?: string | null
    phone?: string | null
    memo?: string | null
  } | null
  /** register_and_charge/charge 필수, >0 */
  charge_amount?: number | null
  /** 선택, >=0. 0/null 이면 USE 거래 생성 안 함 */
  use_amount?: number | null
  /** 기본 parsed_paid_at ?? now */
  occurred_at?: string | null
  memo?: string | null
  /** 기본 false */
  allow_negative?: boolean
  /** 사용자가 화면에서 고친 값 → receipt 에 반영 저장 */
  parsed?: ParsedReceipt | null
}

export type ConfirmOut = {
  restaurant: RestaurantDetail
  /** 이번에 생성된 것 (CHARGE, USE 순) */
  transactions: TransactionOut[]
  balance_before: number
  balance_after: number
  /** 예: "잔액이 부족해 음수가 되었습니다." */
  warnings: string[]
}

// ── 거래 ────────────────────────────────────────────────────────

export type TransactionType = 'CHARGE' | 'USE' | 'ADJUST'

export type TransactionOut = {
  id: number
  restaurant_id: number
  restaurant_name: string
  type: 'CHARGE' | 'USE' | 'ADJUST'
  /** 항상 원본 (양수 또는 ADJUST 부호) */
  amount: number
  /** 잔액 반영값. void 면 0 */
  signed_amount: number
  occurred_at: string
  memo: string | null
  receipt_id: number | null
  has_receipt: boolean
  created_by: UserBrief | null
  created_at: string
  is_voided: boolean
  voided_at: string | null
  voided_by: UserBrief | null
  void_reason: string | null
}

export type TransactionListOut = {
  items: TransactionOut[]
  total: number
  limit: number
  offset: number
  /** void 제외, 필터 전체 기준 */
  sum_charge: number
  sum_use: number
  sum_adjust: number
}

export type TransactionCreateIn = {
  restaurant_id: number
  type: 'CHARGE' | 'USE' | 'ADJUST'
  /** CHARGE/USE: >0 / ADJUST: != 0 */
  amount: number
  /** 기본 now */
  occurred_at?: string | null
  memo?: string | null
  receipt_id?: number | null
  /** 기본 false */
  allow_negative?: boolean
}

export type TransactionCreateOut = {
  transaction: TransactionOut
  balance_after: number
  warnings: string[]
}

/** `GET /api/transactions` · `GET /api/transactions/export.csv` 공용 필터 */
export type TransactionQuery = {
  restaurant_id?: number
  user_id?: number
  type?: string
  date_from?: string
  date_to?: string
  include_voided?: boolean
  query?: string
  limit?: number
  offset?: number
}

// ── 통계 ────────────────────────────────────────────────────────

export type MonthlyPoint = {
  month: string
  charge: number
  use: number
  net: number
}

/** 오래된 달 → 최근 달 순 */
export type MonthlyOut = {
  items: MonthlyPoint[]
}

export type SummaryOut = {
  total_balance: number
  restaurant_count: number
  low_balance_count: number
  low_balance_threshold: number
  /** "YYYY-MM" (KST) */
  month: string
  month_charge: number
  month_use: number
  all_time_charge: number
  all_time_use: number
  /** 10건 */
  recent_transactions: TransactionOut[]
  /** 5건 */
  low_balance_restaurants: RestaurantSummary[]
}

export type RestaurantStatRow = {
  restaurant_id: number
  name: string
  charge: number
  use: number
  balance: number
}

export type UserStatRow = {
  user_id: number | null
  name: string
  charge: number
  use: number
  tx_count: number
}

// ── 메타 ────────────────────────────────────────────────────────

export type HealthOut = {
  status: string
  ocr_enabled: boolean
  low_balance_threshold: number
}
