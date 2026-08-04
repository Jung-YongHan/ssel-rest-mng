<script setup lang="ts">
/**
 * 홈 = **선결제 식당 목록** (CONTRACT §5.1 `/`).
 *
 * 구성: 총 잔액 요약 카드 → CTA 2개(스캔 / 영수증 없이 기록) → 검색·정렬·필터 →
 * 식당 목록 → 식당 직접 등록.
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

/** 요약 카드용 스냅샷 — 검색/필터 때문에 '등록 식당 수'가 흔들리지 않게 따로 둔다. */
const headline = ref<{
  total_balance: number
  total: number
  low_balance_count: number
} | null>(null)

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
  try {
    const res: RestaurantListOut = await restaurantApi.list({
      query: debouncedSearch.value.trim() || undefined,
      sort: sort.value,
      low_only: lowOnly.value || undefined,
    })

    items.value = res.items
    filteredTotal.value = res.total

    // total_balance / low_balance_count 는 서버에서 전체 기준으로 오므로 항상 갱신하고,
    // '등록 식당 수'는 필터가 걸려 있으면 이전 값을 유지한다.
    headline.value = {
      total_balance: res.total_balance,
      low_balance_count: res.low_balance_count,
      total: isFiltered.value && headline.value ? headline.value.total : res.total,
    }

    if (typeof res.low_balance_threshold === 'number') {
      appStore.lowBalanceThreshold = res.low_balance_threshold
    }
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    loading.value = false
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
  <v-container class="pa-3" style="max-width: 720px">
    <!-- ── 요약 ─────────────────────────────────────────────── -->
    <v-card color="primary" variant="flat" class="mb-4">
      <v-card-text class="pb-4">
        <div class="d-flex align-start justify-space-between">
          <div>
            <div class="text-caption" style="opacity: 0.85">총 선결제 잔액</div>
            <div class="text-h4 font-weight-bold amount mt-1">
              {{ headline ? won(headline.total_balance) : '—' }}
            </div>
          </div>
          <v-btn
            icon="mdi-refresh"
            variant="text"
            density="comfortable"
            :loading="loading"
            aria-label="새로고침"
            @click="load()"
          />
        </div>

        <v-divider class="my-3" style="opacity: 0.25" />

        <div class="d-flex text-body-2">
          <div class="me-6">
            <span style="opacity: 0.85">등록 식당</span>
            <strong class="ms-2 amount">{{ headline ? `${headline.total}곳` : '—' }}</strong>
          </div>
          <div>
            <span style="opacity: 0.85">잔액 부족</span>
            <strong class="ms-2 amount">
              {{ headline ? `${headline.low_balance_count}곳` : '—' }}
            </strong>
          </div>
        </div>
      </v-card-text>
    </v-card>

    <!-- ── CTA ──────────────────────────────────────────────── -->
    <div class="mb-4">
      <v-row dense>
        <v-col cols="12" sm="6">
          <v-tooltip
            :disabled="appStore.ocrEnabled"
            text="OCR 서버가 설정되지 않았습니다 — 수동 기록을 사용하세요"
            location="bottom"
          >
            <template #activator="{ props: tipProps }">
              <div v-bind="tipProps">
                <v-btn
                  color="primary"
                  size="large"
                  block
                  height="56"
                  to="/scan"
                  :disabled="!appStore.ocrEnabled"
                >
                  📷 영수증 스캔
                </v-btn>
              </div>
            </template>
          </v-tooltip>
        </v-col>
        <v-col cols="12" sm="6">
          <v-btn color="primary" variant="tonal" size="large" block height="56" to="/use">
            ✏️ 영수증 없이 기록
          </v-btn>
        </v-col>
      </v-row>

      <div
        v-if="!appStore.ocrEnabled"
        class="d-flex align-center text-caption text-medium-emphasis mt-2"
      >
        <v-icon icon="mdi-information-outline" size="16" class="me-1" />
        OCR 서버가 설정되지 않았습니다 — 수동 기록을 사용하세요
      </div>
    </div>

    <!-- ── 검색 / 정렬 / 필터 ───────────────────────────────── -->
    <v-row dense align="center">
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
          hide-details
        />
      </v-col>
    </v-row>

    <div class="d-flex align-center flex-wrap mt-3 mb-1">
      <v-chip
        :variant="lowOnly ? 'flat' : 'outlined'"
        :color="lowOnly ? 'warning' : undefined"
        size="small"
        prepend-icon="mdi-alert-outline"
        @click="lowOnly = !lowOnly"
      >
        잔액 부족만
      </v-chip>
      <v-spacer />
      <span v-if="!loading" class="text-caption text-medium-emphasis">
        {{ isFiltered ? `검색 결과 ${filteredTotal}곳` : `${filteredTotal}곳` }}
      </span>
    </div>

    <!-- ── 목록 ─────────────────────────────────────────────── -->
    <v-card v-if="loading && !items.length" variant="flat" class="mt-2">
      <v-skeleton-loader v-for="n in 5" :key="n" type="list-item-two-line" />
    </v-card>

    <v-card v-else-if="items.length" variant="flat" class="mt-2">
      <v-list lines="two" density="comfortable">
        <template v-for="(r, index) in items" :key="r.id">
          <v-divider v-if="index > 0" />
          <v-list-item :to="`/restaurants/${r.id}`">
            <v-list-item-title class="font-weight-medium d-flex align-center">
              <span class="text-truncate">{{ r.name }}</span>
              <v-chip
                v-if="r.is_low_balance"
                color="warning"
                size="x-small"
                variant="flat"
                class="ms-2 flex-shrink-0"
              >
                잔액 부족
              </v-chip>
            </v-list-item-title>

            <v-list-item-subtitle class="text-caption">
              {{ lastUsedText(r) }}
            </v-list-item-subtitle>

            <template #append>
              <div class="text-right">
                <div class="text-subtitle-1 font-weight-bold amount" :class="balanceClass(r)">
                  {{ won(r.balance) }}
                </div>
                <div class="text-caption text-medium-emphasis">거래 {{ r.tx_count }}건</div>
              </div>
              <v-icon icon="mdi-chevron-right" class="ms-1 text-medium-emphasis" />
            </template>
          </v-list-item>
        </template>
      </v-list>
    </v-card>

    <!-- ── 빈 상태 ──────────────────────────────────────────── -->
    <v-card v-else variant="tonal" class="mt-2 text-center pa-6">
      <v-icon icon="mdi-storefront-outline" size="40" class="text-medium-emphasis mb-2" />
      <template v-if="isFiltered">
        <div class="text-subtitle-1 font-weight-medium">조건에 맞는 식당이 없습니다</div>
        <div class="text-body-2 text-medium-emphasis mt-1">
          검색어나 필터를 지우고 다시 확인해 보세요.
        </div>
        <v-btn class="mt-4" variant="outlined" @click="resetFilters">검색 조건 초기화</v-btn>
      </template>
      <template v-else>
        <div class="text-subtitle-1 font-weight-medium">아직 등록된 선결제 식당이 없습니다</div>
        <div class="text-body-2 text-medium-emphasis mt-1">
          이미 선결제해둔 식당이 있으면 먼저 등록하고 남은 금액을 초기 잔액으로 넣어주세요.<br />
          영수증부터 시작하려면 스캔 화면에서 새 식당으로 바로 등록할 수 있습니다.
        </div>
        <v-btn class="mt-4" color="primary" size="large" to="/restaurants/new">
          + 식당 직접 등록
        </v-btn>
      </template>
    </v-card>

    <!-- ── 식당 직접 등록 ───────────────────────────────────── -->
    <v-btn
      v-if="items.length"
      class="mt-4"
      color="primary"
      variant="tonal"
      size="large"
      block
      height="64"
      to="/restaurants/new"
    >
      <div class="text-center py-1">
        <div class="text-subtitle-1 font-weight-medium">+ 식당 직접 등록</div>
        <div class="text-caption" style="opacity: 0.8">이미 선결제해둔 식당 추가</div>
      </div>
    </v-btn>
  </v-container>
</template>
