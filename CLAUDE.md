# CLAUDE.md — 개발 사양 및 작업 지침

연구실 **선결제(prepaid) 잔액 관리** 웹앱. 식당에 미리 결제해둔 금액을 영수증 사진으로
등록하고, 방문할 때마다 차감해 잔액을 추적한다. FastAPI + Vue 3 단일 컨테이너.

이 파일은 매 세션에 로드되므로 **짧게 유지**한다. 상세 내용은 아래 문서를 열어볼 것.

| 문서 | 언제 읽나 |
|---|---|
| [docs/CONTRACT.md](docs/CONTRACT.md) | API·스키마·타입·프론트 모듈 시그니처를 건드릴 때 (**API 작업의 기준**) |
| [docs/DESIGN.md](docs/DESIGN.md) | UI 를 만들거나 고칠 때 (**시각 표현의 기준**, 충돌 시 CONTRACT 보다 우선) |
| [docs/HANDOFF.md](docs/HANDOFF.md) | 프로젝트 현재 상태·미해결 항목·다음 할 일 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | 원격 서버 배포·백업·HTTPS |
| [README.md](README.md) | 기능 개요·환경변수 표·OCR 설정 |

---

## 1. 구조

```
backend/app/
  main.py            FastAPI 엔트리 + frontend/dist 정적 서빙(SPA fallback)
  models.py          스키마의 단일 진실 공급원
  core/              config(.env) · db · security(bcrypt+JWT) · deps · timeutil
  schemas/           Pydantic v2 (common.py 의 UtcOut/KstIn 을 재사용)
  services/          ledger(잔액·거래·confirm) · matching · ocr · export
  api/               auth · restaurants · receipts · transactions · stats · admin
  alembic/           마이그레이션 (0001_initial_schema)
  scripts/           seed.py · ocr_smoke.py
  tests/             pytest 163건
frontend/src/
  main.ts            Vuetify 테마·컴포넌트 기본값 (디자인 토큰의 구현체)
  styles.css         디자인 유틸리티 클래스 (페이지에서 재사용, 재정의 금지)
  App.vue            앱 셸(앱바·내비·전역 스낵바·테마 토글)
  api/               client(axios) · types · endpoints ← 페이지의 유일한 API 표면
  stores/            auth · app(스낵바·서버설정·앱 업데이트)
  utils/format.ts    won() · dateTime() · txLabel() 등 표시 포맷터
  pages/             9개 화면
```

## 2. 명령

Windows 기준. 백엔드는 `backend/` 에서, 프론트는 `frontend/` 에서 실행한다.

```powershell
# 백엔드 (venv: backend\.venv)
.venv\Scripts\python.exe -m alembic upgrade head      # 스키마 적용 (최초/변경 후 필수)
.venv\Scripts\python.exe scripts\seed.py --demo       # 관리자 + 예시 데이터 (idempotent)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
.venv\Scripts\python.exe -m pytest -q                 # 163건
.venv\Scripts\python.exe scripts\ocr_smoke.py <이미지> # Qwen 서버 연결/비전 지원 확인

# 프론트 (dev 는 /api → :8000 프록시)
npm run dev
npm run typecheck        # vue-tsc --noEmit
npm run build            # typecheck + vite build → dist/ (FastAPI 가 서빙)

# 운영
docker compose up -d --build     # 엔트리포인트가 alembic upgrade head 를 먼저 실행
```

마이그레이션 추가: `alembic revision --autogenerate -m "설명"` → 생성된 파일을 **반드시 눈으로 확인**
(SQLite 는 `render_as_batch=True` 로 ALTER 를 우회한다).

## 3. 절대 지켜야 하는 불변식

어기면 조용히 데이터가 틀어지는 항목들이다. 실제로 한 번씩 겪은 것만 적었다.

1. **잔액은 저장하지 않는다.** 항상 `Σ CHARGE − Σ USE + Σ ADJUST` (voided 제외).
   잔액 컬럼을 추가하지 말 것. 집계는 `services/ledger.py` 의 `restaurant_stats_subquery()`
   를 재사용한다 (목록에서 N+1 금지).
2. **금액은 정수 원 단위.** 부동소수점·Decimal·문자열 금지. CHARGE/USE 는 양수,
   ADJUST 는 부호 있는 0 이 아닌 값.
3. **시간**: DB=naive UTC / 응답=`...+00:00` / **요청의 naive 값 = KST 벽시계**.
   - 요청 datetime 필드는 반드시 `schemas/common.py` 의 `KstIn`(또는 `KstDateTime`)을 쓴다.
     raw `datetime` 을 쓰면 `"2026-08-04T12:30"` 문자열이 변환을 우회해 **9시간 밀린다.**
   - 응답 datetime 은 `UtcOut` 을 쓴다. **입력용 타입으로 응답을 만들면 이미 UTC 인 값이
     KST 로 재해석되어 또 9시간 밀린다** → `ParsedReceipt`(요청) / `ParsedReceiptOut`(응답)
     가 분리되어 있는 이유.
   - 날짜 경계 집계는 `core/timeutil.py` 의 `kst_month_bounds` 등을 쓴다 (KST 8/1 00:00 = UTC 7/31 15:00).
4. **기록은 삭제하지 않는다.** `void_at` + `void_reason` + `voided_by` 로 무효화한다.
   식당도 삭제하지 않고 `is_archived`.
5. **영수증 이중 처리 방지**: `receipts.consumed_at` 이 있으면 confirm 을 409 로 막는다.
   confirm 은 식당 생성 + CHARGE + USE 를 **하나의 DB 트랜잭션**으로 처리한다.
6. **사업자등록번호는 숫자 10자리로 정규화**해서 저장·비교한다(`matching.normalize_business_number`).
   하이픈은 표시할 때만.
7. **OCR 은 절대 예외를 던지지 않는다.** 모든 실패를 `OcrResult.error` 로 변환하고,
   업로드는 실패해도 201 을 반환한다. 모든 플로우는 OCR 없이 수동 입력으로 완주 가능해야 한다.
8. **UI 에 이모지 금지.** MDI outline 아이콘을 쓴다 (DESIGN.md §3 매핑표).
9. **`VCard` 기본값이 `variant="outlined"` 라서 생기는 보정 두 가지** (`styles.css`).
   지우면 조용히 화면이 망가진다.
   - **테두리**: Vuetify 의 `border: thin solid currentColor` 를 헤어라인 색으로 되돌린다.
     선택자는 반드시 `.v-card.v-card--variant-outlined` — 컴포넌트별 CSS 가 이 파일보다
     **뒤에** 번들되므로 특이도가 같으면 보정이 통째로 무시된다.
   - **다이얼로그 배경**: outlined 는 `background: transparent` 이고 `VDialog.css` 는
     패널 배경을 칠하지 않는다(`VMenu.css` 만 칠한다). 보정을 지우면 모든 모달이
     속이 비쳐 뒤 화면과 겹쳐 보인다. 스크림 색은 **불투명**하게 줄 것 —
     Vuetify 가 `--v-overlay-opacity` 를 한 번 더 곱한다.
   - **다이얼로그 글자색**: outlined 는 `color: inherit` 인데, 오버레이는
     `.v-application` 이 아니라 **`<body>` 바로 아래**로 teleport 되므로 테마
     잉크색이 닿지 않는다. `styles.css` 가 `.v-overlay` 에 칠해 둔다. 지우면
     **OS 다크 + 앱 라이트**(또는 그 반대)에서 다이얼로그 내용이 전부 사라진다.
     같은 이유로 `App.vue` 가 `documentElement.style.colorScheme` 을 앱 테마에
     맞춰 준다 — 네이티브 컨트롤이 OS 를 따라가면 색이 반대로 나온다.
10. **`backend/alembic.ini` 는 ASCII 로 유지.** Alembic 이 시스템 로케일(cp949) 로 읽어서
    한글 주석을 넣으면 `UnicodeDecodeError` 로 죽는다. (다른 파이썬 파일은 한글 주석 OK)
11. **셸에는 캐시 헤더를 반드시 붙인다** (`main.py` 의 정적 서빙).
    `index.html`·`sw.js`·`manifest.webmanifest` = `no-cache`, 해시가 박힌 `assets/*` =
    `immutable`. 지우면 브라우저가 휴리스틱 캐싱으로 옛 셸을 붙잡고, 그 셸이 이미
    사라진 청크를 가리켜 **앱이 흰 화면이 된다** (iOS 홈 화면 웹앱에서 겪었다).
    `PUBLIC_ORIGIN` 이 있으면 다른 Host 의 **화면 요청만** 정규 주소로 307 —
    API·정적 파일까지 옮기면 CORS 로 조용히 깨지고 healthcheck 도 흔들린다.

## 4. 컨벤션

- **사용자 노출 문구는 전부 한국어.** 문구 표준은 CONTRACT.md §5.7, 톤은 DESIGN.md §5
  (느낌표 쓰지 않음).
- 주석은 한국어로, **왜 그런지**를 쓴다. 코드가 하는 일을 반복하지 않는다.
- 백엔드: SQLAlchemy 2.0 스타일(`select()`), Pydantic v2, 타입 힌트 필수.
- 프론트 페이지가 import 할 수 있는 것: `vue`, `vue-router`, `vuetify`(`useDisplay`/`useTheme` 만),
  `@/api/endpoints`, `@/api/types`, `@/utils/format`, `@/stores/*`.
  Vuetify 컴포넌트는 자동 import 되므로 직접 import 하지 않는다.
- 페이지에서 스타일을 새로 만들기 전에 `styles.css` 에 있는지 먼저 확인한다.
- 에러는 `appStore.toast(errorMessage(e), 'error')`. 페이지가 자체 스낵바를 만들지 않는다.
- 잔액 초과 사용은 409 → 사용자 확인 후 `allow_negative: true` 로 재요청하는 패턴.

## 5. 이 환경에서 겪는 함정 (Windows/PowerShell)

- **PowerShell 5.1**: 네이티브 명령(`docker`, `git`)의 출력을 파이프하면 exit 0 이어도
  `$?` 가 `$false` 가 된다. `if ($?)` 로 성공 판정하지 말 것.
- **`chrome --dump-dom` 은 Windows 에서 빈 출력**을 준다(콘솔에서 분리됨).
  화면 검증은 `--screenshot=<파일>` 또는 CDP(`--remote-debugging-port`)를 쓴다.
  Node 24 의 내장 `WebSocket` 으로 CDP 를 붙일 수 있어 추가 패키지가 필요 없다.
- 파이썬 스크립트가 이모지/한글을 출력하면 cp949 로 깨지거나 죽는다 →
  `$env:PYTHONIOENCODING='utf-8'`.
- `Invoke-WebRequest` 는 NonInteractive 에서 `-UseBasicParsing` 없이 실패한다.
  HTTP 검증은 파이썬 `httpx` 를 쓰는 편이 안전하다.
- 커밋되는 셸 스크립트는 `.gitattributes` 가 LF 로 고정한다(CRLF 면 컨테이너에서 깨진다).

## 6. 절대 하지 말 것

- `.env` 커밋 (공개 저장소다). **Qwen 서버 주소·JWT 시크릿·초대코드를 코드나 문서에
  하드코딩하지 말 것** — `.env` 의 `OCR_BASE_URL` 로만 주입한다.
- `backend/data/` 커밋 (구성원 계정 해시 + 영수증 이미지가 들어 있다).
- 잔액 컬럼 추가, 거래 하드 삭제, 금액을 float 로 다루기.
- `docs/CONTRACT.md` 와 다르게 구현하기 → 문서가 아니라 구현을 고치거나, 문서를 먼저 바꾼다.
