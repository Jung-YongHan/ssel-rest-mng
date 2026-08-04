<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { statsApi, errorMessage } from '@/api/endpoints'
import type { MonthlyPoint, RestaurantStatRow, SummaryOut, UserStatRow } from '@/api/types'
import { dateTime, todayInput, txColor, txLabel, won, wonShort } from '@/utils/format'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const appStore = useAppStore()

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

function share(value: number, max: number): number {
  if (max <= 0) return 0
  return Math.round((value / max) * 100)
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
  <v-container class="pa-3" style="max-width: 720px">
    <h1 class="text-h6 mb-3">통계</h1>

    <!-- 요약 카드 -->
    <v-skeleton-loader v-if="loadingSummary && !summary" type="card" class="mb-4" />
    <template v-else-if="summary">
      <v-row dense class="mb-1">
        <v-col cols="6">
          <v-card variant="tonal">
            <v-card-text class="py-3">
              <div class="text-caption text-medium-emphasis">총 잔액</div>
              <div
                class="text-h6 font-weight-bold"
                :class="summary.total_balance < 0 ? 'text-error' : 'text-primary'"
              >
                {{ won(summary.total_balance) }}
              </div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="6">
          <v-card variant="tonal">
            <v-card-text class="py-3">
              <div class="text-caption text-medium-emphasis">등록 식당</div>
              <div class="text-h6 font-weight-bold">{{ summary.restaurant_count }}곳</div>
              <div class="text-caption text-medium-emphasis">
                잔액 부족 {{ summary.low_balance_count }}곳
              </div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="6">
          <v-card variant="tonal">
            <v-card-text class="py-3">
              <div class="text-caption text-medium-emphasis">이번 달 충전</div>
              <div class="text-h6 font-weight-bold text-success">
                {{ won(summary.month_charge) }}
              </div>
              <div class="text-caption text-medium-emphasis">{{ summary.month }}</div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="6">
          <v-card variant="tonal">
            <v-card-text class="py-3">
              <div class="text-caption text-medium-emphasis">이번 달 사용</div>
              <div class="text-h6 font-weight-bold text-error">{{ won(summary.month_use) }}</div>
              <div class="text-caption text-medium-emphasis">{{ summary.month }}</div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <div class="text-caption text-medium-emphasis mb-4">
        누적 충전 {{ won(summary.all_time_charge) }} · 누적 사용 {{ won(summary.all_time_use) }} ·
        잔액 부족 기준 {{ won(summary.low_balance_threshold) }}
      </div>
    </template>

    <!-- 잔액 부족 식당 -->
    <template v-if="summary">
      <h2 class="text-subtitle-1 font-weight-bold mb-2">잔액 부족 식당</h2>
      <v-alert
        v-if="summary.low_balance_restaurants.length === 0"
        type="success"
        variant="tonal"
        class="mb-4"
      >
        잔액이 부족한 식당이 없습니다.
      </v-alert>
      <v-card v-else variant="outlined" class="mb-4">
        <v-list>
          <v-list-item
            v-for="r in summary.low_balance_restaurants"
            :key="r.id"
            @click="goRestaurant(r.id)"
          >
            <v-list-item-title>{{ r.name }}</v-list-item-title>
            <v-list-item-subtitle>
              마지막 사용 {{ r.last_used_at ? dateTime(r.last_used_at) : '없음' }}
            </v-list-item-subtitle>
            <template #append>
              <span class="font-weight-bold" :class="r.balance < 0 ? 'text-error' : 'text-warning'">
                {{ won(r.balance) }}
              </span>
            </template>
          </v-list-item>
        </v-list>
      </v-card>
    </template>

    <v-divider class="my-4" />

    <!-- 월별 추이 -->
    <h2 class="text-subtitle-1 font-weight-bold mb-2">월별 추이 (최근 12개월)</h2>
    <v-skeleton-loader v-if="loadingMonthly && monthly.length === 0" type="card" class="mb-4" />
    <v-alert v-else-if="monthly.length === 0" type="info" variant="tonal" class="mb-4">
      아직 집계할 거래가 없습니다.
    </v-alert>
    <template v-else>
      <v-card variant="outlined" class="mb-3">
        <v-card-text>
          <div class="text-caption text-medium-emphasis mb-1">
            <v-chip size="x-small" :color="txColor('CHARGE')" variant="flat" class="mr-1">
              {{ txLabel('CHARGE') }}
            </v-chip>
          </div>
          <v-sparkline
            v-if="canDrawCharge"
            :model-value="chargeValues"
            :labels="monthLabels"
            :padding="12"
            :line-width="2"
            :smooth="6"
            label-size="5"
            show-labels
            auto-draw
            color="success"
          />
          <div v-else class="text-body-2 text-medium-emphasis">충전 기록이 없습니다.</div>
        </v-card-text>
      </v-card>

      <v-card variant="outlined" class="mb-3">
        <v-card-text>
          <div class="text-caption text-medium-emphasis mb-1">
            <v-chip size="x-small" :color="txColor('USE')" variant="flat" class="mr-1">
              {{ txLabel('USE') }}
            </v-chip>
          </div>
          <v-sparkline
            v-if="canDrawUse"
            :model-value="useValues"
            :labels="monthLabels"
            :padding="12"
            :line-width="2"
            :smooth="6"
            label-size="5"
            show-labels
            auto-draw
            color="error"
          />
          <div v-else class="text-body-2 text-medium-emphasis">사용 기록이 없습니다.</div>
        </v-card-text>
      </v-card>

      <v-card variant="outlined" class="mb-4">
        <v-table density="compact">
          <thead>
            <tr>
              <th class="text-left">월</th>
              <th class="text-right">충전</th>
              <th class="text-right">사용</th>
              <th class="text-right">순액</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in monthly" :key="p.month">
              <td>{{ p.month }}</td>
              <td class="text-right text-success">{{ wonShort(p.charge) }}</td>
              <td class="text-right text-error">{{ wonShort(p.use) }}</td>
              <td class="text-right" :class="p.net < 0 ? 'text-error' : ''">
                {{ wonShort(p.net) }}
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card>
    </template>

    <v-divider class="my-4" />

    <!-- 기간 필터 -->
    <h2 class="text-subtitle-1 font-weight-bold mb-1">식당별 · 구성원별</h2>
    <div class="text-caption text-medium-emphasis mb-2">{{ periodLabel }} · 사용액 기준 정렬</div>
    <v-row dense class="mb-2">
      <v-col cols="6">
        <div class="text-caption text-medium-emphasis mb-1">시작일</div>
        <input
          v-model="dateFrom"
          type="date"
          class="pa-2 rounded"
          style="width: 100%; border: 1px solid rgba(128, 128, 128, 0.5)"
        />
      </v-col>
      <v-col cols="6">
        <div class="text-caption text-medium-emphasis mb-1">종료일</div>
        <input
          v-model="dateTo"
          type="date"
          class="pa-2 rounded"
          style="width: 100%; border: 1px solid rgba(128, 128, 128, 0.5)"
        />
      </v-col>
    </v-row>
    <div class="d-flex ga-2 mb-4">
      <v-btn
        color="primary"
        variant="flat"
        class="flex-grow-1"
        :loading="loadingBreakdown"
        @click="loadBreakdown"
      >
        적용
      </v-btn>
      <v-btn variant="outlined" class="flex-grow-1" @click="thisYear">올해</v-btn>
      <v-btn variant="text" class="flex-grow-1" @click="resetRange">전체</v-btn>
    </div>

    <!-- 식당별 -->
    <h3 class="text-subtitle-2 font-weight-bold mb-2">식당별</h3>
    <v-skeleton-loader
      v-if="loadingBreakdown && restaurantRows.length === 0"
      type="list-item-two-line, list-item-two-line"
      class="mb-4"
    />
    <v-alert v-else-if="restaurantRows.length === 0" type="info" variant="tonal" class="mb-4">
      해당 기간에 집계할 식당이 없습니다.
    </v-alert>
    <v-card v-else variant="outlined" class="mb-4">
      <template v-for="(r, i) in restaurantRows" :key="r.restaurant_id">
        <v-divider v-if="i > 0" />
        <div class="pa-3" style="cursor: pointer" @click="goRestaurant(r.restaurant_id)">
          <div class="d-flex align-center justify-space-between">
            <span class="text-body-2 font-weight-medium">{{ r.name }}</span>
            <span class="text-body-2 text-error">{{ wonShort(r.use) }}</span>
          </div>
          <v-progress-linear
            :model-value="share(r.use, restaurantMax)"
            color="error"
            height="6"
            rounded
            class="mt-1"
          />
          <div class="text-caption text-medium-emphasis mt-1">
            충전 {{ wonShort(r.charge) }} · 잔액 {{ won(r.balance) }}
          </div>
        </div>
      </template>
    </v-card>

    <!-- 구성원별 -->
    <h3 class="text-subtitle-2 font-weight-bold mb-2">구성원별</h3>
    <v-skeleton-loader
      v-if="loadingBreakdown && userRows.length === 0"
      type="list-item-two-line, list-item-two-line"
    />
    <v-alert v-else-if="userRows.length === 0" type="info" variant="tonal">
      해당 기간에 집계할 기록이 없습니다.
    </v-alert>
    <v-card v-else variant="outlined">
      <template v-for="(u, i) in userRows" :key="u.user_id === null ? 'none-' + i : u.user_id">
        <v-divider v-if="i > 0" />
        <div class="pa-3">
          <div class="d-flex align-center justify-space-between">
            <span class="text-body-2 font-weight-medium">{{ u.name }}</span>
            <span class="text-body-2 text-error">{{ wonShort(u.use) }}</span>
          </div>
          <v-progress-linear
            :model-value="share(u.use, userMax)"
            color="primary"
            height="6"
            rounded
            class="mt-1"
          />
          <div class="text-caption text-medium-emphasis mt-1">
            충전 {{ wonShort(u.charge) }} · 기록 {{ u.tx_count }}건
          </div>
        </div>
      </template>
    </v-card>
  </v-container>
</template>
