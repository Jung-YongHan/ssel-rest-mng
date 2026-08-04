<script setup lang="ts">
/**
 * 앱 셸 — 상단 바 + (데스크톱)탭 / (모바일)하단 내비 + 전역 스낵바.
 *
 * 로그인 화면에서는 모든 크롬을 숨긴다. 페이지는 자체 스낵바/앱바를 만들지 않는다.
 */
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/endpoints'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

type NavItem = { title: string; to: string; icon: string }

const route = useRoute()
const router = useRouter()
const { mdAndUp } = useDisplay()
const appStore = useAppStore()
const auth = useAuthStore()

/** 로그인 전 / 로그인 화면에서는 앱 셸을 숨긴다. */
const showChrome = computed(() => auth.isAuthenticated && route.path !== '/login')
const showBottomNav = computed(() => showChrome.value && !mdAndUp.value)

const desktopNav = computed<NavItem[]>(() => {
  const items: NavItem[] = [
    { title: '식당 목록', to: '/', icon: 'mdi-storefront-outline' },
    { title: '원장', to: '/ledger', icon: 'mdi-book-open-variant' },
    { title: '통계', to: '/stats', icon: 'mdi-chart-line' },
  ]
  if (auth.isAdmin) items.push({ title: '관리', to: '/admin', icon: 'mdi-shield-account-outline' })
  return items
})

const mobileNav: NavItem[] = [
  { title: '홈', to: '/', icon: 'mdi-home-outline' },
  { title: '스캔', to: '/scan', icon: 'mdi-camera-outline' },
  { title: '원장', to: '/ledger', icon: 'mdi-book-open-variant' },
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
})
</script>

<template>
  <v-app>
    <v-app-bar v-if="showChrome" color="primary" density="comfortable" flat>
      <v-app-bar-title class="flex-grow-0 me-2 me-md-6">
        <router-link to="/" class="plain-link d-inline-flex align-center" aria-label="홈으로">
          <v-icon icon="mdi-wallet-outline" class="me-2" />
          <span class="font-weight-bold text-no-wrap">연구실 선결제</span>
        </router-link>
      </v-app-bar-title>

      <v-tabs v-if="mdAndUp" :model-value="activeTab" density="comfortable">
        <v-tab
          v-for="item in desktopNav"
          :key="item.to"
          :value="item.to"
          :to="item.to"
          :prepend-icon="item.icon"
        >
          {{ item.title }}
        </v-tab>
      </v-tabs>

      <v-spacer />

      <v-menu location="bottom end">
        <template #activator="{ props: menuProps }">
          <v-btn v-bind="menuProps" variant="text" class="px-2">
            <v-icon icon="mdi-account-circle-outline" start />
            <span class="text-truncate" style="max-width: 8rem">{{ auth.user?.name }}</span>
            <v-icon icon="mdi-chevron-down" end />
          </v-btn>
        </template>

        <v-list density="compact" min-width="220">
          <v-list-item
            :title="auth.user?.name ?? ''"
            :subtitle="auth.user?.email ?? ''"
            prepend-icon="mdi-account-circle-outline"
          >
            <template #append>
              <v-chip v-if="auth.isAdmin" size="x-small" color="primary" variant="tonal">
                관리자
              </v-chip>
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
            v-if="!mdAndUp"
            to="/ledger"
            prepend-icon="mdi-book-open-variant"
            title="원장"
          />
          <v-list-item
            prepend-icon="mdi-logout"
            title="로그아웃"
            base-color="error"
            @click="onLogout"
          />
        </v-list>
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
      grow
      :mandatory="false"
    >
      <v-btn v-for="item in mobileNav" :key="item.to" :value="item.to" :to="item.to">
        <v-icon :icon="item.icon" />
        <span>{{ item.title }}</span>
      </v-btn>
    </v-bottom-navigation>

    <!-- 전역 스낵바 (CONTRACT §5.5) — 페이지는 이걸 통해서만 알림을 띄운다 -->
    <v-snackbar
      :key="appStore.toastKey"
      v-model="appStore.snackbar"
      :color="appStore.snackbarColor"
      :timeout="3500"
      location="top"
      multi-line
    >
      <span style="white-space: pre-line">{{ appStore.snackbarMessage }}</span>
      <template #actions>
        <v-btn variant="text" @click="appStore.snackbar = false">닫기</v-btn>
      </template>
    </v-snackbar>
  </v-app>
</template>

<style scoped>
.safe-bottom-spacer {
  height: env(safe-area-inset-bottom);
}
</style>
