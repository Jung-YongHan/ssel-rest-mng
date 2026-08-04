<script setup lang="ts">
/**
 * 홈 = **선결제 식당 목록** (CONTRACT §5.1 `/`).
 *
 * 구성: 총 잔액 요약 카드 → CTA 2개(스캔 / 영수증 없이 기록) → 검색·정렬·필터 →
 * 식당 목록 → 식당 직접 등록.
 *
 * 디자인 규약(docs/DESIGN.md): 총 잔액 카드가 이 화면에서 유일하게 브랜드 컬러를
 * 채우는 면이고, 채운 버튼도 `영수증 스캔` 하나뿐이다. 나머지는 헤어라인으로 나눈다.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { errorMessage, restaurantApi } from '@/api/endpoints'
import type { RestaurantListOut, RestaurantSummary } from '@/api/types'
import { useAppStore } from '@/stores/app'
import { relativeDate, won } from '@/utils/format'

type SortValue = 'balance_desc' | 'balance_asc' | 'name' | 'recent'

const appStore = useAppStore()
const route = useRoute()

const loading = ref(true)
const items = ref<RestaurantSummary[]>([])
const filteredTotal = ref(0)

/** 요약 카드용 — total_balance / low_balance_count 는 서버가 항상 전체 기준으로 준다. */
const headline = ref<{
  total_balance: number
  low_balance_count: number
} | null>(null)

/**
 * 전체 식당 수. 응답의 `total` 은 필터가 반영된 수이므로 여기에 그대로 넣으면 안 된다.
 * 필터 없는 응답에서만 채택하고, 첫 진입이 `?query=` 로 필터된 경우에는
 * 요약용으로 한 번만 따로 조회한다.
 */
const totalRestaurants = ref<number | null>(null)

const search = ref('')
const debouncedSearch = ref('')
const sort = ref<SortValue>('balance_desc')
const lowOnly = ref(false)

const sortOptions: { title: string; value: SortValue }[] = [
  { title: '잔액 많은순', value: 'balance_desc' },
  { title: '잔액 적은순', value: 'balance_asc' },
  { title: '이름순', value: 'name' },
  { title: '최근 사용순', value: 'recent' },
]

const isFiltered = computed(() => debouncedSearch.value.trim() !== '' || lowOnly.value)

let debounceTimer: ReturnType<typeof setTimeout> | undefined

watch(search, (value) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    debouncedSearch.value = value ?? ''
  }, 300)
})

watch([debouncedSearch, sort, lowOnly], () => {
  void load()
})

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})

async function load(): Promise<void> {
  loading.value = true
  const filtered = isFiltered.value
  try {
    const res: RestaurantListOut = await restaurantApi.list({
      query: debouncedSearch.value.trim() || undefined,
      sort: sort.value,
      low_only: lowOnly.value || undefined,
    })

    items.value = res.items
    filteredTotal.value = res.total

    headline.value = {
      total_balance: res.total_balance,
      low_balance_count: res.low_balance_count,
    }
    // 필터가 없을 때만 전체 식당 수로 채택한다.
    if (!filtered) totalRestaurants.value = res.total

    if (typeof res.low_balance_threshold === 'number') {
      appStore.lowBalanceThreshold = res.low_balance_threshold
    }
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    loading.value = false
  }

  if (filtered) void ensureTotalRestaurants()
}

/** 필터된 응답만 받아본 상태라면 요약용 전체 수를 한 번 채운다. */
async function ensureTotalRestaurants(): Promise<void> {
  if (totalRestaurants.value !== null) return
  try {
    const res = await restaurantApi.list({})
    totalRestaurants.value = res.total
  } catch {
    /* 요약 숫자 하나라 실패해도 목록은 그대로 쓴다 */
  }
}

function resetFilters(): void {
  search.value = ''
  debouncedSearch.value = ''
  lowOnly.value = false
}

/** 잔액 색: 음수=error, 부족=warning, 그 외 기본 */
function balanceClass(r: RestaurantSummary): string {
  if (r.balance < 0) return 'text-error'
  if (r.is_low_balance) return 'text-warning'
  return ''
}

function lastUsedText(r: RestaurantSummary): string {
  return r.last_used_at ? `마지막 사용 ${relativeDate(r.last_used_at)}` : '사용 기록 없음'
}

onMounted(() => {
  // 다른 화면에서 `/?query=...` 로 넘어온 경우 검색어를 그대로 이어받는다.
  // (예: 식당 등록 중 사업자등록번호 중복 → "기존 식당 찾아보기")
  const seed = route.query.query
  const term = Array.isArray(seed) ? seed[0] : seed
  if (typeof term === 'string' && term.trim()) {
    search.value = term.trim()
    // debouncedSearch 를 바꾸면 위 watch 가 load() 를 호출한다 →
    // 여기서 또 부르면 요청이 두 번 나가므로 watch 에 맡기고 끝낸다.
    debouncedSearch.value = term.trim()
    return
  }
  void load()
})
</script>

<template>
  <v-container class="flow-container pa-4">
    <!-- ── 총 잔액 (화면당 하나뿐인 브랜드 컬러 면) ───────────── -->
    <!-- color="hero": 라이트=브랜드 블루, 다크=딥 네이비 (main.ts 테마 토큰) -->
    <v-card variant="flat" color="hero" class="pa-5 mb-4">
      <div class="d-flex align-start justify-space-between">
        <div>
          <div class="text-caption hero-label">총 선결제 잔액</div>
          <div class="money-hero amount mt-1">
            {{ headline ? won(headline.total_balance) : '—' }}
          </div>
        </div>
        <v-btn
          icon="mdi-refresh"
          variant="text"
          density="comfortable"
          :loading="loading"
          aria-label="새로 고침"
          class="ms-2 flex-shrink-0"
          @click="load()"
        />
      </div>

      <div class="hero-rule my-4" />

      <div class="hero-metrics d-flex">
        <div>
          <div class="text-caption hero-label">등록 식당</div>
          <div class="text-body-1 font-weight-medium amount mt-1">
            {{ totalRestaurants !== null ? `${totalRestaurants}곳` : '—' }}
          </div>
        </div>
        <div>
          <div class="text-caption hero-label">잔액 부족</div>
          <div class="text-body-1 font-weight-medium amount mt-1">
            {{ headline ? `${headline.low_balance_count}곳` : '—' }}
          </div>
        </div>
      </div>
    </v-card>

    <!-- ── 주 동작 ────────────────────────────────────────────── -->
    <div class="mb-4">
      <v-row dense>
        <v-col cols="12" sm="6">
          <!-- 비활성 이유는 바로 아래 안내문에 항상 보이므로 툴팁을 겹쳐 두지 않는다. -->
          <v-btn
            color="primary"
            size="large"
            block
            prepend-icon="mdi-camera-outline"
            to="/scan"
            :disabled="!appStore.ocrEnabled"
          >
            영수증 스캔
          </v-btn>
        </v-col>
        <v-col cols="12" sm="6">
          <v-btn
            color="primary"
            variant="tonal"
            size="large"
            block
            prepend-icon="mdi-pencil-outline"
            to="/use"
          >
            영수증 없이 기록
          </v-btn>
        </v-col>
      </v-row>

      <div v-if="!appStore.ocrEnabled" class="hint-text d-flex align-center mt-2">
        <v-icon icon="mdi-information-outline" size="16" class="me-1 flex-shrink-0" />
        <span>OCR 서버가 설정되지 않았습니다 — 수동 기록을 사용하세요</span>
      </div>
    </div>

    <!-- ── 검색 / 정렬 ────────────────────────────────────────── -->
    <v-row dense>
      <v-col cols="12" sm="7">
        <v-text-field
          v-model="search"
          label="식당 검색"
          placeholder="상호명 · 주소 · 사업자번호"
          prepend-inner-icon="mdi-magnify"
          clearable
          hide-details
        />
      </v-col>
      <v-col cols="12" sm="5">
        <v-select
          v-model="sort"
          :items="sortOptions"
          item-title="title"
          item-value="value"
          label="정렬"
          prepend-inner-icon="mdi-sort"
          hide-details
        />
      </v-col>
    </v-row>

    <!-- ── 섹션 헤더 + 잔액 부족 필터 ─────────────────────────── -->
    <div class="d-flex align-center flex-wrap mt-4 mb-2">
      <h2 class="section-title">선결제 식당</h2>
      <span v-if="!loading" class="hint-text ms-2">
        {{ isFiltered ? `검색 결과 ${filteredTotal}곳` : `${filteredTotal}곳` }}
      </span>
      <v-spacer />
      <!-- 켜짐 표시는 색만으로 하지 않는다(DESIGN §6) — 체크 아이콘을 함께 붙인다.
           VChip 은 link/chip-group 이 아니면 tabindex 를 주지 않으므로 직접 채운다. -->
      <v-chip
        class="pressable"
        variant="tonal"
        :color="lowOnly ? 'warning' : undefined"
        prepend-icon="mdi-alert-outline"
        :append-icon="lowOnly ? 'mdi-check' : undefined"
        role="button"
        tabindex="0"
        :aria-pressed="lowOnly ? 'true' : 'false'"
        @click="lowOnly = !lowOnly"
        @keydown.enter.prevent="lowOnly = !lowOnly"
        @keydown.space.prevent="lowOnly = !lowOnly"
      >
        잔액 부족만
      </v-chip>
    </div>

    <!-- ── 목록 ───────────────────────────────────────────────── -->
    <v-card v-if="loading && !items.length" class="mb-4">
      <div class="divided">
        <v-skeleton-loader v-for="n in 5" :key="n" type="list-item-two-line" />
      </div>
    </v-card>

    <v-card v-else-if="items.length" class="mb-4">
      <div class="divided">
        <router-link
          v-for="r in items"
          :key="r.id"
          :to="`/restaurants/${r.id}`"
          class="plain-link pressable d-flex align-center pa-4"
        >
          <div class="row-main">
            <div class="d-flex align-center">
              <span class="text-body-1 font-weight-medium text-truncate">{{ r.name }}</span>
              <v-chip
                v-if="r.is_low_balance"
                color="warning"
                size="x-small"
                class="ms-2 flex-shrink-0"
              >
                잔액 부족
              </v-chip>
            </div>
            <div class="hint-text text-truncate mt-1">
              {{ lastUsedText(r) }} · 거래 {{ r.tx_count }}건
            </div>
          </div>

          <div class="amount metric-value text-right ms-3 flex-shrink-0" :class="balanceClass(r)">
            {{ won(r.balance) }}
          </div>
          <v-icon icon="mdi-chevron-right" size="20" class="chevron ms-2 flex-shrink-0" />
        </router-link>
      </div>
    </v-card>

    <!-- ── 빈 상태 ────────────────────────────────────────────── -->
    <v-card v-else class="pa-8 text-center mb-4">
      <v-icon icon="mdi-storefront-outline" size="40" class="mb-3" style="opacity: 0.35" />
      <template v-if="isFiltered">
        <div class="text-body-1 font-weight-medium">조건에 맞는 식당이 없습니다</div>
        <div class="hint-text mt-2 mb-4">검색어나 필터를 지우고 다시 확인해 보세요.</div>
        <v-btn variant="tonal" color="primary" @click="resetFilters">검색 조건 초기화</v-btn>
      </template>
      <template v-else>
        <div class="text-body-1 font-weight-medium">아직 등록된 선결제 식당이 없습니다</div>
        <div class="hint-text mt-2 mb-4">
          이미 선결제해둔 식당이 있으면 먼저 등록하고 남은 금액을 초기 잔액으로 넣어주세요.
          영수증부터 시작하려면 스캔 화면에서 새 식당으로 바로 등록할 수 있습니다.
        </div>
        <v-btn variant="tonal" color="primary" prepend-icon="mdi-plus" to="/restaurants/new">
          식당 직접 등록
        </v-btn>
      </template>
    </v-card>

    <!-- ── 식당 직접 등록 ─────────────────────────────────────── -->
    <div v-if="items.length">
      <v-btn variant="outlined" size="large" block prepend-icon="mdi-plus" to="/restaurants/new">
        식당 직접 등록
      </v-btn>
      <div class="hint-text text-center mt-2">이미 선결제해둔 식당 추가</div>
    </div>
  </v-container>
</template>

<style scoped>
/* ── 총 잔액 카드 ────────────────────────────────────────────────
   브랜드 컬러를 채운 면이므로 테마 테두리색(`--v-border-color`)이 아니라
   `currentColor`(= on-primary) 를 흐리게 써야 라이트/다크 양쪽에서 맞는다. */
.hero-label {
  opacity: 0.82;
}

.hero-rule {
  border-top: 1px solid currentColor;
  opacity: 0.24;
}

.hero-metrics > * {
  min-width: 0;
}
.hero-metrics > * + * {
  position: relative;
  margin-inline-start: var(--sp-4);
  padding-inline-start: var(--sp-4);
}
.hero-metrics > * + *::before {
  content: '';
  position: absolute;
  inset-block: 0;
  inset-inline-start: 0;
  width: 1px;
  background: currentColor;
  opacity: 0.24;
}

/* ── 목록 행 ─────────────────────────────────────────────────────*/
/* 행 자체가 링크다. 식당명이 길면 잘리도록 주 영역의 최소 폭을 풀어준다. */
.row-main {
  flex: 1 1 auto;
  min-width: 0;
}

.chevron {
  opacity: 0.38;
}
</style>
