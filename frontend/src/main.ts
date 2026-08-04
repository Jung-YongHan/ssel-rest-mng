/**
 * 앱 부트스트랩 — Vuetify(테마/아이콘/한국어) + pinia + 라우터.
 *
 * 플러그인 순서 주의: pinia 를 먼저 install 해야 라우터 가드에서 스토어를 쓸 수 있다.
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createVuetify, type ThemeDefinition } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import { en, ko } from 'vuetify/locale'

import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import './styles.css'

import App from './App.vue'
import router from './router'

/** 한국어 본문에 어울리는 기본 폰트 스택 (styles.css 의 --app-font 와 동일하게 유지) */
const FONT_STACK =
  "'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif"

const lightTheme: ThemeDefinition = {
  dark: false,
  colors: {
    background: '#F4F5F9',
    surface: '#FFFFFF',
    'surface-bright': '#FFFFFF',
    primary: '#3F51B5',
    'primary-darken-1': '#303F9F',
    secondary: '#5C6BC0',
    success: '#2E7D32',
    error: '#C62828',
    warning: '#EF6C00',
    info: '#0277BD',
  },
}

const darkTheme: ThemeDefinition = {
  dark: true,
  colors: {
    background: '#121212',
    surface: '#1E1E1E',
    primary: '#9FA8DA',
    'primary-darken-1': '#7986CB',
    secondary: '#7986CB',
    success: '#66BB6A',
    error: '#EF5350',
    warning: '#FFA726',
    info: '#4FC3F7',
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
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi },
  },
  locale: {
    locale: 'ko',
    fallback: 'en',
    messages: { ko, en },
  },
  defaults: {
    VCard: { rounded: 'lg' },
    VBtn: { rounded: 'lg' },
    VChip: { rounded: 'lg' },
    VAlert: { variant: 'tonal', rounded: 'lg' },
    VTextField: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VTextarea: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VSelect: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VAutocomplete: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VFileInput: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
  },
})

// Vuetify 는 SASS 없이 폰트를 바꿀 수 없으므로 CSS 변수로 주입한다.
// (styles.css 가 `var(--app-font, ...)` 로 소비한다)
document.documentElement.style.setProperty('--app-font', FONT_STACK)

createApp(App).use(createPinia()).use(vuetify).use(router).mount('#app')
