<script setup lang="ts">
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

/* 필터 패널 (모바일 접기) */
const panels = ref<number[]>([])

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
  { title: '일시', key: 'occurred_at', sortable: false },
  { title: '식당', key: 'restaurant_name', sortable: false },
  { title: '유형', key: 'type', sortable: false },
  { title: '금액', key: 'signed_amount', sortable: false, align: 'end' },
  { title: '메모', key: 'memo', sortable: false },
  { title: '기록자', key: 'created_by', sortable: false },
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

function signedText(t: TransactionOut): string {
  if (t.is_voided) return won(t.amount)
  return (t.signed_amount > 0 ? '+' : '') + won(t.signed_amount)
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
const preset = ref<Preset | null>(null)

function applyPreset(p: Preset) {
  preset.value = p
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
  preset.value = null
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

function exportCsv() {
  const url = transactionApi.exportCsvUrl(currentQuery())
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  a.remove()
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
  if (mdAndUp.value) panels.value = [0]
})
</script>

<template>
  <!-- 원장은 컬럼이 7개라 모바일 기준 720px 로는 표가 좁아 셀이 줄바꿈된다.
       PC 에서 관리하는 화면이므로 데스크톱에서는 폭을 넓게 쓴다. -->
  <v-container class="pa-3" :style="{ maxWidth: mdAndUp ? '1200px' : '720px' }">
    <div class="d-flex align-center justify-space-between mb-3">
      <h1 class="text-h6">전체 거래 원장</h1>
      <v-btn size="small" variant="outlined" @click="exportCsv">CSV 내보내기</v-btn>
    </div>

    <!-- 필터 -->
    <v-expansion-panels v-model="panels" multiple class="mb-3">
      <v-expansion-panel>
        <v-expansion-panel-title>
          <span class="text-subtitle-2">필터</span>
          <span class="text-caption text-medium-emphasis ml-2">{{ periodLabel }}</span>
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <div class="text-caption text-medium-emphasis mb-1">기간</div>
          <div class="d-flex ga-2 flex-wrap mb-3">
            <v-chip
              size="small"
              :color="preset === 'this' ? 'primary' : undefined"
              :variant="preset === 'this' ? 'flat' : 'outlined'"
              @click="applyPreset('this')"
            >
              이번 달
            </v-chip>
            <v-chip
              size="small"
              :color="preset === 'last' ? 'primary' : undefined"
              :variant="preset === 'last' ? 'flat' : 'outlined'"
              @click="applyPreset('last')"
            >
              지난 달
            </v-chip>
            <v-chip
              size="small"
              :color="preset === 'three' ? 'primary' : undefined"
              :variant="preset === 'three' ? 'flat' : 'outlined'"
              @click="applyPreset('three')"
            >
              최근 3개월
            </v-chip>
            <v-chip
              size="small"
              :color="preset === 'all' ? 'primary' : undefined"
              :variant="preset === 'all' ? 'flat' : 'outlined'"
              @click="applyPreset('all')"
            >
              전체
            </v-chip>
          </div>

          <v-row dense>
            <v-col cols="6">
              <div class="text-caption text-medium-emphasis mb-1">시작일</div>
              <input
                v-model="filters.date_from"
                type="date"
                class="pa-2 rounded"
                style="width: 100%; border: 1px solid rgba(128, 128, 128, 0.5)"
              />
            </v-col>
            <v-col cols="6">
              <div class="text-caption text-medium-emphasis mb-1">종료일</div>
              <input
                v-model="filters.date_to"
                type="date"
                class="pa-2 rounded"
                style="width: 100%; border: 1px solid rgba(128, 128, 128, 0.5)"
              />
            </v-col>
          </v-row>

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
            label="식당"
            density="comfortable"
            class="mt-3"
          >
            <template #item="{ props, item }">
              <v-list-item
                v-bind="props"
                :title="item.raw.name"
                :subtitle="`잔액 ${won(item.raw.balance)}`"
              />
            </template>
            <template #no-data>
              <div class="pa-4 text-body-2 text-medium-emphasis">검색 결과가 없습니다.</div>
            </template>
          </v-autocomplete>

          <v-select
            v-if="authStore.isAdmin"
            v-model="filters.user_id"
            :items="users"
            item-title="name"
            item-value="id"
            clearable
            label="구성원"
            density="comfortable"
            class="mt-3"
          />

          <v-select
            v-model="filters.type"
            :items="typeOptions"
            clearable
            label="유형"
            density="comfortable"
            class="mt-3"
          />

          <v-text-field
            v-model="filters.query"
            label="검색어"
            placeholder="메모 · 식당명"
            density="comfortable"
            clearable
            class="mt-3"
          />

          <v-switch
            v-model="filters.include_voided"
            label="취소 포함"
            color="primary"
            density="compact"
            hide-details
            class="mt-1"
          />

          <v-btn variant="text" size="small" class="mt-2" @click="resetFilters">필터 초기화</v-btn>
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>

    <!-- 합계 -->
    <v-card variant="tonal" class="mb-3">
      <v-card-text class="py-3">
        <v-row dense>
          <v-col cols="6" sm="3">
            <div class="text-caption text-medium-emphasis">충전 합계</div>
            <div class="text-subtitle-2 font-weight-bold text-success">{{ won(sumCharge) }}</div>
          </v-col>
          <v-col cols="6" sm="3">
            <div class="text-caption text-medium-emphasis">사용 합계</div>
            <div class="text-subtitle-2 font-weight-bold text-error">{{ won(sumUse) }}</div>
          </v-col>
          <v-col cols="6" sm="3">
            <div class="text-caption text-medium-emphasis">정정 합계</div>
            <div class="text-subtitle-2 font-weight-bold text-warning">{{ won(sumAdjust) }}</div>
          </v-col>
          <v-col cols="6" sm="3">
            <div class="text-caption text-medium-emphasis">순액</div>
            <div
              class="text-subtitle-2 font-weight-bold"
              :class="net < 0 ? 'text-error' : 'text-primary'"
            >
              {{ won(net) }}
            </div>
          </v-col>
        </v-row>
        <div class="text-caption text-medium-emphasis mt-2">
          {{ periodLabel }} · 총 {{ total }}건
        </div>
      </v-card-text>
    </v-card>

    <!-- 데스크톱 : 표 -->
    <v-data-table-server
      v-if="mdAndUp"
      v-model:page="page"
      v-model:items-per-page="itemsPerPage"
      :headers="headers"
      :items="items"
      :items-length="total"
      :loading="loading"
      :items-per-page-options="[10, 25, 50, 100]"
      item-value="id"
      density="compact"
      no-data-text="조건에 맞는 거래가 없습니다."
      loading-text="불러오는 중입니다..."
    >
      <template v-slot:item.occurred_at="{ item }">
        <span class="text-caption">{{ dateTime(item.occurred_at) }}</span>
      </template>
      <template v-slot:item.restaurant_name="{ item }">
        <a class="text-primary" style="cursor: pointer" @click="goRestaurant(item.restaurant_id)">
          {{ item.restaurant_name }}
        </a>
      </template>
      <template v-slot:item.type="{ item }">
        <v-chip size="x-small" :color="txColor(item.type)" variant="flat">
          {{ txLabel(item.type) }}
        </v-chip>
        <v-chip v-if="item.is_voided" size="x-small" color="grey" variant="tonal" class="ml-1">
          취소됨
        </v-chip>
      </template>
      <template v-slot:item.signed_amount="{ item }">
        <span :class="item.is_voided ? 'text-decoration-line-through text-medium-emphasis' : ''">
          {{ signedText(item) }}
        </span>
      </template>
      <template v-slot:item.memo="{ item }">
        <span class="text-caption">{{ item.memo || '-' }}</span>
        <template v-if="item.is_voided">
          <div class="text-caption text-error">취소 사유: {{ item.void_reason || '-' }}</div>
        </template>
      </template>
      <template v-slot:item.created_by="{ item }">
        <span class="text-caption">{{ item.created_by ? item.created_by.name : '-' }}</span>
      </template>
      <template v-slot:item.actions="{ item }">
        <v-btn
          v-if="item.has_receipt"
          size="x-small"
          variant="text"
          @click="openReceipt(item.receipt_id)"
        >
          🧾
        </v-btn>
        <v-btn
          v-if="!item.is_voided"
          size="x-small"
          variant="text"
          color="error"
          @click="openVoid(item)"
        >
          기록 취소
        </v-btn>
      </template>
    </v-data-table-server>

    <!-- 모바일 : 카드 목록 -->
    <template v-else>
      <v-skeleton-loader
        v-if="loading && items.length === 0"
        type="list-item-two-line, list-item-two-line, list-item-two-line"
      />
      <v-alert v-else-if="items.length === 0" type="info" variant="tonal">
        조건에 맞는 거래가 없습니다.
      </v-alert>
      <v-card v-else variant="outlined">
        <template v-for="(t, i) in items" :key="t.id">
          <v-divider v-if="i > 0" />
          <div class="pa-3">
            <div class="d-flex align-center justify-space-between">
              <div class="d-flex align-center ga-2">
                <v-chip size="small" :color="txColor(t.type)" variant="flat">
                  {{ txLabel(t.type) }}
                </v-chip>
                <v-chip v-if="t.is_voided" size="small" color="grey" variant="tonal">취소됨</v-chip>
              </div>
              <div
                class="text-subtitle-1 font-weight-bold"
                :class="t.is_voided ? 'text-decoration-line-through text-medium-emphasis' : ''"
              >
                {{ signedText(t) }}
              </div>
            </div>
            <div class="mt-1">
              <a class="text-primary" style="cursor: pointer" @click="goRestaurant(t.restaurant_id)">
                {{ t.restaurant_name }}
              </a>
            </div>
            <div class="text-caption text-medium-emphasis">{{ dateTime(t.occurred_at) }}</div>
            <div v-if="t.memo" class="text-body-2 mt-1">{{ t.memo }}</div>
            <div class="text-caption text-medium-emphasis mt-1">
              기록: {{ t.created_by ? t.created_by.name : '알 수 없음' }}
            </div>
            <div v-if="t.is_voided" class="text-caption text-error mt-1">
              취소 사유: {{ t.void_reason || '(사유 없음)' }}
            </div>
            <div class="d-flex ga-2 mt-2">
              <v-btn v-if="t.has_receipt" size="small" variant="text" @click="openReceipt(t.receipt_id)">
                🧾 영수증
              </v-btn>
              <v-spacer />
              <v-btn v-if="!t.is_voided" size="small" variant="text" color="error" @click="openVoid(t)">
                기록 취소
              </v-btn>
            </div>
          </div>
        </template>
      </v-card>

      <div v-if="total > 0" class="d-flex align-center justify-space-between mt-3">
        <v-btn
          variant="outlined"
          size="small"
          :disabled="page <= 1 || loading"
          @click="page = page - 1"
        >
          이전
        </v-btn>
        <span class="text-caption">{{ page }} / {{ totalPages }} 페이지</span>
        <v-btn
          variant="outlined"
          size="small"
          :disabled="page >= totalPages || loading"
          @click="page = page + 1"
        >
          다음
        </v-btn>
      </div>
    </template>

    <!-- 기록 취소 -->
    <v-dialog v-model="voidDialog" max-width="480">
      <v-card>
        <v-card-title class="text-subtitle-1">기록 취소</v-card-title>
        <v-card-text>
          <div v-if="voidTarget" class="text-body-2 mb-3">
            {{ voidTarget.restaurant_name }} · {{ txLabel(voidTarget.type) }}
            {{ won(voidTarget.amount) }} · {{ dateTime(voidTarget.occurred_at) }}
          </div>
          <div class="text-body-2 text-medium-emphasis mb-2">
            기록은 삭제되지 않고 취소 표시만 남습니다. 사유를 남겨 주세요.
          </div>
          <v-text-field
            v-model="voidReason"
            label="취소 사유"
            density="comfortable"
            :error="voidReason.trim().length === 0"
            autofocus
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="voiding" @click="voidDialog = false">닫기</v-btn>
          <v-btn
            color="error"
            variant="flat"
            :loading="voiding"
            :disabled="!canVoid"
            @click="confirmVoid"
          >
            기록 취소
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 영수증 이미지 -->
    <v-dialog v-model="imageDialog" max-width="640">
      <v-card>
        <v-img :src="imageUrl" max-height="80vh" contain />
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="imageDialog = false">닫기</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
