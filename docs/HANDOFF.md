# 인수·인계 (HANDOFF)

작성 시점: **2026-08-04** · 저장소: https://github.com/Jung-YongHan/ssel-rest-mng (public)

이 문서는 **프로젝트를 넘겨받는 사람**을 위한 것이다. 무엇이 되어 있고, 무엇이 검증되었고,
무엇이 아직 안 되어 있는지를 솔직하게 적었다. 개발 규칙은 [CLAUDE.md](../CLAUDE.md) 를 본다.

---

## 1. 한 줄 요약

연구실이 식당에 미리 결제해둔 금액을 **영수증 사진으로 등록하고 방문할 때마다 차감**해
잔액을 추적하는 웹앱. 폰으로 촬영·기록하고 PC 로 관리한다. 코드는 완성되어 동작하며,
**실사용을 시작하려면 `.env` 설정과 OCR 서버 확인이 남아 있다.**

규모: 백엔드 Python 5,601줄 · 프론트 6,258줄 · 테스트 163건 · 화면 9개 · 커밋 8개.

## 2. 완성 상태

| 마일스톤 | 상태 | 내용 |
|---|---|---|
| M0 스캐폴딩·인증 | **완료** | 초대코드 가입, JWT httpOnly 쿠키, admin/member 역할, Docker, CI |
| M1 코어 원장 | **완료** | 식당 CRUD, 초기 잔액 백필, 수동 충전/차감, 잔액 계산, 홈·상세 |
| M2 영수증 파이프라인 | **코드 완료 / 실환경 미검증** | 업로드·전처리·OCR·매칭·confirm. **Qwen 비전 지원 여부만 미확인** (§4-1) |
| M3 관리·통계 | **완료** | 원장 필터, 기록 취소, 통계, CSV 내보내기, 사용자 관리 |
| M4 (선택) | **미착수** | 잔액 부족 웹푸시 알림, HTTPS/PWA 설치 |

유스케이스 대응:

- **UC1 신규 식당 선결제 등록** / **UC2 잔액 사용** / **UC3 추가 선결제** →
  세 개를 별도 화면으로 만들지 않고 **하나의 영수증 스캔 플로우의 분기**로 구현했다(`/scan`).
- **UC4 웹 관리** → 대시보드(홈) · 원장 · 통계 · 사용자 관리 · CSV 내보내기.
- **추가 요구** → 이미 선결제해둔 식당 백필 등록(`/restaurants/new`), 선결제 식당 목록(홈).

## 3. 인수 후 바로 할 일

```powershell
# 1) 로컬에서 돌려보기
cp .env.example .env          # JWT_SECRET, INVITE_CODE 를 반드시 교체
cd backend
python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe scripts\seed.py --demo     # 화면 확인용 예시 데이터
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
cd ..\frontend; npm install; npm run dev            # http://localhost:5173

# 2) OCR 서버 확인 (§4-1 — 가장 먼저 할 일)
cd backend
.venv\Scripts\python.exe scripts\ocr_smoke.py 실제영수증.jpg

# 3) 원격 서버 배포
#    docs/DEPLOY.md 를 따른다 (git clone → .env → docker compose up -d --build)
```

**실사용 시작 전 체크리스트**

- [ ] `JWT_SECRET` 교체 (`openssl rand -hex 32`) — 기본값이면 서버 로그에 경고가 뜬다
- [ ] `INVITE_CODE` 교체 — 이 코드를 아는 사람만 가입할 수 있다
- [ ] `OCR_BASE_URL` 에 연구실 Qwen 엔드포인트 입력 (**코드·문서에 하드코딩 금지**)
- [ ] HTTP 로 배포하면 `COOKIE_SECURE=false` 유지 (true 면 로그인이 안 된다)
- [ ] **예시 데이터 정리** — `seed.py --demo` 로 넣은 식당 3곳(행복분식·청춘국수·든든한식당)은
      가짜다. 운영 DB 에서는 `--demo` **없이** 실행하고, 이미 넣었다면 새 DB 로 시작한다
      (`backend/data/app.db` 삭제 후 `alembic upgrade head`). 지우는 플래그는 없다.
- [ ] 첫 가입 계정이 자동으로 관리자가 된다 — 연구실장 계정으로 먼저 가입할 것
- [ ] 기존에 선결제해둔 식당들을 `/restaurants/new` 에서 현재 남은 잔액으로 등록

## 4. 미해결 항목 (중요한 순서)

### 4-1. Qwen 서버의 비전(이미지) 입력 지원 여부 미확인 ⚠️ 최우선

영수증 OCR 은 연구실 자체 호스팅 Qwen 서버를 OpenAI 호환 API(vLLM 등)로 가정해 구현했다.
**그 배포본이 이미지 입력을 받는지는 확인하지 못했다.**

- 확인: `python scripts/ocr_smoke.py <영수증 이미지>` — 파싱 JSON 이 나오면 성공.
- 비전 미지원이면 `.env` 의 `OCR_PROVIDER=qwen_text` 로 바꾼다. 단
  **`services/ocr.py` 의 `QwenTextProvider` 는 텍스트 추출기가 비어 있다** —
  PaddleOCR(한글) 등을 붙여 `text_extractor` 를 구현해야 한다. 현재는 안내 메시지만 반환한다.
- 그동안에도 앱은 `OCR_PROVIDER=disabled` 로 **수동 입력만으로 완전히 사용 가능**하다.
  잔액 관리라는 본래 목적은 OCR 없이도 달성된다.

### 4-2. 실사용 검증이 안 되어 있다

자동 검증은 충분히 했지만(§5), 다음은 사람이 해봐야 한다.

- 실제 영수증 사진으로 OCR 정확도 확인 (특히 합계금액과 사업자등록번호)
- 실기기(폰) 에서 촬영 → 등록 → 차감 완주. 브라우저 렌더링은 headless Chrome 으로
  확인했지만 **실기기 터치·카메라 동작은 미검증**이다.
- 여러 명이 동시에 같은 식당을 차감하는 경우 (동시성은 last-write-wins 로 설계했다.
  연구실 규모에서는 문제되지 않지만 확인해두면 좋다)

### 4-3. 본문 폰트 2.2MB 트레이드오프

Pretendard 3개 웨이트(400/500/700)를 셀프호스팅한다. LAN 내부 배포라면 문제없고
런타임 캐시로 한 번만 받는다. 외부 인터넷에 공개한다면 첫 로딩이 무겁다.

- 줄이려면 `frontend/src/main.ts` 의 `@fontsource/pretendard/500.css` import 를 제거
  (1.5MB). 대신 중간 굵기 텍스트가 굵게 합성된다.
- 폰트를 빼려면 import 3줄을 모두 지운다. 시스템 폰트(맑은 고딕)로 폴백되며 **한국어
  UI 품질이 눈에 띄게 떨어진다** — 처음에 실제로 그 상태였다.

### 4-4. 운영 항목

- **HTTPS 미구성.** 카메라 촬영(`<input capture>`)은 HTTP 에서도 되지만
  **PWA "홈 화면에 추가"는 HTTPS 가 필요**하다. `docs/DEPLOY.md` 에 Caddy 3줄 설정이 있다.
- **백업 자동화 없음.** DEPLOY.md 에 수동 절차(`sqlite3 .backup`)와 cron 예시가 있다.
  `backend/data/` 에 DB + 영수증 이미지가 모두 있으므로 이 디렉터리만 백업하면 된다.
- **로그인 시도 제한 없음.** 내부망 + 초대코드 전제로 rate limiting 을 넣지 않았다.
  외부에 노출한다면 `api/auth.py` 의 login 에 제한을 추가할 것.
- **CI 에 브라우저 E2E 없음.** pytest·타입체크·Docker 빌드만 돈다. 화면 회귀는
  검증 스크립트를 되살려 붙이면 된다(§5 참고).

### 4-5. 알려진 작은 것들 (기능에 영향 없음)

| 항목 | 위치 |
|---|---|
| `GET /restaurants/{id}` 의 `recent_transactions` 를 상세 화면이 쓰지 않는다(별도 페이지네이션 사용). 응답 낭비 | `api/restaurants.py`, `RestaurantDetailPage.vue` |
| `.choice-card` / `.amount-field` scoped 스타일이 ScanPage·ManualUsePage 에 중복. `styles.css` 로 올리면 좋다 | 두 페이지의 `<style scoped>` |
| `<v-table>` 헤더가 `.field-label` 의 12px 크기를 못 받는다(Vuetify 규칙이 더 강함). 색만 적용됨 | `AdminPage.vue`, `StatsPage.vue` |
| 통계 월별 표만 `wonShort()` 를 쓴다(360px 에 4열이 안 들어감) | `StatsPage.vue` |

### 4-6. PWA 홈 화면 아이콘·설치 안내 (2026-08-19 종결)

iOS 26/27 에서 홈 화면 아이콘이 글자 타일로 나오던 문제(커밋 2211d32~1a97609 의 5차례
시도)의 원인 두 가지. 이름 "선결제"는 처음부터 정상이었다 — 아이콘 실패의 글자 타일
폴백이 이름 문제처럼 보였을 뿐이다.

1. manifest 의 `any` 아이콘(-v2)에 **실제 투명 픽셀**이 있었다. iOS 는 알파를 검정으로
   합성하거나 글자 타일로 폴백한다. → 불투명 풀블리드 -v3 로 교체.
2. `manifest.webmanifest` 가 **서비스워커 프리캐시**에 들어 있었다. `registerType: 'prompt'`
   는 사용자가 '업데이트'를 누르기 전까지 옛 프리캐시를 유지하는데, iOS 는 홈 화면 추가
   때 SW 캐시를 거쳐 manifest 를 읽는다(커밋 7ad89ad 에서 확인) → 갓 배포한 아이콘이
   기기에 영영 닿지 않았다. → vite.config.ts 의 `ssel:manifest-no-precache` 플러그인으로
   프리캐시에서 제외 (서버는 이미 no-cache 로 서빙, main.py SHELL_FILES).

지켜야 할 규칙은 CLAUDE.md §3-12. 추가로:

- 기존 기기는 홈 화면 앱에서 '업데이트'를 한 번 눌러야 stale manifest 가 끊긴다.
  그 다음부터는 홈 화면 추가 때마다 항상 최신 manifest 를 받는다.
- 설치 안내: PWA 가 아닌 모바일 브라우저로 접근하면 로그인 전이라도 즉시 1회,
  닫으면(방식 불문) 7일 스누즈
  (`ssel.installSnoozedAt`). iOS(비인앱)는 공유 → 홈 화면에 추가 단계 안내,
  Android 크롬 계열은 네이티브 설치 창. 삼성 인터넷·파이어폭스·인앱 브라우저
  (카카오톡 등)는 의도적으로 침묵 — 따라할 수 없는 안내는 띄우지 않는다.
  인앱 브라우저 탈출(intent:// 리다이렉트)은 범위 밖으로 남겨 두었다.

## 5. 검증 현황

**자동 검증 (재현 가능)**

| 항목 | 결과 |
|---|---|
| pytest | **163건 통과** (auth 19 · ledger 29 · matching 40 · receipts 25 · restaurants 28 · stats 22) |
| Alembic ↔ models.py 일치 | 테이블·컬럼·타입·nullable·인덱스·유니크·외래키 전부 일치, upgrade/downgrade 정상 |
| GitHub Actions CI | pytest · 프론트 타입체크+빌드 · Docker 빌드 3잡 통과 |
| 유스케이스 E2E (HTTP) | 80건 통과 — UC1/UC2/UC3 + 백필 등록, 음수잔액 거부→재시도, void 후 잔액 복원 |
| KST 시간 규약 | 15건 통과 — `datetime-local` 입력 왕복, 월 경계(KST 9/1 00:30 → UTC 8/31 15:30), 날짜 필터 |
| 컨테이너 배포 | 28건 통과 — 자체 마이그레이션, SPA 서빙, 비루트 실행, 재시작 후 데이터 유지 |
| 화면 렌더링 (실제 Chrome headless) | 9화면 × 모바일 390px·데스크톱 1440px — 마운트·가로오버플로·콘솔에러 전부 통과, 라이트/다크 확인 |

화면 검증은 Node 24 내장 `WebSocket` 으로 Chrome DevTools Protocol 을 붙여서 했다
(Windows 에서 `chrome --dump-dom` 은 빈 출력을 주므로 CDP 나 `--screenshot` 을 써야 한다).
CI 에 붙이려면 이 방식을 재사용하면 된다.

**검증하지 않은 것**: 실제 영수증 OCR 정확도, 실기기 카메라·터치, HTTPS/PWA 설치,
부하·동시성, 장기 운영(백업 복구 리허설).

## 6. 설계 결정과 이유

다시 논의하지 않도록 근거를 남긴다.

1. **잔액을 컬럼으로 저장하지 않는다.** 원장 합계로만 계산한다. 정정·감사 추적이 쉽고
   잔액이 실제 기록과 어긋날 수 없다. 대신 집계 쿼리가 필요해서
   `restaurant_stats_subquery()` 로 목록을 1회 쿼리로 처리한다.
2. **기록을 삭제하지 않는다.** void + 사유 + 취소자. 연구비 정산에서 "누가 언제 무엇을"이
   남아야 한다.
3. **UC1/UC2/UC3 을 한 플로우로 합쳤다.** 영수증만 보고는 그것이 충전인지 사용인지
   구분할 수 없다. 그래서 매칭 결과에 따라 사용자에게 물어보는 분기 구조가 자연스럽다.
4. **매칭 1순위는 사업자등록번호.** 한국 영수증에는 항상 인쇄되어 있고 상호명 유사도보다
   훨씬 신뢰할 수 있다. 상호명 fuzzy 매칭은 보조 수단.
5. **SQLite.** 사용자 5~20명 규모에 충분하고 배포·백업이 파일 하나다.
   `DATABASE_URL` 만 바꾸면 PostgreSQL 로 전환된다(compose 에 주석 처리된 서비스가 있다).
6. **단일 컨테이너.** FastAPI 가 `frontend/dist` 를 직접 서빙하므로 nginx 가 필요 없다.
7. **OCR 은 편의 기능.** 실패해도 앱이 멈추지 않고 수동 입력으로 완주 가능하게 만들었다.
   자체 호스팅 모델의 가용성에 앱 전체를 걸지 않기 위해서다.
8. **잔액 음수를 허용한다.** 실수로 초과 차감하는 것을 막기보다, 경고 후 기록하고 정정할 수
   있게 하는 편이 실제 회계에 가깝다.
9. **문서 우선순위**: 시각 표현은 `DESIGN.md`, 인터페이스는 `CONTRACT.md`.
   구현이 문서와 어긋나면 구현을 고치거나 문서를 먼저 바꾼다.

## 7. 기능을 추가할 때 건드릴 지점

| 하고 싶은 일 | 건드릴 곳 |
|---|---|
| 새 API 엔드포인트 | `CONTRACT.md` §2 에 먼저 규약 추가 → `schemas/` → `api/` → `tests/` |
| 새 화면 | `CONTRACT.md` §5.1 라우트 표 → `router/index.ts` → `pages/` (DESIGN.md 준수) |
| 스키마 변경 | `models.py` → `alembic revision --autogenerate` → 생성 파일 확인 → 테스트 |
| 잔액 계산 규칙 변경 | `services/ledger.py` 한 곳. 여기만 고치면 목록·상세·통계·CSV 가 함께 따라온다 |
| 다른 OCR 제공자 | `services/ocr.py` 에 `OcrProvider` 구현 추가 + `get_ocr_provider()` 분기 |
| 알림(잔액 부족) | `stats.summary` 의 `low_balance_restaurants` 를 재사용. 웹푸시는 M4 미착수 |
| 디자인 토큰 변경 | `main.ts`(테마) + `styles.css`(유틸) 두 곳. 페이지에 hex 를 넣지 않는다 |

## 8. 연락·이력

- 저장소 이슈/PR 로 논의한다. CI 가 통과해야 머지한다.
- 커밋 메시지는 무엇을 왜 바꿨는지 한국어로 적는다(기존 8개 커밋 참고).
