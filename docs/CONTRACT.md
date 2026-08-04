# 인터페이스 계약 (CONTRACT)

이 문서는 백엔드/프론트엔드가 **반드시** 지켜야 하는 인터페이스 규약이다.
여러 사람(또는 에이전트)이 병렬로 작업할 때의 단일 기준점이며, 구현이 이 문서와
어긋나면 문서가 아니라 구현을 고친다.

기준 코드: `backend/app/models.py`(스키마), `backend/app/core/*`(설정·인증·시간),
`backend/app/schemas/common.py`(공용 타입).

---

## 0. 전역 규약

| 항목 | 규약 |
|---|---|
| 금액 | **정수 원 단위**. 소수·문자열 금지. CHARGE/USE 는 양수, ADJUST 는 부호 있는 0 이 아닌 값 |
| 잔액 | 저장하지 않고 항상 계산: `Σ CHARGE − Σ USE + Σ ADJUST` (voided 제외) |
| 시간 | DB=naive UTC / 응답=`...+00:00` ISO / 요청의 naive datetime=**KST 벽시계**로 해석. `app.core.timeutil` 사용 |
| 인증 | httpOnly 쿠키(`ssel_token`). 프론트는 `withCredentials: true`. Bearer 헤더도 폴백 지원 |
| 에러 | FastAPI 기본 `{"detail": "한국어 메시지"}`. 프론트는 `detail` 을 그대로 사용자에게 노출 |
| 사업자등록번호 | 저장·비교 모두 **숫자 10자리 정규화**(`123-45-67890` → `1234567890`). 표시할 때만 하이픈 |
| 삭제 | 거래는 삭제하지 않고 void. 식당은 삭제하지 않고 `is_archived` |
| API prefix | 전부 `/api` |

---

## 1. 백엔드 파일 소유권

| 파일 | 내용 |
|---|---|
| `app/schemas/auth.py` | `UserOut`, `RegisterIn`, `LoginIn`, `UserUpdateIn` |
| `app/schemas/restaurant.py` | `RestaurantSummary`, `RestaurantDetail`, `RestaurantCreateIn`, `RestaurantUpdateIn`, `RestaurantListOut` |
| `app/schemas/receipt.py` | `ParsedReceipt`, `ReceiptOut`, `MatchCandidate`, `MatchResult`, `DuplicateInfo`, `ReceiptUploadOut`, `ConfirmIn`, `ConfirmOut` |
| `app/schemas/transaction.py` | `TransactionOut`, `TransactionCreateIn`, `TransactionCreateOut`, `TransactionListOut`, `VoidIn` |
| `app/schemas/stats.py` | `SummaryOut`, `MonthlyPoint`, `MonthlyOut`, `RestaurantStatRow`, `UserStatRow` |
| `app/services/ledger.py` | 잔액 계산·거래 생성·void·중복탐지·confirm 원자처리 |
| `app/services/matching.py` | 사업자번호 정규화 + rapidfuzz 상호명 매칭 |
| `app/services/ocr.py` | `OcrProvider` 추상화 + Qwen 구현 |
| `app/services/export.py` | CSV 생성 |
| `app/api/{auth,restaurants,receipts,transactions,stats,admin}.py` | 라우터 (각 모듈에 `router = APIRouter()`) |

`app/main.py` 는 위 6개 라우터 모듈을 이미 import 하고 있으므로 **모듈명·`router` 변수명을 반드시 지킬 것.**

---

## 2. API 엔드포인트

### 2.1 인증 `/api/auth`

```
POST /register   {email, name, password, invite_code}        → 201 UserOut  (+쿠키 설정)
POST /login      {email, password}                           → 200 UserOut  (+쿠키 설정)
POST /logout     -                                           → 200 {message}  (+쿠키 삭제)
GET  /me         -                                           → 200 UserOut
```
- `invite_code` 가 `settings.invite_code` 와 다르면 403 `"초대코드가 올바르지 않습니다."`
- 이메일 중복 409, 로그인 실패 401 `"이메일 또는 비밀번호가 올바르지 않습니다."`
- 비밀번호 최소 8자.
- **첫 번째로 가입한 사용자는 자동으로 `admin`** (연구실 초기 세팅 편의).
- 쿠키: `httponly=True, samesite=settings.cookie_samesite, secure=settings.cookie_secure, max_age=jwt_expire_minutes*60, path="/"`

```ts
UserOut = { id: number, email: string, name: string,
            role: "admin"|"member", is_active: boolean, created_at: string }
```

### 2.2 식당 `/api/restaurants`

```
GET    /                → RestaurantListOut
        ?query=          상호명/주소/사업자번호 부분검색 (숫자만 입력하면 사업자번호로도 검색)
        ?sort=           balance_desc(기본) | balance_asc | name | recent | created
        ?include_archived=false
        ?low_only=false  잔액 부족만
POST   /                RestaurantCreateIn      → 201 RestaurantDetail
GET    /{id}            → RestaurantDetail  (recent_transactions 최근 20건 포함)
PATCH  /{id}            RestaurantUpdateIn      → 200 RestaurantDetail
GET    /{id}/transactions ?limit=50&offset=0&include_voided=true → TransactionListOut
```

```ts
RestaurantSummary = {
  id: number, name: string, business_number: string|null,
  address: string|null, phone: string|null, memo: string|null,
  is_archived: boolean,
  balance: number,            // 현재 잔액 (음수 가능)
  charge_total: number,       // 누적 충전
  use_total: number,          // 누적 사용
  tx_count: number,           // 유효 거래 수 (void 제외)
  last_used_at: string|null,
  last_charged_at: string|null,
  is_low_balance: boolean,    // balance < LOW_BALANCE_THRESHOLD (음수 포함)
  created_at: string, updated_at: string,
}

RestaurantDetail = RestaurantSummary & { recent_transactions: TransactionOut[] }

RestaurantListOut = {
  items: RestaurantSummary[], total: number,
  total_balance: number,        // 전체 합계 (archived 제외)
  low_balance_count: number,
  low_balance_threshold: number,
}

// 앱 도입 전 이미 선결제해둔 식당 백필용: initial_balance 를 주면
// "초기 잔액 등록" 메모가 달린 CHARGE 거래를 함께 생성한다.
RestaurantCreateIn = {
  name: string,                       // 필수, 1~200자
  business_number?: string|null,      // 하이픈 허용, 서버가 숫자만 남김. 중복이면 409
  address?: string|null, phone?: string|null, memo?: string|null,
  initial_balance?: number,           // >=0, 기본 0. 0 이면 거래 생성 안 함
  initial_balance_memo?: string|null, // 기본 "초기 잔액 등록"
  occurred_at?: string|null,          // 기본 now
}

RestaurantUpdateIn = { name?, business_number?, address?, phone?, memo?, is_archived? }  // 전부 optional
```
- 사업자번호 중복 → 409 `"이미 등록된 사업자등록번호입니다. (○○식당)"`
- 정렬·집계는 서브쿼리 1회로 (N+1 금지). `models.SIGNED_AMOUNT_SQL` 재사용.

### 2.3 영수증 `/api/receipts`

```
POST /                  multipart: file       → 201 ReceiptUploadOut
GET  /{id}                                    → 200 ReceiptUploadOut  (재조회, OCR 재실행 없음)
GET  /{id}/image                              → 200 이미지 바이트 (인증 필요)
POST /{id}/confirm      ConfirmIn             → 200 ConfirmOut
POST /{id}/reocr                              → 200 ReceiptUploadOut  (OCR 재시도)
```

```ts
ParsedReceipt = {
  store_name: string|null, business_number: string|null,
  address: string|null, phone: string|null,
  total_amount: number|null,     // 부가세 포함 합계
  paid_at: string|null,
}

ReceiptOut = {
  id: number, image_url: string,          // "/api/receipts/{id}/image"
  ocr_status: "pending"|"done"|"failed",
  ocr_error: string|null, ocr_ms: number|null,
  created_at: string, consumed_at: string|null,
  uploaded_by: UserBrief|null,
}

MatchCandidate = { restaurant: RestaurantSummary, score: number, reason: "business_number"|"name" }

MatchResult = {
  matched_by: "business_number"|"name"|null,   // name 은 score>=88 자동확정
  restaurant: RestaurantSummary|null,          // 확정 매칭
  candidates: MatchCandidate[],                // 최대 5개, score 내림차순
}

DuplicateInfo = { receipt_id: number, transaction_id: number|null,
                  restaurant_name: string|null, message: string }

ReceiptUploadOut = {
  receipt: ReceiptOut, parsed: ParsedReceipt,
  match: MatchResult, duplicate: DuplicateInfo|null,
}
```
- 업로드: `image/*` 만, `MAX_UPLOAD_MB` 초과 413. 저장 경로 `data/uploads/YYYY/MM/<uuid4>.<ext>`.
- 저장 전 Pillow 로 **EXIF 회전 보정**(폰 사진 필수) + 긴 변 `OCR_MAX_IMAGE_PX` 로 축소.
- OCR 실패해도 **201 을 반환**한다 (`ocr_status="failed"`, `parsed` 전부 null). 프론트가 수동 입력으로 이어감.
- 중복 판정: 같은 `business_number` + `total_amount` + `paid_at`(±1일) 인 **consumed 된** 영수증이 있으면 `duplicate` 채움. 차단하지 않고 경고만.

```ts
ConfirmIn = {
  action: "register_and_charge" | "charge" | "use",
  restaurant_id?: number|null,     // charge/use 필수
  restaurant?: {                   // register_and_charge 필수
    name: string, business_number?: string|null,
    address?: string|null, phone?: string|null, memo?: string|null,
  }|null,
  charge_amount?: number|null,     // register_and_charge/charge 필수, >0
  use_amount?: number|null,        // 선택, >=0. 0/null 이면 USE 거래 생성 안 함
  occurred_at?: string|null,       // 기본 parsed_paid_at ?? now
  memo?: string|null,
  allow_negative?: boolean,        // 기본 false
  parsed?: ParsedReceipt|null,     // 사용자가 화면에서 고친 값 → receipt 에 반영 저장
}

ConfirmOut = {
  restaurant: RestaurantDetail,
  transactions: TransactionOut[],   // 이번에 생성된 것 (CHARGE, USE 순)
  balance_before: number, balance_after: number,
  warnings: string[],               // 예: "잔액이 부족해 음수가 되었습니다."
}
```
**confirm 규칙**
- 하나의 DB 트랜잭션에서 식당 생성 + CHARGE + USE 를 처리. 중간 실패 시 전부 롤백.
- 성공 시 `receipt.consumed_at` 을 기록하고, 생성된 거래에 `receipt_id` 를 연결한다.
- 이미 `consumed_at` 이 있으면 409 `"이미 처리된 영수증입니다."`
- `use_amount` 가 사용 후 잔액을 음수로 만들고 `allow_negative=false` 면
  409 `"잔액이 부족합니다. (현재 ○○원) 계속하려면 확인해 주세요."` → 프론트가 확인 모달 후 `allow_negative=true` 로 재요청.
- `action="register_and_charge"` 인데 `restaurant.business_number` 가 이미 존재 → 409 (기존 식당으로 안내).

### 2.4 거래 `/api/transactions`

```
GET  /            → TransactionListOut
      ?restaurant_id= &user_id= &type=CHARGE|USE|ADJUST
      &date_from=YYYY-MM-DD &date_to=YYYY-MM-DD   (KST 날짜, 양끝 포함)
      &include_voided=true &query=  (메모/식당명 검색)
      &limit=50 &offset=0
POST /            TransactionCreateIn   → 201 TransactionCreateOut
POST /{id}/void   {reason: string}      → 200 TransactionCreateOut
GET  /export.csv  (GET / 과 동일 필터)   → text/csv; UTF-8 BOM, 파일명 transactions_YYYYMMDD.csv
```

```ts
TransactionOut = {
  id: number, restaurant_id: number, restaurant_name: string,
  type: "CHARGE"|"USE"|"ADJUST",
  amount: number,          // 항상 원본 (양수 또는 ADJUST 부호)
  signed_amount: number,   // 잔액 반영값. void 면 0
  occurred_at: string, memo: string|null,
  receipt_id: number|null, has_receipt: boolean,
  created_by: UserBrief|null, created_at: string,
  is_voided: boolean, voided_at: string|null,
  voided_by: UserBrief|null, void_reason: string|null,
}

TransactionListOut = {
  items: TransactionOut[], total: number, limit: number, offset: number,
  sum_charge: number, sum_use: number, sum_adjust: number,   // void 제외, 필터 전체 기준
}

TransactionCreateIn = {
  restaurant_id: number,
  type: "CHARGE"|"USE"|"ADJUST",
  amount: number,             // CHARGE/USE: >0 / ADJUST: != 0
  occurred_at?: string|null,  // 기본 now
  memo?: string|null,
  receipt_id?: number|null,
  allow_negative?: boolean,   // 기본 false
}

TransactionCreateOut = { transaction: TransactionOut, balance_after: number, warnings: string[] }
```
- void: 이미 void 면 409. `reason` 필수(1자 이상). 누구나 가능하되 기록에 `voided_by` 남김.
- USE 로 잔액이 음수가 되면 위 confirm 과 동일한 409 → `allow_negative=true` 재요청 패턴.

### 2.5 통계 `/api/stats`

```
GET /summary                          → SummaryOut
GET /monthly?months=12                → MonthlyOut
GET /by-restaurant?date_from=&date_to= → { items: RestaurantStatRow[] }
GET /by-user?date_from=&date_to=       → { items: UserStatRow[] }
```
```ts
SummaryOut = {
  total_balance: number, restaurant_count: number, low_balance_count: number,
  low_balance_threshold: number,
  month: string,                 // "YYYY-MM" (KST)
  month_charge: number, month_use: number,
  all_time_charge: number, all_time_use: number,
  recent_transactions: TransactionOut[],       // 10건
  low_balance_restaurants: RestaurantSummary[],// 5건
}
MonthlyPoint = { month: string, charge: number, use: number, net: number }
MonthlyOut = { items: MonthlyPoint[] }         // 오래된 달 → 최근 달 순
RestaurantStatRow = { restaurant_id: number, name: string, charge: number, use: number, balance: number }
UserStatRow = { user_id: number|null, name: string, charge: number, use: number, tx_count: number }
```

### 2.6 관리 `/api/admin` (전부 admin 전용, 403 otherwise)

```
GET   /users            → UserOut[]
PATCH /users/{id}       {name?, role?, is_active?, password?}  → UserOut
GET   /invite-code      → {invite_code: string}
```
- 자기 자신의 `role` 을 member 로 내리거나 `is_active=false` 로 만드는 것은 400 으로 막는다
  (마지막 관리자 잠금 방지).

---

## 3. OCR 서비스 규약 (`app/services/ocr.py`)

```python
@dataclass
class OcrResult:
    parsed: dict        # ParsedReceipt 와 같은 키. 못 읽은 값은 None
    raw: str | None     # 모델 원문 (DB 저장)
    elapsed_ms: int
    error: str | None   # None 이면 성공

class OcrProvider(Protocol):
    def extract(self, image_path: Path) -> OcrResult: ...

def get_ocr_provider() -> OcrProvider   # settings.ocr_provider 로 분기
```
- `QwenVisionProvider`: OpenAI 호환 `POST {OCR_BASE_URL}/chat/completions`,
  `messages=[{role:user, content:[{type:"text",text:PROMPT},{type:"image_url",image_url:{url:"data:image/jpeg;base64,..."}}]}]`,
  `temperature=0`, `OCR_USE_GUIDED_JSON` 이면 `extra_body.guided_json` 추가.
- `QwenTextProvider`: (비전 미지원 폴백) 이미지→텍스트는 별도 OCR 필요.
  구현체는 두되 텍스트 추출기가 없으면 `error="비전 미지원 폴백에 로컬 OCR 이 필요합니다"` 반환.
- `DisabledProvider`: 즉시 `error=None, parsed=all-None` 반환 (조용히 수동 입력 유도).
- 프롬프트는 **JSON 만** 출력하도록 지시하고, 응답에서 ```json 코드펜스/앞뒤 잡텍스트를 벗겨
  첫 `{`~마지막 `}` 를 파싱한다. 파싱 실패는 `error` 로.
- 금액 정규화: `"12,000원"`, `"₩12000"`, `"12.000"` → `12000`. 날짜: `2026-08-04 12:30`,
  `2026/08/04`, `26.08.04` 등 관용 파싱(`dateutil`), 실패 시 None.
- **모든 예외를 삼켜서 `error` 로 변환**한다. OCR 이 앱을 죽이면 안 된다.

## 4. 매칭 서비스 규약 (`app/services/matching.py`)

```python
def normalize_business_number(v: str | None) -> str | None   # 숫자만, 10자리 아니면 None
def format_business_number(v: str | None) -> str | None      # "123-45-67890"
def normalize_name(v: str) -> str                            # 공백/괄호/지점표기 제거, 소문자화
def match_restaurant(db, parsed, limit=5) -> MatchOutcome
    # 1) business_number 정확일치 → matched_by="business_number", score=100
    # 2) rapidfuzz(WRatio, normalize_name) → 최고점 >= 88 이면 matched_by="name"
    #    그 외는 score >= 60 인 것들을 candidates 로만 반환 (matched_by=None)
```

---

## 5. 프론트엔드 계약

### 5.1 라우트 / 페이지 파일

| 경로 | 파일 | 설명 |
|---|---|---|
| `/login` | `src/pages/LoginPage.vue` | 로그인 + 초대코드 가입 (탭) |
| `/` | `src/pages/HomePage.vue` | **선결제 식당 목록** + 총 잔액 + CTA 2개 |
| `/scan` | `src/pages/ScanPage.vue` | 영수증 촬영 → OCR → 매칭 → 충전/사용 확정 |
| `/use` | `src/pages/ManualUsePage.vue` | 영수증 없이 사용 기록 |
| `/restaurants/new` | `src/pages/RestaurantNewPage.vue` | 식당 직접 등록(기존 선결제 백필) |
| `/restaurants/:id` | `src/pages/RestaurantDetailPage.vue` | 잔액 + 거래 타임라인 + 충전/차감/수정 |
| `/ledger` | `src/pages/LedgerPage.vue` | 전체 원장 + 필터 + void + CSV |
| `/stats` | `src/pages/StatsPage.vue` | 통계 |
| `/admin` | `src/pages/AdminPage.vue` | 사용자 관리 (admin 전용) |

- 라우터 가드: 미인증 → `/login?redirect=<path>`. `/admin` 은 `role!=="admin"` 이면 `/` 로.
- 별칭 `@` → `src/`.

### 5.2 `src/api/types.ts` — 위 2장의 타입을 그대로 TS 로 선언 (동일 이름)

### 5.3 `src/api/endpoints.ts` — 페이지가 쓰는 유일한 API 표면

```ts
export const authApi = {
  register(body: {email:string; name:string; password:string; invite_code:string}): Promise<UserOut>
  login(body: {email:string; password:string}): Promise<UserOut>
  logout(): Promise<void>
  me(): Promise<UserOut>
}
export const restaurantApi = {
  list(params?: {query?:string; sort?:string; include_archived?:boolean; low_only?:boolean}): Promise<RestaurantListOut>
  get(id: number): Promise<RestaurantDetail>
  create(body: RestaurantCreateIn): Promise<RestaurantDetail>
  update(id: number, body: RestaurantUpdateIn): Promise<RestaurantDetail>
  transactions(id: number, params?: {limit?:number; offset?:number; include_voided?:boolean}): Promise<TransactionListOut>
}
export const receiptApi = {
  upload(file: File, onProgress?: (pct:number)=>void): Promise<ReceiptUploadOut>
  get(id: number): Promise<ReceiptUploadOut>
  reocr(id: number): Promise<ReceiptUploadOut>
  confirm(id: number, body: ConfirmIn): Promise<ConfirmOut>
  imageUrl(id: number): string
}
export const transactionApi = {
  list(params?: TransactionQuery): Promise<TransactionListOut>
  create(body: TransactionCreateIn): Promise<TransactionCreateOut>
  void_(id: number, reason: string): Promise<TransactionCreateOut>
  exportCsvUrl(params?: TransactionQuery): string
}
export const statsApi = {
  summary(): Promise<SummaryOut>
  monthly(months?: number): Promise<MonthlyOut>
  byRestaurant(p?: {date_from?:string; date_to?:string}): Promise<{items: RestaurantStatRow[]}>
  byUser(p?: {date_from?:string; date_to?:string}): Promise<{items: UserStatRow[]}>
}
export const adminApi = {
  users(): Promise<UserOut[]>
  updateUser(id: number, body: {name?:string; role?:string; is_active?:boolean; password?:string}): Promise<UserOut>
  inviteCode(): Promise<{invite_code: string}>
}
export const healthApi = { get(): Promise<{status:string; ocr_enabled:boolean; low_balance_threshold:number}> }

export type TransactionQuery = {
  restaurant_id?: number; user_id?: number; type?: string;
  date_from?: string; date_to?: string; include_voided?: boolean;
  query?: string; limit?: number; offset?: number;
}
/** axios 에러 → 사용자에게 보여줄 한국어 메시지 */
export function errorMessage(e: unknown): string
/** 서버가 409 로 음수잔액을 거부했는지 */
export function isInsufficientBalance(e: unknown): boolean
```

### 5.4 `src/utils/format.ts`

```ts
export function won(n: number|null|undefined): string          // 12000 → "12,000원"
export function wonShort(n: number|null|undefined): string     // 12000 → "1.2만"  (요약 카드용)
export function dateTime(iso: string|null|undefined): string    // "2026-08-04 12:30"
export function dateOnly(iso: string|null|undefined): string    // "2026-08-04"
export function relativeDate(iso: string|null|undefined): string // "오늘" "어제" "3일 전" "2026-06-01"
export function bizNumber(v: string|null|undefined): string     // "123-45-67890"
export function txLabel(t: "CHARGE"|"USE"|"ADJUST"): string      // "선결제 충전" | "사용" | "정정"
export function txColor(t: string): string                       // vuetify color: success|error|warning
export function todayInput(): string                             // "YYYY-MM-DD" (KST)
export function nowLocalInput(): string                          // "YYYY-MM-DDTHH:mm" (KST, datetime-local 용)
```

### 5.5 스토어

```ts
// src/stores/auth.ts  — useAuthStore()
{ user: UserOut|null, ready: boolean, isAuthenticated: boolean, isAdmin: boolean,
  fetchMe(): Promise<void>, login(email,password): Promise<void>,
  register(body): Promise<void>, logout(): Promise<void> }

// src/stores/app.ts  — useAppStore()   전역 스낵바 + 서버 설정
{ ocrEnabled: boolean, lowBalanceThreshold: number,
  loadHealth(): Promise<void>,
  toast(message: string, color?: "success"|"error"|"info"|"warning"): void }
```
`useAppStore().toast(...)` 는 `App.vue` 의 `<v-snackbar>` 가 렌더한다. 페이지는 자체 스낵바를 만들지 말 것.

### 5.6 페이지 작성 규칙 (충돌 방지)

- 페이지가 import 할 수 있는 것: **Vuetify 컴포넌트**, `@/api/endpoints`, `@/api/types`,
  `@/utils/format`, `@/stores/*`, `vue`, `vue-router`. 그 외 커스텀 컴포넌트에 의존하지 않는다.
- 모든 사용자 노출 문구는 **한국어**.
- 금액 입력은 `<v-text-field type="number" inputmode="numeric">` + `suffix="원"`.
- 에러는 `appStore.toast(errorMessage(e), "error")`.
- 모바일 우선: 최대 폭 `<v-container class="pa-3" style="max-width:720px">`, 버튼은 `size="large" block`.

### 5.7 UI 문구 표준 (일관성 필수)

| 개념 | 문구 |
|---|---|
| 충전 | **선결제 충전** (버튼: `선결제 충전하기`) |
| 차감 | **사용** (버튼: `잔액에서 차감하기`) |
| 홈 CTA 1 | `📷 영수증 스캔` |
| 홈 CTA 2 | `✏️ 영수증 없이 기록` |
| 식당 직접 등록 | `+ 식당 직접 등록` (부제: `이미 선결제해둔 식당 추가`) |
| 즉시사용 질문 | `이번 결제에서 바로 사용한 금액이 있나요?` |
| 잔액 부족 배지 | `잔액 부족` |
| void | `기록 취소` (사유 입력 필수) |

---

## 6. 로컬 실행

```bash
# 백엔드
cd backend && .venv/Scripts/activate      # Windows
alembic upgrade head
python scripts/seed.py                    # 관리자 계정 + 예시 데이터
uvicorn app.main:app --reload --port 8000

# 프론트엔드
cd frontend && npm install && npm run dev # http://localhost:5173 (/api → :8000 프록시)
```
