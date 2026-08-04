/**
 * 표시 포맷 유틸 (CONTRACT §5.4).
 *
 * - 금액은 정수 원 단위이며 `Intl.NumberFormat('ko-KR')` 로 천단위 구분한다.
 * - API 의 시각은 `...+00:00` ISO 문자열이므로 **항상 Asia/Seoul 로 렌더**한다.
 *   (사용자 기기 타임존이 KST 가 아니어도 연구실 기준 시간으로 보이게 한다.)
 */

const SEOUL = 'Asia/Seoul'
const KST_OFFSET_MS = 9 * 60 * 60 * 1000
const DAY_MS = 24 * 60 * 60 * 1000

const numberFormat = new Intl.NumberFormat('ko-KR')

const dateTimeParts = new Intl.DateTimeFormat('en-CA', {
  timeZone: SEOUL,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

type Parts = { year: string; month: string; day: string; hour: string; minute: string }

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

function seoulParts(date: Date): Parts {
  const out: Record<string, string> = {}
  for (const part of dateTimeParts.formatToParts(date)) {
    if (part.type !== 'literal') out[part.type] = part.value
  }
  return out as unknown as Parts
}

/** KST 기준 '며칠째'인지 (달력 날짜 비교용). KST 는 DST 가 없어 고정 오프셋으로 정확하다. */
function seoulDayIndex(date: Date): number {
  return Math.floor((date.getTime() + KST_OFFSET_MS) / DAY_MS)
}

// ── 금액 ────────────────────────────────────────────────────────

/** 12000 → "12,000원" */
export function won(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '-'
  return `${numberFormat.format(n)}원`
}

/** 12000 → "1.2만"  (요약 카드용) */
export function wonShort(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '-'

  const sign = n < 0 ? '-' : ''
  const abs = Math.abs(n)
  if (abs < 10_000) return `${sign}${numberFormat.format(abs)}원`

  const [divisor, unit] = abs >= 100_000_000 ? [100_000_000, '억'] : [10_000, '만']
  const value = abs / divisor
  const text =
    value >= 100
      ? numberFormat.format(Math.round(value))
      : value.toFixed(1).replace(/\.0$/, '')
  return `${sign}${text}${unit}`
}

// ── 날짜/시간 (Asia/Seoul) ──────────────────────────────────────

/** "2026-08-04 12:30" */
export function dateTime(iso: string | null | undefined): string {
  const date = toDate(iso)
  if (!date) return '-'
  const p = seoulParts(date)
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`
}

/** "2026-08-04" */
export function dateOnly(iso: string | null | undefined): string {
  const date = toDate(iso)
  if (!date) return '-'
  const p = seoulParts(date)
  return `${p.year}-${p.month}-${p.day}`
}

/** "오늘" "어제" "3일 전" "2026-06-01" */
export function relativeDate(iso: string | null | undefined): string {
  const date = toDate(iso)
  if (!date) return '-'

  const diff = seoulDayIndex(new Date()) - seoulDayIndex(date)
  if (diff === 0) return '오늘'
  if (diff === 1) return '어제'
  if (diff > 1 && diff < 7) return `${diff}일 전`
  return dateOnly(iso)
}

/** "YYYY-MM-DD" (KST) — `<input type="date">` 초기값 */
export function todayInput(): string {
  const p = seoulParts(new Date())
  return `${p.year}-${p.month}-${p.day}`
}

/** "YYYY-MM-DDTHH:mm" (KST) — `<input type="datetime-local">` 초기값 */
export function nowLocalInput(): string {
  const p = seoulParts(new Date())
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

// ── 기타 ────────────────────────────────────────────────────────

/** "1234567890" → "123-45-67890" (10자리가 아니면 원본 그대로) */
export function bizNumber(v: string | null | undefined): string {
  if (!v) return '-'
  const digits = v.replace(/\D/g, '')
  if (digits.length !== 10) return v
  return `${digits.slice(0, 3)}-${digits.slice(3, 5)}-${digits.slice(5)}`
}

/** 거래 종류 라벨 — UI 문구 표준(CONTRACT §5.7) */
export function txLabel(t: 'CHARGE' | 'USE' | 'ADJUST'): string {
  if (t === 'CHARGE') return '선결제 충전'
  if (t === 'USE') return '사용'
  return '정정'
}

/** 거래 종류 색 (vuetify color) */
export function txColor(t: string): string {
  if (t === 'CHARGE') return 'success'
  if (t === 'USE') return 'error'
  if (t === 'ADJUST') return 'warning'
  return 'grey'
}
