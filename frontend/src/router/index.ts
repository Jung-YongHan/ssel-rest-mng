/**
 * 라우터 (CONTRACT §5.1).
 *
 * 모든 페이지는 lazy import 한다 — 첫 화면(홈)만 빠르게 뜨면 된다.
 * 가드: 미인증 → `/login?redirect=<path>`, `/admin` 은 admin 만.
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    /** 브라우저 탭 제목 (앱 이름 앞에 붙는다) */
    title?: string
    /** 로그인 없이 볼 수 있는 화면 */
    public?: boolean
    /** admin 전용 화면 */
    admin?: boolean
  }
}

const APP_TITLE = '연구실 선결제 관리'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { title: '로그인', public: true },
  },
  {
    path: '/',
    name: 'home',
    component: () => import('@/pages/HomePage.vue'),
    meta: { title: '선결제 식당' },
  },
  {
    path: '/scan',
    name: 'scan',
    component: () => import('@/pages/ScanPage.vue'),
    meta: { title: '영수증 스캔' },
  },
  {
    path: '/use',
    name: 'manual-use',
    component: () => import('@/pages/ManualUsePage.vue'),
    meta: { title: '영수증 없이 기록' },
  },
  {
    path: '/restaurants/new',
    name: 'restaurant-new',
    component: () => import('@/pages/RestaurantNewPage.vue'),
    meta: { title: '식당 직접 등록' },
  },
  {
    path: '/restaurants/:id',
    name: 'restaurant-detail',
    component: () => import('@/pages/RestaurantDetailPage.vue'),
    meta: { title: '식당 상세' },
  },
  {
    path: '/ledger',
    name: 'ledger',
    component: () => import('@/pages/LedgerPage.vue'),
    meta: { title: '원장' },
  },
  {
    path: '/stats',
    name: 'stats',
    component: () => import('@/pages/StatsPage.vue'),
    meta: { title: '통계' },
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/pages/AdminPage.vue'),
    meta: { title: '사용자 관리', admin: true },
  },
  { path: '/:pathMatch(.*)*', name: 'not-found', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (_to, _from, savedPosition) => savedPosition ?? { top: 0 },
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 앱 첫 진입: 쿠키가 살아있는지 서버에 한 번 물어본다.
  if (!auth.ready) await auth.fetchMe()

  if (!auth.isAuthenticated && !to.meta.public) {
    return {
      path: '/login',
      query: to.fullPath && to.fullPath !== '/' ? { redirect: to.fullPath } : {},
    }
  }

  if (auth.isAuthenticated && to.meta.public) {
    return { path: '/' }
  }

  if (to.meta.admin && !auth.isAdmin) {
    useAppStore().toast('관리자만 접근할 수 있습니다.', 'warning')
    return { path: '/' }
  }

  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · ${APP_TITLE}` : APP_TITLE
})

export default router
