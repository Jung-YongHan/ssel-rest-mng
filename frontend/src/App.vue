<script setup lang="ts">
/**
 * 앱 셸 — 상단 바 + (데스크톱)탭 / (모바일)하단 내비 + 전역 스낵바.
 *
 * 로그인 화면에서는 모든 크롬을 숨긴다. 페이지는 자체 스낵바/앱바를 만들지 않는다.
 * 디자인 규약: docs/DESIGN.md — 상단 바는 브랜드 컬러로 채우지 않고
 * 표면색 + 헤어라인으로 처리해 '문서/업무 도구' 톤을 유지한다.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay, useTheme } from 'vuetify'

import { errorMessage } from '@/api/endpoints'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

type NavItem = { title: string; to: string; icon: string }

const THEME_KEY = 'ssel.theme'

const route = useRoute()
const router = useRouter()
const { mdAndUp } = useDisplay()
const theme = useTheme()
const appStore = useAppStore()
const auth = useAuthStore()

/** 로그인 전 / 로그인 화면에서는 앱 셸을 숨긴다. */
const showChrome = computed(() => auth.isAuthenticated && route.path !== '/login')
const showBottomNav = computed(() => showChrome.value && !mdAndUp.value)

const desktopNav = computed<NavItem[]>(() => {
  const items: NavItem[] = [
    { title: '식당 목록', to: '/', icon: 'mdi-storefront-outline' },
    { title: '원장', to: '/ledger', icon: 'mdi-book-open-variant-outline' },
    { title: '통계', to: '/stats', icon: 'mdi-chart-line' },
  ]
  if (auth.isAdmin) items.push({ title: '관리', to: '/admin', icon: 'mdi-shield-account-outline' })
  return items
})

const mobileNav: NavItem[] = [
  { title: '식당', to: '/', icon: 'mdi-storefront-outline' },
  { title: '스캔', to: '/scan', icon: 'mdi-camera-outline' },
  { title: '원장', to: '/ledger', icon: 'mdi-book-open-variant-outline' },
  { title: '통계', to: '/stats', icon: 'mdi-chart-line' },
]

/** 현재 경로에 해당하는 내비 항목 값 (없으면 아무것도 선택하지 않는다) */
function activeValue(items: NavItem[]): string | undefined {
  const path = route.path
  const exact = items.find((item) => item.to === path)
  if (exact) return exact.to
  const prefixed = items.find((item) => item.to !== '/' && path.startsWith(item.to))
  if (prefixed) return prefixed.to
  // 식당 상세/등록은 '식당 목록' 탭으로 묶는다.
  if (path.startsWith('/restaurants')) return '/'
  return undefined
}

const activeTab = computed(() => activeValue(desktopNav.value))
const activeBottom = computed(() => activeValue(mobileNav))

/* ── 테마 (사용자 선택을 기억한다) ────────────────────────────────*/
const isDark = ref(theme.global.current.value.dark)

const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(THEME_KEY) : null
if (stored === 'dark' || stored === 'light') {
  isDark.value = stored === 'dark'
}

watch(
  isDark,
  (dark) => {
    theme.change(dark ? 'dark' : 'light')
    // 브라우저 기본 UI(네이티브 날짜 선택기·자동완성·스크롤바)와 기본 글자색이
    // OS 설정이 아니라 **앱 테마**를 따르게 한다. index.html 의
    // `color-scheme: light dark` 는 첫 페인트용이고, 앱 테마를 라이트로 바꿔 둔
    // 사용자가 OS 는 다크인 상태면 둘이 어긋나 네이티브 요소가 반대로 그려진다.
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
    try {
      localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light')
    } catch {
      /* 시크릿 모드 등에서 저장 실패는 무시 */
    }
  },
  { immediate: true },
)

async function onLogout(): Promise<void> {
  try {
    await auth.logout()
    appStore.toast('로그아웃되었습니다.', 'success')
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    await router.replace('/login')
  }
}

onMounted(() => {
  void appStore.loadHealth()
  // 홈 화면 PWA 에는 새로고침 수단이 없다 → 앱이 스스로 새 버전을 확인한다.
  void appStore.initAppUpdates()
})

// 홈 화면 설치 안내 — 로그인한 모바일 화면에서만, 세션당 한 번 즉시.
// 데스크톱(mdAndUp)은 홈 화면 개념이 약하므로 안내하지 않는다.
// 다이얼로그 자체는 스토어 상태로 그려지므로, 표시 방식을 바꾸려면 이 지점만 고치면 된다.
watch(
  () => showChrome.value && !mdAndUp.value,
  (eligible) => {
    if (eligible) appStore.maybeShowInstallGuide()
  },
  { immediate: true },
)
</script>

<template>
  <v-app>
    <v-app-bar
      v-if="showChrome"
      class="app-bar--flat"
      color="surface"
      density="comfortable"
      flat
    >
      <v-app-bar-title class="flex-grow-0 me-2 me-md-8">
        <router-link to="/" class="plain-link d-inline-flex align-center" aria-label="홈으로">
          <span class="brand-mark">
            <v-icon icon="mdi-wallet-outline" size="17" />
          </span>
          <span class="brand-text text-no-wrap">연구실 선결제</span>
        </router-link>
      </v-app-bar-title>

      <v-tabs v-if="mdAndUp" :model-value="activeTab" density="comfortable" color="primary">
        <v-tab
          v-for="item in desktopNav"
          :key="item.to"
          :value="item.to"
          :to="item.to"
          :prepend-icon="item.icon"
          class="text-body-2"
        >
          {{ item.title }}
        </v-tab>
      </v-tabs>

      <v-spacer />

      <v-btn
        :icon="isDark ? 'mdi-weather-night' : 'mdi-weather-sunny'"
        variant="text"
        density="comfortable"
        :aria-label="isDark ? '밝은 테마로 전환' : '어두운 테마로 전환'"
        @click="isDark = !isDark"
      />

      <v-menu location="bottom end">
        <template #activator="{ props: menuProps }">
          <v-btn v-bind="menuProps" variant="text" class="px-2" density="comfortable">
            <v-icon icon="mdi-account-circle-outline" start />
            <span class="text-truncate text-body-2" style="max-width: 8rem">
              {{ auth.user?.name }}
            </span>
            <v-icon icon="mdi-chevron-down" end size="16" />
          </v-btn>
        </template>

        <v-card min-width="248">
          <v-list density="compact" class="py-1">
            <v-list-item
              :title="auth.user?.name ?? ''"
              :subtitle="auth.user?.email ?? ''"
              prepend-icon="mdi-account-circle-outline"
            >
              <template #append>
                <v-chip v-if="auth.isAdmin" size="x-small" color="primary">관리자</v-chip>
              </template>
            </v-list-item>

            <v-divider class="my-1" />

            <v-list-item
              v-if="auth.isAdmin && !mdAndUp"
              to="/admin"
              prepend-icon="mdi-shield-account-outline"
              title="사용자 관리"
            />
            <v-list-item
              prepend-icon="mdi-logout"
              title="로그아웃"
              base-color="error"
              @click="onLogout"
            />
          </v-list>
        </v-card>
      </v-menu>
    </v-app-bar>

    <v-main>
      <router-view />
      <!-- 하단 내비 + iOS 홈바 만큼 여백 확보 -->
      <div v-if="showBottomNav" class="safe-bottom-spacer" />
    </v-main>

    <v-bottom-navigation
      v-if="showBottomNav"
      :model-value="activeBottom"
      color="primary"
      bg-color="surface"
      grow
      :mandatory="false"
      elevation="0"
    >
      <v-btn v-for="item in mobileNav" :key="item.to" :value="item.to" :to="item.to">
        <v-icon :icon="item.icon" size="21" />
        <span class="text-caption">{{ item.title }}</span>
      </v-btn>
    </v-bottom-navigation>

    <!-- 전역 스낵바 (CONTRACT §5.5) — 페이지는 이걸 통해서만 알림을 띄운다 -->
    <v-snackbar
      :key="appStore.toastKey"
      v-model="appStore.snackbar"
      :color="appStore.snackbarColor"
      :timeout="3500"
      location="top"
      rounded="lg"
      multi-line
    >
      <span style="white-space: pre-line">{{ appStore.snackbarMessage }}</span>
      <template #actions>
        <v-btn variant="text" @click="appStore.snackbar = false">닫기</v-btn>
      </template>
    </v-snackbar>

    <!-- 새 버전 안내 — 스스로 사라지지 않는다(timeout -1). 위쪽 스낵바는 잠깐 뜨는
         알림용이라 겹치지 않게 아래에 둔다. 하단 내비가 있으면 그만큼 띄운다. -->
    <v-snackbar
      v-model="appStore.updateReady"
      :timeout="-1"
      location="bottom"
      :class="showBottomNav ? 'mb-16' : ''"
      rounded="lg"
      multi-line
    >
      <div class="d-flex align-center ga-2">
        <v-icon icon="mdi-refresh" size="20" />
        <span>새 버전이 있습니다.</span>
      </div>
      <template #actions>
        <v-btn variant="text" @click="appStore.applyUpdate()">업데이트</v-btn>
        <v-btn variant="text" @click="appStore.updateReady = false">나중에</v-btn>
      </template>
    </v-snackbar>

    <!-- 홈 화면 설치 안내 — 모바일 로그인 직후 한 번, 닫으면 7일 스누즈 (stores/app.ts).
         iOS 는 자동 설치 API 가 없어 단계 안내, Android(크롬 계열)는 네이티브 설치 창 호출.
         문구가 Safari 를 지명하지 않는 이유: iOS 16.4+ 의 Chrome 도 같은 경로로 동작한다. -->
    <v-dialog v-model="appStore.installGuideOpen" max-width="420">
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-cellphone-arrow-down" color="primary" size="20" class="me-2" />
          <span class="section-title">홈 화면에 추가</span>
        </v-card-title>
        <v-card-text>
          <div class="text-body-2">홈 화면에 추가하면 앱처럼 전체 화면으로 바로 열 수 있습니다.</div>
          <template v-if="appStore.installPlatform === 'ios'">
            <div class="d-flex align-center ga-2 mt-3 text-body-2">
              <v-icon icon="mdi-export-variant" size="18" />
              <span>브라우저의 공유 버튼을 누릅니다.</span>
            </div>
            <div class="d-flex align-center ga-2 mt-2 text-body-2">
              <v-icon icon="mdi-plus-box-outline" size="18" />
              <span>'홈 화면에 추가'를 선택합니다.</span>
            </div>
            <div class="d-flex align-center ga-2 mt-2 text-body-2">
              <v-icon icon="mdi-check-circle-outline" size="18" />
              <span>오른쪽 위 '추가'를 누르면 완료됩니다.</span>
            </div>
          </template>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="appStore.installGuideOpen = false">나중에</v-btn>
          <v-btn
            v-if="appStore.installPlatform === 'android'"
            color="primary"
            variant="tonal"
            @click="appStore.promptInstall()"
          >
            설치
          </v-btn>
          <v-btn
            v-else
            color="primary"
            variant="tonal"
            @click="appStore.installGuideOpen = false"
          >
            확인
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-app>
</template>

<style scoped>
.safe-bottom-spacer {
  height: env(safe-area-inset-bottom);
}

/* 워드마크 앞의 작은 브랜드 사각형 — 로고 대용 */
.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-inline-end: 10px;
  border-radius: 8px;
  background: rgb(var(--v-theme-primary));
  color: rgb(var(--v-theme-on-primary, 255, 255, 255));
}

.brand-text {
  font-size: 0.9375rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}
</style>
