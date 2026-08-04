# 디자인 규약 (DESIGN)

목표는 **"연구실 회계 도구"가 아니라 "사내 재무 시스템"처럼 보이는 것**이다.
절제된 중성 색조 + 하나의 브랜드 컬러 + 명확한 위계. 장식은 넣지 않는다.

구현체: `frontend/src/main.ts`(테마·컴포넌트 기본값), `frontend/src/styles.css`(토큰·유틸리티).
**이 문서와 어긋나는 화면이 있으면 화면을 고친다.**

---

## 0. 절대 규칙 (위반 시 토이 프로젝트처럼 보인다)

| 금지 | 대신 |
|---|---|
| **UI 에 이모지 사용** (📷 ✏️ 📍 ☎ ⚠️ ✅ 🧾) | `<v-icon icon="mdi-..." />` — §3 매핑표 |
| 그림자 있는 카드 (`elevation`) | 헤어라인 테두리 (`VCard` 기본값이 `variant="outlined"`) |
| 한 화면에 채운 버튼 2개 이상 | 주 동작 1개만 `variant="flat"`, 나머지 `tonal`/`outlined`/`text` |
| 원색 빨강/초록 꽉 채운 버튼 | `variant="tonal" color="error"` 처럼 톤으로 |
| 금액에 일반 숫자 | `class="amount"` (고정폭 숫자) — 자리수가 흔들리면 회계 화면이 아니다 |
| 회색 박스로 지표 나열 | `.metric-row` / `.metric-cell` (헤어라인으로 칸 분리) |
| 페이지마다 새 스타일 정의 | `styles.css` 의 유틸리티 재사용 |
| 임의 간격값 (`13px`, `mt-7`) | 4px 배수 · Vuetify 간격 클래스 (`pa-4`, `mb-3`) |

---

## 1. 색

`main.ts` 의 테마 토큰만 쓴다. 하드코딩한 hex 금지.

| 용도 | 토큰 |
|---|---|
| 브랜드 · 주 동작 | `primary` (딥 블루) |
| 보조 텍스트/동작 | `secondary`, `text-medium-emphasis` |
| **충전(입금)** | `success` — 딥 그린 |
| **사용(출금)** · 위험 | `error` — 딥 레드 |
| 잔액 부족 경고 | `warning` |
| 배경 / 카드 | `background` / `surface` |
| 흐린 라벨 | `on-surface-variant` |
| 히어로 면 (화면당 1개) | `hero` — 라이트=브랜드 블루, 다크=딥 네이비. `primary` 를 직접 채우면 다크에서 밝은 파랑이 크게 튄다 |

- 금액 색은 **부호가 있을 때만** 쓴다. 잔액이 정상이면 기본 잉크색(색 없음).
  음수면 `text-error`, 잔액 부족(임계값 미만)이면 `text-warning`.
- 큰 면적을 브랜드 컬러로 채우는 것은 **화면당 최대 1개**(홈의 총 잔액 카드).

## 2. 타이포그래피 · 레이아웃

| 클래스 | 용도 |
|---|---|
| `.page-title` | 화면 제목. 각 페이지 최상단에 **하나** |
| `.section-title` | 카드 묶음 위 섹션 제목 |
| `.field-label` | 지표/필드 라벨 (값보다 항상 작고 흐리게) |
| `.hint-text` | 보조 설명문 |
| `.amount` | 목록·표 안의 금액 |
| `.metric-value` | 카드 안 대표 숫자 |
| `.money-hero` | 화면 최상단 잔액 |
| `.flow-container` | 모바일 우선 플로우 화면 (720px) |
| `.wide-container` | PC 관리 화면 (1200px) — 원장/통계만 |

컨테이너 패턴:
```vue
<!-- 플로우 화면 (홈/스캔/사용/등록/상세) -->
<v-container class="flow-container pa-4">
<!-- 관리 화면 (원장/통계): 데스크톱에서 넓게 -->
<v-container :class="['pa-4', mdAndUp ? 'wide-container' : 'flow-container']">
```

- 카드 내부 패딩은 `pa-4`(16px) 기본. 카드 사이 간격 `mb-4`.
- 라벨 → 값 순서로 세로 배치. 값이 라벨보다 크고 진하다.

## 3. 아이콘 매핑 (이모지 전량 교체)

| 의미 | 아이콘 |
|---|---|
| 영수증 스캔/촬영 | `mdi-camera-outline` |
| 갤러리에서 선택 | `mdi-image-outline` |
| 영수증 없이 기록 | `mdi-pencil-outline` |
| 영수증(문서) | `mdi-receipt-text-outline` |
| 식당 · 목록 | `mdi-storefront-outline` |
| 주소 | `mdi-map-marker-outline` |
| 전화 | `mdi-phone-outline` |
| 사업자등록번호 | `mdi-card-account-details-outline` |
| 메모 | `mdi-note-text-outline` |
| **선결제 충전** | `mdi-arrow-down-circle-outline` (잔액 유입) |
| **사용/차감** | `mdi-arrow-up-circle-outline` (잔액 유출) |
| 정정(ADJUST) | `mdi-swap-vertical` |
| 기록 취소(void) | `mdi-close-circle-outline` |
| 잔액 부족 경고 | `mdi-alert-outline` |
| 완료/성공 | `mdi-check-circle-outline` |
| 원장 | `mdi-book-open-variant-outline` |
| 통계 | `mdi-chart-line` |
| 사용자 관리 | `mdi-shield-account-outline` |
| 식당 추가 | `mdi-plus` / `mdi-store-plus-outline` |
| 검색 | `mdi-magnify` |
| 필터 | `mdi-filter-variant` |
| 정렬 | `mdi-sort` |
| 새로 고침 | `mdi-refresh` |
| CSV 내보내기 | `mdi-tray-arrow-down` |
| 복사 | `mdi-content-copy` |
| 보기/숨기기 | `mdi-eye-outline` / `mdi-eye-off-outline` |
| 수정 | `mdi-pencil-outline` |
| 보관 | `mdi-archive-arrow-down-outline` |
| 뒤로 | `mdi-arrow-left` |
| 다음 단계 | `mdi-arrow-right` |
| 사용자 | `mdi-account-circle-outline` |
| 로그아웃 | `mdi-logout` |

아이콘은 **outline 계열로 통일**한다(채운 아이콘 섞지 않기). 버튼 안에서는
`<v-btn prepend-icon="mdi-...">`, 단독은 `<v-icon size="18" class="mr-1" />` 정도로 작게.

## 4. 컴포넌트 사용법

### 카드
```vue
<!-- 기본: 헤어라인 (VCard 기본값이므로 variant 를 적지 않는다) -->
<v-card class="pa-4 mb-4"> ... </v-card>

<!-- 히어로(화면당 1개): 브랜드 컬러 채움 -->
<v-card variant="flat" color="primary" class="pa-5 mb-4"> ... </v-card>

<!-- 은은한 강조 -->
<v-card variant="tonal" color="primary"> ... </v-card>
```
`elevation` 은 쓰지 않는다.

### 버튼 위계
```vue
<v-btn color="primary" size="large" block>주 동작</v-btn>          <!-- flat(기본) -->
<v-btn variant="tonal" color="primary">보조 동작</v-btn>
<v-btn variant="outlined">중립 동작</v-btn>
<v-btn variant="text">취소 / 부가</v-btn>
<v-btn variant="tonal" color="error">파괴적 동작</v-btn>
```
- 모바일 주 동작은 `size="large" block`.
- 아이콘만 있는 버튼은 `icon` + `variant="text"` + `aria-label` 필수.

### 칩 (거래 유형 등)
```vue
<v-chip :color="txColor(t.type)" size="small" variant="tonal">{{ txLabel(t.type) }}</v-chip>
```

### 지표 행
```vue
<v-card class="mb-4">
  <div class="metric-row">
    <div class="metric-cell">
      <div class="field-label">누적 충전</div>
      <div class="metric-value text-success amount">{{ won(r.charge_total) }}</div>
    </div>
    <div class="metric-cell">
      <div class="field-label">누적 사용</div>
      <div class="metric-value text-error amount">{{ won(r.use_total) }}</div>
    </div>
  </div>
</v-card>
```

### 빈 상태
아이콘(흐리게) + 한 줄 설명 + 다음 행동 버튼 하나. 느낌표·이모지 금지.
```vue
<v-card class="pa-8 text-center">
  <v-icon icon="mdi-storefront-outline" size="40" class="mb-3" style="opacity: 0.35" />
  <div class="text-body-2 text-medium-emphasis mb-4">아직 등록된 식당이 없습니다.</div>
  <v-btn color="primary" variant="tonal" prepend-icon="mdi-plus">식당 등록</v-btn>
</v-card>
```

### 로딩
`<v-skeleton-loader>` 로 최종 레이아웃과 같은 모양을 보여준다. 스피너 남용 금지.

### 표 (원장)
- 데스크톱: `<v-data-table-server>`, 숫자 컬럼에 `class="num-col"`, 유형은 칩.
- 모바일: 카드 목록 (`useDisplay()` 의 `mdAndUp` 로 분기).
- 표를 감싸는 카드는 `.table-scroll` 로 표만 가로 스크롤.

## 5. 문구 톤

- 기존 UI 문구 표준(`docs/CONTRACT.md` §5.7)은 **그대로 유지**한다. 단, 문구에 붙은
  이모지만 제거하고 아이콘으로 바꾼다. 예: `📷 영수증 스캔` → 아이콘 + `영수증 스캔`.
- 느낌표를 쓰지 않는다. "저장되었습니다" (O) / "저장 완료!" (X)
- 숫자는 항상 `won()` 등 포맷터를 통과시킨다.

## 6. 접근성

- 색만으로 의미를 전달하지 않는다(충전/사용은 색 + 아이콘 + 라벨).
- 아이콘 전용 버튼에 `aria-label`.
- 터치 타깃 최소 44px.
- 라이트/다크 양쪽에서 확인한다(테마 토큰만 쓰면 자동으로 따라온다).
