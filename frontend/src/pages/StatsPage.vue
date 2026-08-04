<script setup lang="ts">
/**
 * 통계 (CONTRACT §2.5).
 *
 * 요약 지표 → 잔액 부족 식당 → 월별 추이 → 식당별/구성원별 사용 분포.
 * 차트 라이브러리는 쓰지 않는다(`v-sparkline` / `v-progress-linear` 만 사용).
 * 디자인 규약은 docs/DESIGN.md — 통계는 데스크톱에서 `.wide-container`.
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import { statsApi, errorMessage } from '@/api/endpoints'
import type { MonthlyPoint, RestaurantStatRow, SummaryOut, UserStatRow } from '@/api/types'
import { dateTime, todayInput, txLabel, won, wonShort } from '@/utils/format'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const appStore = useAppStore()
const { mdAndUp } = useDisplay()

/* ------------------------------------------------------------------ */
/* 상태                                                                */
/* ------------------------------------------------------------------ */

const summary = ref<SummaryOut | null>(null)
const monthly = ref<MonthlyPoint[]>([])
const byRestaurant = ref<RestaurantStatRow[]>([])
const byUser = ref<UserStatRow[]>([])

const loadingSummary = ref(true)
const loadingMonthly = ref(true)
const loadingBreakdown = ref(true)

const dateFrom = ref('')
const dateTo = ref('')

/* ------------------------------------------------------------------ */
/* 파생 값                                                             */
/* ------------------------------------------------------------------ */

const chargeValues = computed(() => monthly.value.map((p) => p.charge))
const useValues = computed(() => monthly.value.map((p) => p.use))
const monthLabels = computed(() =>
  monthly.value.map((p) => String(Number(p.month.slice(5, 7))) + '월'),
)
const canDrawCharge = computed(
  () => monthly.value.length >= 2 && chargeValues.value.some((v) => v > 0),
)
const canDrawUse = computed(() => monthly.value.length >= 2 && useValues.value.some((v) => v > 0))

const restaurantRows = computed(() =>
  byRestaurant.value.slice().sort((a, b) => b.use - a.use),
)
const userRows = computed(() => byUser.value.slice().sort((a, b) => b.use - a.use))
const restaurantMax = computed(() =>
  restaurantRows.value.reduce((m, r) => Math.max(m, r.use), 0),
)
const userMax = computed(() => userRows.value.reduce((m, r) => Math.max(m, r.use), 0))

const periodLabel = computed(() => {
  if (!dateFrom.value && !dateTo.value) return '전체 기간'
  return `${dateFrom.value || '처음'} ~ ${dateTo.value || '오늘'}`
})

/** 총 잔액은 음수일 때만 색을 쓴다 (DESIGN §1). */
const totalBalanceClass = computed(() =>
  summary.value && summary.value.total_balance < 0 ? 'text-error' : '',
)

/** 요약 지표 — 좁은 화면에서는 2칸씩 두 줄로 나눈다. */
const summaryMetrics = computed(() => {
  const s = summary.value
  if (!s) return []
  return [
    { label: '등록 식당', value: `${s.restaurant_count}곳`, cls: '' },
    {
      label: '잔액 부족',
      value: `${s.low_balance_count}곳`,
      cls: s.low_balance_count > 0 ? 'text-warning' : '',
    },
    { label: '이번 달 충전', value: won(s.month_charge), cls: 'text-success' },
    { label: '이번 달 사용', value: won(s.month_use), cls: 'text-error' },
  ]
})

const metricRows = computed(() => {
  const m = summaryMetrics.value
  return mdAndUp.value ? [m] : [m.slice(0, 2), m.slice(2)]
})

function share(value: number, max: number): number {
  if (max <= 0) return 0
  return Math.round((value / max) * 100)
}

/** 잔액 부족 목록의 금액 색 — 음수는 error, 그 외에는 warning */
function lowBalanceClass(balance: number): string {
  return balance < 0 ? 'text-error' : 'text-warning'
}

/* ------------------------------------------------------------------ */
/* 로드                                                                */
/* ------------------------------------------------------------------ */

async function loadSummary() {
  loadingSummary.value = true
  try {
    summary.value = await statsApi.summary()
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    loadingSummary.value = false
  }
}

async function loadMonthly() {
  loadingMonthly.value = true
  try {
    const res = await statsApi.monthly(12)
    monthly.value = res.items
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    loadingMonthly.value = false
  }
}

async function loadBreakdown() {
  loadingBreakdown.value = true
  const params = {
    date_from: dateFrom.value || undefined,
    date_to: dateTo.value || undefined,
  }
  try {
    const [r, u] = await Promise.all([statsApi.byRestaurant(params), statsApi.byUser(params)])
    byRestaurant.value = r.items
    byUser.value = u.items
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    loadingBreakdown.value = false
  }
}

function resetRange() {
  dateFrom.value = ''
  dateTo.value = ''
  loadBreakdown()
}

function thisYear() {
  const y = todayInput().slice(0, 4)
  dateFrom.value = `${y}-01-01`
  dateTo.value = `${y}-12-31`
  loadBreakdown()
}

function goRestaurant(id: number) {
  router.push(`/restaurants/${id}`)
}

onMounted(() => {
  loadSummary()
  loadMonthly()
  loadBreakdown()
})
</script>

<template>
  <v-container :class="['pa-4', mdAndUp ? 'wide-container' : 'flow-container']">
    <h1 class="page-title mb-4">통계</h1>

    <!-- ── 요약 ────────────────────────────────────────────────── -->
    <v-skeleton-loader v-if="loadingSummary && !summary" type="card" class="mb-4" />

    <template v-else-if="summary">
      <v-row class="mb-3">
        <v-col cols="12" md="4">
          <v-card class="pa-4 h-100">
            <div class="field-label">총 잔액</div>
            <div class="money-hero amount mt-1" :class="totalBalanceClass">
              {{ won(summary.total_balance) }}
            </div>
            <div class="hint-text mt-2">
              잔액 부족 기준 {{ won(summary.low_balance_threshold) }}
            </div>
          </v-card>
        </v-col>

        <v-col cols="12" md="8">
          <v-card class="h-100 d-flex flex-column">
            <!-- 옆 카드와 높이를 맞추므로 남는 높이를 지표 행이 채우게 한다 (칸 구분선이 끝까지) -->
            <div class="divided flex-grow-1 d-flex flex-column">
              <div v-for="(row, i) in metricRows" :key="i" class="metric-row flex-grow-1">
                <div
                  v-for="metric in row"
                  :key="metric.label"
                  class="metric-cell d-flex flex-column justify-center"
                >
                  <div class="field-label">{{ metric.label }}</div>
                  <div class="metric-value amount" :class="metric.cls">{{ metric.value }}</div>
                </div>
              </div>
            </div>
            <v-divider />
            <div class="px-4 py-2 hint-text">
              이번 달 {{ summary.month }} · 누적 충전 {{ won(summary.all_time_charge) }} · 누적 사용
              {{ won(summary.all_time_use) }}
            </div>
          </v-card>
        </v-col>
      </v-row>

      <!-- ── 잔액 부족 식당 ───────────────────────────────────── -->
      <h2 class="section-title mb-2">잔액 부족 식당</h2>

      <v-card v-if="summary.low_balance_restaurants.length === 0" class="pa-8 text-center mb-6">
        <v-icon icon="mdi-check-circle-outline" size="40" class="mb-3" style="opacity: 0.35" />
        <div class="text-body-2 text-medium-emphasis">잔액이 부족한 식당이 없습니다.</div>
      </v-card>

      <v-card v-else class="mb-6">
        <div class="divided">
          <div
            v-for="r in summary.low_balance_restaurants"
            :key="r.id"
            class="pa-4 pressable d-flex align-center ga-3"
            @click="goRestaurant(r.id)"
          >
            <v-icon icon="mdi-alert-outline" size="18" color="warning" class="flex-shrink-0" />

            <div class="flex-grow-1 overflow-hidden">
              <div class="text-body-2 font-weight-medium text-truncate">{{ r.name }}</div>
              <div class="hint-text">
                마지막 사용 {{ r.last_used_at ? dateTime(r.last_used_at) : '없음' }}
              </div>
            </div>

            <div class="amount text-right flex-shrink-0" :class="lowBalanceClass(r.balance)">
              {{ won(r.balance) }}
            </div>
            <v-icon icon="mdi-chevron-right" size="18" class="text-medium-emphasis flex-shrink-0" />
          </div>
        </div>
      </v-card>
    </template>

    <!-- ── 월별 추이 ───────────────────────────────────────────── -->
    <div class="d-flex align-center justify-space-between mb-2">
      <h2 class="section-title">월별 추이</h2>
      <span class="hint-text">최근 12개월</span>
    </div>

    <v-skeleton-loader v-if="loadingMonthly && monthly.length === 0" type="card" class="mb-4" />

    <v-card v-else-if="monthly.length === 0" class="pa-8 text-center mb-6">
      <v-icon icon="mdi-chart-line" size="40" class="mb-3" style="opacity: 0.35" />
      <div class="text-body-2 text-medium-emphasis">아직 집계할 거래가 없습니다.</div>
    </v-card>

    <template v-else>
      <v-row class="mb-1">
        <v-col cols="12" md="6">
          <v-card class="pa-4 h-100">
            <div class="d-flex align-center ga-2 mb-3">
              <v-icon icon="mdi-arrow-down-circle-outline" size="16" color="success" />
              <span class="section-title">{{ txLabel('CHARGE') }}</span>
            </div>
            <v-sparkline
              v-if="canDrawCharge"
              :model-value="chargeValues"
              :labels="monthLabels"
              :padding="16"
              :line-width="2"
              :smooth="6"
              height="80"
              label-size="7"
              show-labels
              auto-draw
              color="success"
            />
            <div v-else class="hint-text py-4 text-center">충전 기록이 없습니다.</div>
          </v-card>
        </v-col>

        <v-col cols="12" md="6">
          <v-card class="pa-4 h-100">
            <div class="d-flex align-center ga-2 mb-3">
              <v-icon icon="mdi-arrow-up-circle-outline" size="16" color="error" />
              <span class="section-title">{{ txLabel('USE') }}</span>
            </div>
            <v-sparkline
              v-if="canDrawUse"
              :model-value="useValues"
              :labels="monthLabels"
              :padding="16"
              :line-width="2"
              :smooth="6"
              height="80"
              label-size="7"
              show-labels
              auto-draw
              color="error"
            />
            <div v-else class="hint-text py-4 text-center">사용 기록이 없습니다.</div>
          </v-card>
        </v-col>
      </v-row>

      <v-card class="mb-6 table-scroll">
        <v-table density="compact">
          <thead>
            <tr>
              <th class="field-label text-left">월</th>
              <th class="field-label num-col">충전</th>
              <th class="field-label num-col">사용</th>
              <th class="field-label num-col">순액</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in monthly" :key="p.month">
              <td class="text-no-wrap">{{ p.month }}</td>
              <td class="num-col amount text-success">{{ wonShort(p.charge) }}</td>
              <td class="num-col amount text-error">{{ wonShort(p.use) }}</td>
              <td class="num-col amount" :class="p.net < 0 ? 'text-error' : ''">
                {{ wonShort(p.net) }}
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card>
    </template>

    <!-- ── 식당별 · 구성원별 ───────────────────────────────────── -->
    <h2 class="section-title mb-1">식당별 · 구성원별</h2>
    <div class="hint-text mb-3">{{ periodLabel }} · 사용액 기준 정렬</div>

    <v-card class="pa-4 mb-4">
      <v-row dense align="end">
        <v-col cols="6" md="3">
          <div class="field-label mb-1">시작일</div>
          <v-text-field v-model="dateFrom" type="date" />
        </v-col>
        <v-col cols="6" md="3">
          <div class="field-label mb-1">종료일</div>
          <v-text-field v-model="dateTo" type="date" />
        </v-col>
        <v-col cols="12" md="6" class="d-flex flex-wrap ga-2 justify-md-end">
          <v-btn
            color="primary"
            class="flex-grow-1 flex-md-grow-0"
            :loading="loadingBreakdown"
            @click="loadBreakdown"
          >
            적용
          </v-btn>
          <v-btn variant="outlined" class="flex-grow-1 flex-md-grow-0" @click="thisYear">
            올해
          </v-btn>
          <v-btn variant="text" class="flex-grow-1 flex-md-grow-0" @click="resetRange">
            전체
          </v-btn>
        </v-col>
      </v-row>
    </v-card>

    <v-row class="mb-0">
      <!-- 식당별 -->
      <v-col cols="12" md="6">
        <h3 class="section-title mb-2">식당별</h3>

        <v-skeleton-loader
          v-if="loadingBreakdown && restaurantRows.length === 0"
          type="list-item-two-line, list-item-two-line"
        />

        <v-card v-else-if="restaurantRows.length === 0" class="pa-8 text-center">
          <v-icon icon="mdi-storefront-outline" size="40" class="mb-3" style="opacity: 0.35" />
          <div class="text-body-2 text-medium-emphasis mb-4">
            해당 기간에 집계할 식당이 없습니다.
          </div>
          <v-btn variant="tonal" color="primary" @click="resetRange">전체 기간 보기</v-btn>
        </v-card>

        <v-card v-else>
          <div class="divided">
            <div
              v-for="r in restaurantRows"
              :key="r.restaurant_id"
              class="pa-4 pressable"
              @click="goRestaurant(r.restaurant_id)"
            >
              <div class="d-flex align-center ga-3">
                <span class="text-body-2 font-weight-medium flex-grow-1 text-truncate">
                  {{ r.name }}
                </span>
                <span class="amount text-error flex-shrink-0">{{ won(r.use) }}</span>
              </div>
              <v-progress-linear
                :model-value="share(r.use, restaurantMax)"
                color="error"
                height="6"
                rounded
                class="mt-2"
              />
              <div class="hint-text mt-2">
                충전 {{ won(r.charge) }} · 잔액 {{ won(r.balance) }}
              </div>
            </div>
          </div>
        </v-card>
      </v-col>

      <!-- 구성원별 -->
      <v-col cols="12" md="6">
        <h3 class="section-title mb-2">구성원별</h3>

        <v-skeleton-loader
          v-if="loadingBreakdown && userRows.length === 0"
          type="list-item-two-line, list-item-two-line"
        />

        <v-card v-else-if="userRows.length === 0" class="pa-8 text-center">
          <v-icon icon="mdi-account-circle-outline" size="40" class="mb-3" style="opacity: 0.35" />
          <div class="text-body-2 text-medium-emphasis mb-4">
            해당 기간에 집계할 기록이 없습니다.
          </div>
          <v-btn variant="tonal" color="primary" @click="resetRange">전체 기간 보기</v-btn>
        </v-card>

        <v-card v-else>
          <div class="divided">
            <div
              v-for="(u, i) in userRows"
              :key="u.user_id === null ? 'none-' + i : u.user_id"
              class="pa-4"
            >
              <div class="d-flex align-center ga-3">
                <span class="text-body-2 font-weight-medium flex-grow-1 text-truncate">
                  {{ u.name }}
                </span>
                <span class="amount text-error flex-shrink-0">{{ won(u.use) }}</span>
              </div>
              <v-progress-linear
                :model-value="share(u.use, userMax)"
                color="primary"
                height="6"
                rounded
                class="mt-2"
              />
              <div class="hint-text mt-2">
                충전 {{ won(u.charge) }} · 기록 {{ u.tx_count }}건
              </div>
            </div>
          </div>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
