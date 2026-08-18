/**
 * 앱 부트스트랩 — Vuetify(테마/아이콘/한국어) + pinia + 라우터.
 *
 * 플러그인 순서 주의: pinia 를 먼저 install 해야 라우터 가드에서 스토어를 쓸 수 있다.
 * 디자인 규약은 docs/DESIGN.md 참고. 이 파일은 그 토큰의 구현체다.
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createVuetify, type ThemeDefinition } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import { en, ko } from 'vuetify/locale'

// 본문 폰트 (Pretendard) — 셀프호스팅. 웨이트는 3개만 쓴다(각 ~750KB).
import '@fontsource/pretendard/400.css'
import '@fontsource/pretendard/500.css'
import '@fontsource/pretendard/700.css'

import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import './styles.css'

import App from './App.vue'
import router from './router'

/** styles.css 의 --app-font fallback 과 같은 값을 유지할 것 */
const FONT_STACK =
  "Pretendard, 'Pretendard Variable', -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif"

/**
 * 팔레트 방향: 중성(ink/slate) 위주 + 브랜드 블루 하나를 아껴 쓴다.
 * 금액의 증감은 채도 높은 원색이 아니라 깊은 녹/적으로 표현해 회계 문서 톤을 유지한다.
 */
const lightTheme: ThemeDefinition = {
  dark: false,
  colors: {
    background: '#F5F6F8',
    surface: '#FFFFFF',
    'surface-bright': '#FFFFFF',
    'surface-light': '#F1F3F6',
    'surface-variant': '#EFF1F5',
    'on-surface-variant': '#5B6472',
    'on-surface': '#16191F',
    'on-background': '#16191F',

    primary: '#234E9E',
    'primary-darken-1': '#1B3D7C',
    'primary-lighten-1': '#3D68B8',
    secondary: '#5B6472',
    'secondary-darken-1': '#454C57',

    // 화면당 하나뿐인 '히어로' 면(홈의 총 잔액 카드) 전용.
    // 라이트에서는 브랜드 컬러 그대로, 다크에서는 딥 네이비로 낮춘다.
    hero: '#234E9E',

    success: '#176B3F', // 충전(입금)
    error: '#B3261E', // 사용(출금) · 위험
    warning: '#8A5A00', // 잔액 부족
    info: '#1B5E8A',
  },
  variables: {
    'border-color': '#0B1220',
    'border-opacity': 0.1,
    'high-emphasis-opacity': 0.94,
    'medium-emphasis-opacity': 0.66,
    'disabled-opacity': 0.36,
    'hover-opacity': 0.035,
    'activated-opacity': 0.05,
  },
}

const darkTheme: ThemeDefinition = {
  dark: true,
  colors: {
    background: '#0E1116',
    surface: '#161A21',
    'surface-bright': '#1E232C',
    'surface-light': '#1E232C',
    'surface-variant': '#232935',
    'on-surface-variant': '#A5AEBC',
    'on-surface': '#E6E9EF',
    'on-background': '#E6E9EF',

    primary: '#8FB3F2',
    'primary-darken-1': '#6E97E0',
    'primary-lighten-1': '#B3CBF7',
    secondary: '#9AA4B2',
    'secondary-darken-1': '#7C8695',

    // 다크에서 밝은 파랑을 크게 채우면 화면에서 과하게 튄다 → 딥 네이비
    hero: '#1B2B49',

    success: '#5FC98D',
    error: '#F2867E',
    warning: '#E0B057',
    info: '#7BC0E8',
  },
  variables: {
    'border-color': '#C7D2E4',
    'border-opacity': 0.14,
    'high-emphasis-opacity': 0.94,
    'medium-emphasis-opacity': 0.68,
    'disabled-opacity': 0.38,
    'hover-opacity': 0.06,
    'activated-opacity': 0.08,
  },
}

const prefersDark =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-color-scheme: dark)').matches

const vuetify = createVuetify({
  theme: {
    defaultTheme: prefersDark ? 'dark' : 'light',
    themes: { light: lightTheme, dark: darkTheme },
  },
  icons: { defaultSet: 'mdi', aliases, sets: { mdi } },
  locale: { locale: 'ko', fallback: 'en', messages: { ko, en } },
  defaults: {
    // 카드는 그림자 대신 1px 헤어라인 — 전 화면 통일 (docs/DESIGN.md)
    VCard: { variant: 'outlined', rounded: 'lg' },
    VSheet: { rounded: 'lg' },
    // 버튼은 기본 flat(그림자 없음). 강조 위계는 variant 로만 표현한다.
    VBtn: { variant: 'flat', rounded: 'lg', elevation: 0 },
    VChip: { variant: 'tonal', size: 'small', rounded: 'sm' },
    VAlert: { variant: 'tonal', rounded: 'lg', border: 'start' },
    VTextField: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VTextarea: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VSelect: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VAutocomplete: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VFileInput: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VDataTable: { density: 'comfortable' },
    VDataTableServer: { density: 'comfortable' },
    // 스크림 색은 **불투명**하게 준다. Vuetify 가 `.v-overlay__scrim` 에
    // `opacity: var(--v-overlay-opacity)` 를 한 번 더 곱하므로, 여기에 알파를 넣으면
    // 두 번 곱해져 거의 투명해진다. 농도는 styles.css 의 `--v-overlay-opacity`.
    VDialog: { scrim: '#0B1220' },
    VTooltip: { location: 'top' },
    VProgressLinear: { rounded: true, height: 6 },
    VSkeletonLoader: { boilerplate: false },
  },
})

// Vuetify 는 SASS 없이 폰트를 바꿀 수 없으므로 CSS 변수로 주입한다.
document.documentElement.style.setProperty('--app-font', FONT_STACK)

/*
 * 사라진 청크에 대한 안전망.
 *
 * 라우트를 전부 lazy import 하므로, 배포 직후 열려 있던 화면에서 다른 탭으로
 * 넘어가면 이미 지워진 해시 파일명을 요청해 빈 화면이 된다. 서비스워커가 있으면
 * 옛 프리캐시가 막아 주지만, 서비스워커를 못 쓰는 브라우저에는 방어가 없다.
 * 새 번들을 받도록 한 번만 새로고침한다.
 */
const CHUNK_RELOAD_KEY = 'ssel.chunkReloadAt'
const CHUNK_RELOAD_COOLDOWN_MS = 60_000

window.addEventListener('vite:preloadError', (event) => {
  try {
    // 방금 새로고침하고도 또 실패했다면 새로고침 루프다 — 그냥 에러를 보여준다.
    const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) ?? 0)
    if (Date.now() - last < CHUNK_RELOAD_COOLDOWN_MS) return
    sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
  } catch {
    // 저장소를 못 쓰면 루프를 막을 수 없으므로 새로고침하지 않는다.
    return
  }
  event.preventDefault() // 라우터로 에러를 흘리지 않고 여기서 처리한다
  window.location.reload()
})

createApp(App).use(createPinia()).use(vuetify).use(router).mount('#app')
