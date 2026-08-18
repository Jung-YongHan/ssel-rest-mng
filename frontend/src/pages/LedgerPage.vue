<script setup lang="ts">
/**
 * 전체 거래 원장 (CONTRACT §2.4).
 *
 * 데스크톱은 표(`v-data-table-server`), 모바일은 카드 목록으로 분기한다.
 * 디자인 규약은 docs/DESIGN.md — 지표는 `.metric-row`, 숫자 컬럼은 `.num-col`.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import {
  adminApi,
  receiptApi,
  restaurantApi,
  transactionApi,
  errorMessage,
} from '@/api/endpoints'
import type { TransactionQuery } from '@/api/endpoints'
import type { RestaurantSummary, TransactionOut, UserOut } from '@/api/types'
import { dateTime, todayInput, txColor, txLabel, won } from '@/utils/format'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const { mdAndUp } = useDisplay()

/* ------------------------------------------------------------------ */
/* 상태                                                                */
/* ------------------------------------------------------------------ */

const filters = ref({
  date_from: '',
  date_to: '',
  restaurant: null as RestaurantSummary | null,
  user_id: null as number | null,
  type: null as string | null,
  query: '',
  include_voided: false,
})

const items = ref<TransactionOut[]>([])
const total = ref(0)
const sumCharge = ref(0)
const sumUse = ref(0)
const sumAdjust = ref(0)
const loading = ref(false)

const page = ref(1)
const itemsPerPage = ref(25)

/* 식당 검색 */
const restaurantOptions = ref<RestaurantSummary[]>([])
const restaurantSearch = ref('')
const restaurantLoading = ref(false)

/* 구성원 */
const users = ref<UserOut[]>([])

/* 필터 카드 (모바일에서는 접은 채로 시작) */
const filtersOpen = ref(false)

/* CSV 내보내기 (본문을 받아오는 동안 버튼을 잠근다) */
const exporting = ref(false)

/* 기록 취소 */
const voidDialog = ref(false)
const voidTarget = ref<TransactionOut | null>(null)
const voidReason = ref('')
const voiding = ref(false)

/* 영수증 이미지 */
const imageDialog = ref(false)
const imageUrl = ref('')

const typeOptions = [
  { title: txLabel('CHARGE'), value: 'CHARGE' },
  { title: txLabel('USE'), value: 'USE' },
  { title: txLabel('ADJUST'), value: 'ADJUST' },
]

const headers = [
  { title: '일시', key: 'occurred_at', sortable: false, cellProps: { class: 'text-no-wrap' } },
  { title: '식당', key: 'restaurant_name', sortable: false },
  { title: '유형', key: 'type', sortable: false, cellProps: { class: 'text-no-wrap' } },
  {
    title: '금액',
    key: 'signed_amount',
    sortable: false,
    align: 'end',
    headerProps: { class: 'num-col' },
    cellProps: { class: 'num-col' },
  },
  { title: '메모', key: 'memo', sortable: false },
  { title: '기록자', key: 'created_by', sortable: false, cellProps: { class: 'text-no-wrap' } },
  { title: '', key: 'actions', sortable: false, align: 'end' },
] as any

/* ------------------------------------------------------------------ */
/* 파생 값                                                             */
/* ------------------------------------------------------------------ */

const net = computed(() => sumCharge.value - sumUse.value + sumAdjust.value)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / itemsPerPage.value)))
const canVoid = computed(() => voidReason.value.trim().length > 0 && !voiding.value)
const periodLabel = computed(() => {
  const f = filters.value
  if (!f.date_from && !f.date_to) return '전체 기간'
  return `${f.date_from || '처음'} ~ ${f.date_to || '오늘'}`
})

/** 접힌 필터 카드에서 지금 무엇이 걸려 있는지 한눈에 보여줄 요약 칩 */
const activeFilters = computed<string[]>(() => {
  const f = filters.value
  const out: string[] = []
  if (f.date_from || f.date_to) out.push(periodLabel.value)
  if (f.restaurant) out.push(f.restaurant.name)
  if (f.user_id) {
    const found = users.value.find((u) => u.id === f.user_id)
    out.push(found ? found.name : '구성원')
  }
  if (f.type) out.push(txLabel(f.type as 'CHARGE' | 'USE' | 'ADJUST'))
  if (f.query.trim()) out.push(`검색어 ${f.query.trim()}`)
  if (f.include_voided) out.push('취소 포함')
  return out
})

/** 합계 지표 — 좁은 화면에서는 2칸씩 두 줄로 나눈다. */
const summaryMetrics = computed(() => [
  { label: '충전 합계', value: won(sumCharge.value), cls: 'text-success' },
  { label: '사용 합계', value: won(sumUse.value), cls: 'text-error' },
  {
    label: '정정 합계',
    value: won(sumAdjust.value),
    cls: sumAdjust.value === 0 ? '' : sumAdjust.value < 0 ? 'text-error' : 'text-success',
  },
  { label: '순액', value: won(net.value), cls: net.value < 0 ? 'text-error' : '' },
])

const metricRows = computed(() => {
  const m = summaryMetrics.value
  return mdAndUp.value ? [m] : [m.slice(0, 2), m.slice(2)]
})

/** 거래 유형 아이콘 (DESIGN §3) */
function txIcon(type: string): string {
  if (type === 'CHARGE') return 'mdi-arrow-down-circle-outline'
  if (type === 'USE') return 'mdi-arrow-up-circle-outline'
  return 'mdi-swap-vertical'
}

function signedText(t: TransactionOut): string {
  if (t.is_voided) return won(t.amount)
  return (t.signed_amount > 0 ? '+' : '') + won(t.signed_amount)
}

/** 유입은 success, 유출은 error, 취소된 기록은 흐리게 + 취소선 */
function amountClass(t: TransactionOut): string {
  if (t.is_voided) return 'text-medium-emphasis text-decoration-line-through'
  if (t.signed_amount > 0) return 'text-success'
  if (t.signed_amount < 0) return 'text-error'
  return ''
}

/* ------------------------------------------------------------------ */
/* 조회                                                                */
/* ------------------------------------------------------------------ */

function currentQuery(): TransactionQuery {
  const f = filters.value
  const q: TransactionQuery = { include_voided: f.include_voided }
  if (f.date_from) q.date_from = f.date_from
  if (f.date_to) q.date_to = f.date_to
  if (f.restaurant) q.restaurant_id = f.restaurant.id
  if (f.user_id) q.user_id = f.user_id
  if (f.type) q.type = f.type
  if (f.query.trim()) q.query = f.query.trim()
  return q
}

async function load() {
  loading.value = true
  try {
    const res = await transactionApi.list({
      ...currentQuery(),
      limit: itemsPerPage.value,
      offset: (page.value - 1) * itemsPerPage.value,
    })
    items.value = res.items
    total.value = res.total
    sumCharge.value = res.sum_charge
    sumUse.value = res.sum_use
    sumAdjust.value = res.sum_adjust
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    loading.value = false
  }
}

let loadTimer: number | undefined
function scheduleLoad() {
  window.clearTimeout(loadTimer)
  loadTimer = window.setTimeout(load, 250)
}

watch(
  filters,
  () => {
    page.value = 1
    scheduleLoad()
  },
  { deep: true },
)
watch([page, itemsPerPage], scheduleLoad)

/* ------------------------------------------------------------------ */
/* 기간 단축 선택                                                       */
/* ------------------------------------------------------------------ */

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** offsetMonths=0 이번 달, -1 지난 달 */
function monthRange(offsetMonths: number): { from: string; to: string } {
  const today = todayInput()
  const y = Number(today.slice(0, 4))
  const m = Number(today.slice(5, 7))
  const first = new Date(Date.UTC(y, m - 1 + offsetMonths, 1))
  const yy = first.getUTCFullYear()
  const mm = first.getUTCMonth() + 1
  const lastDay = new Date(Date.UTC(yy, mm, 0)).getUTCDate()
  return { from: `${yy}-${pad(mm)}-01`, to: `${yy}-${pad(mm)}-${pad(lastDay)}` }
}

type Preset = 'this' | 'last' | 'three' | 'all'

/**
 * 강조할 기간 칩. 선택값을 따로 저장하지 않고 **현재 날짜 범위에서 역산**한다.
 * 저장해 두면 사용자가 시작일/종료일을 직접 고친 뒤에도 칩이 강조된 채 남아
 * 실제 조회 조건과 표시가 어긋난다.
 */
const activePreset = computed<Preset | null>(() => {
  const { date_from: from, date_to: to } = filters.value
  if (!from && !to) return 'all'
  const thisMonth = monthRange(0)
  if (from === thisMonth.from && to === thisMonth.to) return 'this'
  const lastMonth = monthRange(-1)
  if (from === lastMonth.from && to === lastMonth.to) return 'last'
  if (from === monthRange(-2).from && to === thisMonth.to) return 'three'
  return null
})

const presetOptions: { title: string; value: Preset }[] = [
  { title: '이번 달', value: 'this' },
  { title: '지난 달', value: 'last' },
  { title: '최근 3개월', value: 'three' },
  { title: '전체', value: 'all' },
]

function applyPreset(p: Preset) {
  if (p === 'all') {
    filters.value.date_from = ''
    filters.value.date_to = ''
    return
  }
  if (p === 'this') {
    const r = monthRange(0)
    filters.value.date_from = r.from
    filters.value.date_to = r.to
    return
  }
  if (p === 'last') {
    const r = monthRange(-1)
    filters.value.date_from = r.from
    filters.value.date_to = r.to
    return
  }
  filters.value.date_from = monthRange(-2).from
  filters.value.date_to = monthRange(0).to
}

function resetFilters() {
  filters.value = {
    date_from: '',
    date_to: '',
    restaurant: null,
    user_id: null,
    type: null,
    query: '',
    include_voided: false,
  }
}

/* ------------------------------------------------------------------ */
/* 식당 검색 / 구성원                                                   */
/* ------------------------------------------------------------------ */

async function fetchRestaurants(q: string) {
  restaurantLoading.value = true
  try {
    const res = await restaurantApi.list({ query: q || undefined, include_archived: true })
    restaurantOptions.value = res.items
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    restaurantLoading.value = false
  }
}

let restaurantTimer: number | undefined
watch(restaurantSearch, (v) => {
  const q = (v ?? '').trim()
  if (filters.value.restaurant && q === filters.value.restaurant.name) return
  window.clearTimeout(restaurantTimer)
  restaurantTimer = window.setTimeout(() => fetchRestaurants(q), 250)
})

async function fetchUsers() {
  try {
    users.value = await adminApi.users()
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  }
}

/* ------------------------------------------------------------------ */
/* 기록 취소 / CSV / 기타                                               */
/* ------------------------------------------------------------------ */

function openVoid(t: TransactionOut) {
  voidTarget.value = t
  voidReason.value = ''
  voidDialog.value = true
}

async function confirmVoid() {
  if (!voidTarget.value || !canVoid.value) {
    appStore.toast('취소 사유를 입력해 주세요.', 'warning')
    return
  }
  voiding.value = true
  try {
    await transactionApi.void_(voidTarget.value.id, voidReason.value.trim())
    appStore.toast('기록을 취소했습니다.', 'success')
    voidDialog.value = false
    await load()
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    voiding.value = false
  }
}

async function exportCsv() {
  if (exporting.value) return
  exporting.value = true
  try {
    const result = await transactionApi.exportCsv(currentQuery())
    if (result === 'shared') appStore.toast('CSV 파일을 내보냈습니다.', 'success')
    else if (result === 'downloaded') appStore.toast('CSV 파일을 내려받았습니다.', 'success')
    // 'cancelled' — 사용자가 공유 시트를 닫은 것이므로 알리지 않는다.
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    exporting.value = false
  }
}

function openReceipt(receiptId: number | null) {
  if (!receiptId) return
  imageUrl.value = receiptApi.imageUrl(receiptId)
  imageDialog.value = true
}

function goRestaurant(id: number) {
  router.push(`/restaurants/${id}`)
}

onMounted(() => {
  load()
  fetchRestaurants('')
  if (authStore.isAdmin) fetchUsers()
  if (mdAndUp.value) filtersOpen.value = true
})
</script>

<template>
  <!-- 원장은 컬럼이 7개라 모바일 기준 720px 로는 표가 좁아 셀이 줄바꿈된다.
       PC 에서 관리하는 화면이므로 데스크톱에서는 폭을 넓게 쓴다 (DESIGN §2). -->
  <v-container :class="['pa-4', mdAndUp ? 'wide-container' : 'flow-container']">
    <div class="d-flex align-center justify-space-between ga-3 mb-4">
      <h1 class="page-title">전체 거래 원장</h1>
      <v-btn
        variant="outlined"
        prepend-icon="mdi-tray-arrow-down"
        :loading="exporting"
        @click="exportCsv"
      >
        CSV 내보내기
      </v-btn>
    </div>

    <!-- ── 필터 ────────────────────────────────────────────────── -->
    <v-card class="mb-4">
      <div
        class="pa-4 pressable d-flex align-center ga-3"
        @click="filtersOpen = !filtersOpen"
      >
        <v-icon icon="mdi-filter-variant" size="18" class="flex-shrink-0" />
        <span class="section-title flex-shrink-0">필터</span>

        <div class="d-flex align-center flex-wrap ga-1 flex-grow-1 overflow-hidden">
          <v-chip v-for="chip in activeFilters" :key="chip" color="primary" size="x-small">
            {{ chip }}
          </v-chip>
          <span v-if="activeFilters.length === 0" class="hint-text">{{ periodLabel }}</span>
        </div>

        <v-btn
          :icon="filtersOpen ? 'mdi-chevron-up' : 'mdi-chevron-down'"
          variant="text"
          density="comfortable"
          class="flex-shrink-0"
          :aria-label="filtersOpen ? '필터 접기' : '필터 펼치기'"
          @click.stop="filtersOpen = !filtersOpen"
        />
      </div>

      <v-expand-transition>
        <div v-show="filtersOpen">
          <v-divider />
          <div class="pa-4">
            <v-row dense>
              <!-- 기간 단축 선택 -->
              <v-col cols="12">
                <div class="field-label mb-2">기간</div>
                <div class="d-flex flex-wrap ga-2">
                  <v-chip
                    v-for="option in presetOptions"
                    :key="option.value"
                    :color="activePreset === option.value ? 'primary' : undefined"
                    :variant="activePreset === option.value ? 'flat' : 'outlined'"
                    @click="applyPreset(option.value)"
                  >
                    {{ option.title }}
                  </v-chip>
                </div>
              </v-col>

              <!-- 날짜 -->
              <v-col cols="6" md="3">
                <div class="field-label mb-1">시작일</div>
                <v-text-field v-model="filters.date_from" type="date" />
              </v-col>
              <v-col cols="6" md="3">
                <div class="field-label mb-1">종료일</div>
                <v-text-field v-model="filters.date_to" type="date" />
              </v-col>

              <!-- 식당 / 구성원 / 유형 -->
              <v-col cols="12" :md="authStore.isAdmin ? 4 : 6">
                <div class="field-label mb-1">식당</div>
                <v-autocomplete
                  v-model="filters.restaurant"
                  v-model:search="restaurantSearch"
                  :items="restaurantOptions"
                  :loading="restaurantLoading"
                  item-title="name"
                  item-value="id"
                  return-object
                  no-filter
                  clearable
                  placeholder="전체"
                  prepend-inner-icon="mdi-storefront-outline"
                >
                  <template #item="{ props: itemProps, item }">
                    <v-list-item
                      v-bind="itemProps"
                      :title="item.raw.name"
                      :subtitle="`잔액 ${won(item.raw.balance)}`"
                    />
                  </template>
                  <template #no-data>
                    <div class="pa-4 hint-text">검색 결과가 없습니다.</div>
                  </template>
                </v-autocomplete>
              </v-col>

              <v-col v-if="authStore.isAdmin" cols="12" md="4">
                <div class="field-label mb-1">구성원</div>
                <v-select
                  v-model="filters.user_id"
                  :items="users"
                  item-title="name"
                  item-value="id"
                  clearable
                  placeholder="전체"
                  prepend-inner-icon="mdi-account-circle-outline"
                />
              </v-col>

              <v-col cols="12" :md="authStore.isAdmin ? 4 : 6">
                <div class="field-label mb-1">유형</div>
                <v-select
                  v-model="filters.type"
                  :items="typeOptions"
                  clearable
                  placeholder="전체"
                  prepend-inner-icon="mdi-swap-vertical"
                />
              </v-col>

              <!-- 검색어 / 취소 포함 -->
              <v-col cols="12" md="8">
                <div class="field-label mb-1">검색어</div>
                <v-text-field
                  v-model="filters.query"
                  placeholder="메모 · 식당명"
                  prepend-inner-icon="mdi-magnify"
                  clearable
                />
              </v-col>

              <v-col cols="12" md="4" class="d-flex align-end">
                <div class="d-flex align-center ga-2 flex-grow-1 pb-1">
                  <v-switch
                    v-model="filters.include_voided"
                    label="취소 포함"
                    color="primary"
                    density="compact"
                    inset
                    hide-details
                  />
                  <v-spacer />
                  <v-btn variant="text" @click="resetFilters">필터 초기화</v-btn>
                </div>
              </v-col>
            </v-row>
          </div>
        </div>
      </v-expand-transition>
    </v-card>

    <!-- ── 합계 ────────────────────────────────────────────────── -->
    <v-card class="mb-4">
      <div class="divided">
        <div v-for="(row, i) in metricRows" :key="i" class="metric-row">
          <div v-for="metric in row" :key="metric.label" class="metric-cell">
            <div class="field-label">{{ metric.label }}</div>
            <div class="metric-value amount" :class="metric.cls">{{ metric.value }}</div>
          </div>
        </div>
      </div>
      <v-divider />
      <div class="px-4 py-2 hint-text">{{ periodLabel }} · 총 {{ total }}건</div>
    </v-card>

    <!-- ── 데스크톱: 표 ─────────────────────────────────────────── -->
    <v-card v-if="mdAndUp" class="table-scroll">
      <v-data-table-server
        v-model:page="page"
        v-model:items-per-page="itemsPerPage"
        :headers="headers"
        :items="items"
        :items-length="total"
        :loading="loading"
        :items-per-page-options="[10, 25, 50, 100]"
        item-value="id"
        hover
        no-data-text="조건에 맞는 거래가 없습니다."
        loading-text="불러오는 중입니다..."
      >
        <template #item.occurred_at="{ item }">
          <span class="hint-text">{{ dateTime(item.occurred_at) }}</span>
        </template>

        <template #item.restaurant_name="{ item }">
          <a
            class="text-primary text-decoration-none"
            style="cursor: pointer"
            @click="goRestaurant(item.restaurant_id)"
          >
            {{ item.restaurant_name }}
          </a>
        </template>

        <template #item.type="{ item }">
          <v-chip :color="txColor(item.type)" size="small" :prepend-icon="txIcon(item.type)">
            {{ txLabel(item.type) }}
          </v-chip>
          <v-chip v-if="item.is_voided" color="secondary" size="small" class="ms-1">
            취소됨
          </v-chip>
        </template>

        <template #item.signed_amount="{ item }">
          <span class="amount" :class="amountClass(item)">{{ signedText(item) }}</span>
        </template>

        <template #item.memo="{ item }">
          <div class="memo-cell">
            <div class="text-truncate" :title="item.memo || ''">{{ item.memo || '-' }}</div>
            <div
              v-if="item.is_voided"
              class="hint-text text-truncate"
              :title="item.void_reason || ''"
            >
              취소 사유: {{ item.void_reason || '-' }}
            </div>
          </div>
        </template>

        <template #item.created_by="{ item }">
          <span class="hint-text">{{ item.created_by ? item.created_by.name : '-' }}</span>
        </template>

        <template #item.actions="{ item }">
          <div class="d-flex align-center justify-end">
            <v-btn
              v-if="item.has_receipt"
              icon="mdi-receipt-text-outline"
              variant="text"
              density="comfortable"
              aria-label="영수증 보기"
              @click="openReceipt(item.receipt_id)"
            />
            <v-menu v-if="!item.is_voided" location="bottom end">
              <template #activator="{ props: menuProps }">
                <v-btn
                  v-bind="menuProps"
                  icon="mdi-dots-vertical"
                  variant="text"
                  density="comfortable"
                  aria-label="이 기록의 추가 작업"
                />
              </template>
              <v-card min-width="176">
                <v-list density="compact" class="py-1">
                  <v-list-item
                    prepend-icon="mdi-close-circle-outline"
                    title="기록 취소"
                    base-color="error"
                    @click="openVoid(item)"
                  />
                </v-list>
              </v-card>
            </v-menu>
          </div>
        </template>
      </v-data-table-server>
    </v-card>

    <!-- ── 모바일: 카드 목록 ────────────────────────────────────── -->
    <template v-else>
      <v-skeleton-loader
        v-if="loading && items.length === 0"
        type="list-item-two-line, list-item-two-line, list-item-two-line"
      />

      <v-card v-else-if="items.length === 0" class="pa-8 text-center">
        <v-icon
          icon="mdi-book-open-variant-outline"
          size="40"
          class="mb-3"
          style="opacity: 0.35"
        />
        <div class="text-body-2 text-medium-emphasis mb-4">조건에 맞는 거래가 없습니다.</div>
        <v-btn variant="tonal" color="primary" @click="resetFilters">필터 초기화</v-btn>
      </v-card>

      <v-card v-else>
        <div class="divided">
          <div v-for="t in items" :key="t.id" class="pa-4">
            <div class="d-flex align-start ga-3">
              <div class="flex-grow-1 overflow-hidden">
                <div class="d-flex align-center flex-wrap ga-2">
                  <v-chip :color="txColor(t.type)" size="small" :prepend-icon="txIcon(t.type)">
                    {{ txLabel(t.type) }}
                  </v-chip>
                  <v-chip v-if="t.is_voided" color="secondary" size="small">취소됨</v-chip>
                </div>

                <div class="mt-2">
                  <a
                    class="text-primary text-decoration-none text-body-2"
                    style="cursor: pointer"
                    @click="goRestaurant(t.restaurant_id)"
                  >
                    {{ t.restaurant_name }}
                  </a>
                </div>
                <div class="hint-text">{{ dateTime(t.occurred_at) }}</div>
                <div v-if="t.memo" class="text-body-2 mt-1">{{ t.memo }}</div>
                <div class="hint-text mt-1">
                  기록: {{ t.created_by ? t.created_by.name : '알 수 없음' }}
                </div>
                <div v-if="t.is_voided" class="hint-text mt-1">
                  취소 사유: {{ t.void_reason || '(사유 없음)' }}
                </div>
              </div>

              <div class="d-flex align-center flex-shrink-0">
                <div class="amount text-right" :class="amountClass(t)">{{ signedText(t) }}</div>
                <v-btn
                  v-if="t.has_receipt"
                  icon="mdi-receipt-text-outline"
                  variant="text"
                  class="ms-1"
                  aria-label="영수증 보기"
                  @click="openReceipt(t.receipt_id)"
                />
                <v-menu v-if="!t.is_voided" location="bottom end">
                  <template #activator="{ props: menuProps }">
                    <v-btn
                      v-bind="menuProps"
                      icon="mdi-dots-vertical"
                      variant="text"
                      class="ms-1"
                      aria-label="이 기록의 추가 작업"
                    />
                  </template>
                  <v-card min-width="176">
                    <v-list density="compact" class="py-1">
                      <v-list-item
                        prepend-icon="mdi-close-circle-outline"
                        title="기록 취소"
                        base-color="error"
                        @click="openVoid(t)"
                      />
                    </v-list>
                  </v-card>
                </v-menu>
              </div>
            </div>
          </div>
        </div>
      </v-card>

      <div v-if="total > 0" class="d-flex align-center justify-space-between mt-4">
        <v-btn
          variant="outlined"
          prepend-icon="mdi-arrow-left"
          :disabled="page <= 1 || loading"
          @click="page = page - 1"
        >
          이전
        </v-btn>
        <span class="hint-text amount">{{ page }} / {{ totalPages }} 페이지</span>
        <v-btn
          variant="outlined"
          append-icon="mdi-arrow-right"
          :disabled="page >= totalPages || loading"
          @click="page = page + 1"
        >
          다음
        </v-btn>
      </div>
    </template>

    <!-- ── 기록 취소 ───────────────────────────────────────────── -->
    <v-dialog v-model="voidDialog" max-width="480">
      <v-card>
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon icon="mdi-close-circle-outline" size="20" />
          <span class="section-title">기록 취소</span>
        </v-card-title>
        <v-divider />

        <v-card-text class="pa-4">
          <template v-if="voidTarget">
            <div class="text-body-2 font-weight-medium">{{ voidTarget.restaurant_name }}</div>
            <div class="d-flex align-center flex-wrap ga-2 mt-2 mb-3">
              <v-chip
                :color="txColor(voidTarget.type)"
                size="small"
                :prepend-icon="txIcon(voidTarget.type)"
              >
                {{ txLabel(voidTarget.type) }}
              </v-chip>
              <span class="amount">{{ won(voidTarget.amount) }}</span>
              <span class="hint-text">{{ dateTime(voidTarget.occurred_at) }}</span>
            </div>
          </template>

          <div class="hint-text mb-4">
            기록은 삭제되지 않고 취소 표시만 남습니다. 사유를 남겨 주세요.
          </div>

          <div class="field-label mb-1">취소 사유</div>
          <v-text-field
            v-model="voidReason"
            :error="voidReason.trim().length === 0"
            placeholder="예: 금액 오기입"
            autofocus
          />
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn variant="text" :disabled="voiding" @click="voidDialog = false">닫기</v-btn>
          <v-btn color="error" :loading="voiding" :disabled="!canVoid" @click="confirmVoid">
            기록 취소
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- ── 영수증 이미지 ───────────────────────────────────────── -->
    <v-dialog v-model="imageDialog" max-width="640">
      <v-card>
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon icon="mdi-receipt-text-outline" size="20" />
          <span class="section-title">영수증</span>
        </v-card-title>
        <v-divider />

        <v-img :src="imageUrl" max-height="80vh" contain />

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn variant="text" @click="imageDialog = false">닫기</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
/* 메모는 표 폭을 밀어내지 않게 잘라서 보여준다 (전체 내용은 title 로 확인).
   styles.css 에 없는 '이 표 전용' 제약이라 여기서만 정의한다. */
.memo-cell {
  max-width: 260px;
}
</style>
