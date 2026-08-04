<script setup lang="ts">
/**
 * 영수증 없이 기록 — 사용(차감) / 선결제 충전을 직접 입력한다.
 *
 * 화면 규약은 docs/DESIGN.md: 이모지 대신 아이콘, 카드는 헤어라인,
 * 금액은 반드시 `won()` + `class="amount"`, 채운 버튼은 화면당 1개.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { restaurantApi, transactionApi, errorMessage, isInsufficientBalance } from '@/api/endpoints'
import type { RestaurantDetail, RestaurantSummary, TransactionCreateIn } from '@/api/types'
import { bizNumber, nowLocalInput, won } from '@/utils/format'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

function toInt(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

/* ------------------------------------------------------------------ */
/* 상태                                                                */
/* ------------------------------------------------------------------ */

const type = ref<'USE' | 'CHARGE'>('USE')
const picked = ref<RestaurantSummary | null>(null)
const detail = ref<RestaurantDetail | null>(null)
const options = ref<RestaurantSummary[]>([])
const search = ref('')
const searching = ref(false)
const loadingDetail = ref(false)

const amount = ref<number | string>('')
const occurredAt = ref(nowLocalInput())
const memo = ref('')

const submitting = ref(false)
const negDialog = ref(false)
const negMessage = ref('')

const amountInt = computed(() => toInt(amount.value))
/** 선택된 식당 — 상세를 이미 읽었으면 상세(최신 잔액)를 쓴다 */
const current = computed<RestaurantSummary | null>(() => {
  if (picked.value && detail.value && detail.value.id === picked.value.id) return detail.value
  return picked.value
})
const balance = computed(() => current.value?.balance ?? 0)
const isUse = computed(() => type.value === 'USE')
const expected = computed(() =>
  isUse.value ? balance.value - amountInt.value : balance.value + amountInt.value,
)
const canSubmit = computed(() => !!picked.value && amountInt.value > 0 && !submitting.value)

/** 잔액 색 — 음수만 error, 임계값 미만은 warning, 정상은 기본 잉크색 (DESIGN §1) */
const balanceClass = computed(() => {
  if (!current.value) return ''
  if (current.value.balance < 0) return 'text-error'
  if (current.value.is_low_balance) return 'text-warning'
  return ''
})

/* ------------------------------------------------------------------ */
/* 식당 검색                                                            */
/* ------------------------------------------------------------------ */

async function fetchOptions(q: string) {
  searching.value = true
  try {
    const res = await restaurantApi.list({ query: q || undefined, sort: 'balance_desc' })
    options.value = res.items
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    searching.value = false
  }
}

let searchTimer: number | undefined
watch(search, (v) => {
  const q = (v ?? '').trim()
  if (picked.value && q === picked.value.name) return
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => fetchOptions(q), 250)
})

/** 선택 후에는 항상 최신 잔액을 다시 읽어 온다 */
watch(
  () => picked.value?.id ?? null,
  async (id) => {
    if (!id || detail.value?.id === id) return
    loadingDetail.value = true
    try {
      const d = await restaurantApi.get(id)
      detail.value = d
      if (!options.value.some((r) => r.id === d.id)) options.value = [d, ...options.value]
    } catch (e) {
      appStore.toast(errorMessage(e), 'error')
    } finally {
      loadingDetail.value = false
    }
  },
)

/* ------------------------------------------------------------------ */
/* 저장                                                                */
/* ------------------------------------------------------------------ */

async function submit(allowNegative = false) {
  if (!picked.value) {
    appStore.toast('식당을 먼저 선택해 주세요.', 'warning')
    return
  }
  if (amountInt.value <= 0) {
    appStore.toast('금액을 입력해 주세요.', 'warning')
    return
  }
  if (submitting.value) return

  const body: TransactionCreateIn = {
    restaurant_id: picked.value.id,
    type: type.value,
    amount: amountInt.value,
    occurred_at: occurredAt.value || null,
    memo: memo.value.trim() || null,
    allow_negative: allowNegative,
  }

  submitting.value = true
  try {
    const res = await transactionApi.create(body)
    for (const w of res.warnings) appStore.toast(w, 'warning')
    appStore.toast(
      isUse.value ? '사용 기록을 저장했습니다.' : '선결제 충전을 기록했습니다.',
      'success',
    )
    router.push(`/restaurants/${res.transaction.restaurant_id}`)
  } catch (e) {
    if (isInsufficientBalance(e)) {
      negMessage.value = errorMessage(e)
      negDialog.value = true
    } else {
      appStore.toast(errorMessage(e), 'error')
    }
  } finally {
    submitting.value = false
  }
}

function proceedNegative() {
  negDialog.value = false
  submit(true)
}

/* ------------------------------------------------------------------ */
/* 초기화                                                              */
/* ------------------------------------------------------------------ */

onMounted(async () => {
  await fetchOptions('')
  const raw = route.query.restaurant_id
  const id = Number(Array.isArray(raw) ? raw[0] : raw)
  if (Number.isFinite(id) && id > 0) {
    const found = options.value.find((r) => r.id === id)
    if (found) {
      picked.value = found
    } else {
      try {
        const d = await restaurantApi.get(id)
        detail.value = d
        picked.value = d
      } catch (e) {
        appStore.toast(errorMessage(e), 'error')
      }
    }
  }
})
</script>

<template>
  <v-container class="flow-container pa-4">
    <h1 class="page-title">영수증 없이 기록</h1>
    <div class="hint-text mt-1 mb-4">영수증이 없거나 나중에 정리할 때 사용합니다.</div>

    <!-- ── 유형 전환 ─────────────────────────────────────────────── -->
    <v-row dense class="mb-2">
      <v-col cols="12" sm="6">
        <v-card
          class="choice-card pa-4 h-100"
          :class="isUse ? 'choice-card--on' : ''"
          role="button"
          tabindex="0"
          :aria-pressed="isUse"
          @click="type = 'USE'"
          @keydown.enter="type = 'USE'"
          @keydown.space.prevent="type = 'USE'"
        >
          <div class="d-flex align-start">
            <v-icon
              icon="mdi-arrow-up-circle-outline"
              color="error"
              size="22"
              class="me-3 flex-shrink-0"
            />
            <div class="min-w-0">
              <div class="text-body-2 font-weight-medium">잔액에서 차감</div>
              <div class="hint-text mt-1">선결제 잔액에서 쓴 금액을 기록합니다.</div>
            </div>
            <v-spacer />
            <v-icon
              v-if="isUse"
              icon="mdi-check-circle-outline"
              color="primary"
              size="20"
              class="ms-2 flex-shrink-0"
            />
          </div>
        </v-card>
      </v-col>
      <v-col cols="12" sm="6">
        <v-card
          class="choice-card pa-4 h-100"
          :class="!isUse ? 'choice-card--on' : ''"
          role="button"
          tabindex="0"
          :aria-pressed="!isUse"
          @click="type = 'CHARGE'"
          @keydown.enter="type = 'CHARGE'"
          @keydown.space.prevent="type = 'CHARGE'"
        >
          <div class="d-flex align-start">
            <v-icon
              icon="mdi-arrow-down-circle-outline"
              color="success"
              size="22"
              class="me-3 flex-shrink-0"
            />
            <div class="min-w-0">
              <div class="text-body-2 font-weight-medium">선결제 충전하기</div>
              <div class="hint-text mt-1">이번에 미리 결제한 금액을 잔액에 더합니다.</div>
            </div>
            <v-spacer />
            <v-icon
              v-if="!isUse"
              icon="mdi-check-circle-outline"
              color="primary"
              size="20"
              class="ms-2 flex-shrink-0"
            />
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- ── 식당 선택 ─────────────────────────────────────────────── -->
    <v-autocomplete
      v-model="picked"
      v-model:search="search"
      :items="options"
      :loading="searching"
      item-title="name"
      item-value="id"
      return-object
      no-filter
      clearable
      label="식당"
      placeholder="식당명 · 주소 · 사업자번호로 검색"
      prepend-inner-icon="mdi-magnify"
      class="mt-4"
    >
      <template #item="{ props: itemProps, item }">
        <v-list-item v-bind="itemProps">
          <template #title>
            <div class="d-flex align-center ga-3">
              <span class="text-body-2 text-truncate flex-grow-1">{{ item.raw.name }}</span>
              <span class="amount text-medium-emphasis flex-shrink-0">
                {{ won(item.raw.balance) }}
              </span>
            </div>
          </template>
        </v-list-item>
      </template>
      <template #no-data>
        <div class="pa-4 hint-text">검색 결과가 없습니다. 식당을 먼저 등록해 주세요.</div>
      </template>
    </v-autocomplete>

    <!-- ── 선택된 식당 ───────────────────────────────────────────── -->
    <v-skeleton-loader v-if="loadingDetail" type="card" class="mt-4 mb-4" />
    <v-card v-else-if="current" class="mt-4 mb-4">
      <div class="px-4 py-3">
        <div class="d-flex align-center">
          <v-icon icon="mdi-storefront-outline" size="18" class="me-2 text-medium-emphasis" />
          <span class="text-body-2 font-weight-medium text-truncate">{{ current.name }}</span>
          <v-spacer />
          <v-chip v-if="current.is_low_balance" color="warning" class="ms-2 flex-shrink-0">
            잔액 부족
          </v-chip>
        </div>
        <div class="d-flex align-center mt-2">
          <v-icon
            icon="mdi-card-account-details-outline"
            size="18"
            class="me-2 text-medium-emphasis"
          />
          <span class="text-body-2 text-medium-emphasis">
            {{ bizNumber(current.business_number) }}
          </span>
        </div>
      </div>
      <v-divider />
      <div class="px-4 py-3 d-flex align-center justify-space-between ga-3">
        <span class="field-label">현재 잔액</span>
        <span class="metric-value amount" :class="balanceClass">{{ won(balance) }}</span>
      </div>
    </v-card>
    <v-alert
      v-else
      type="info"
      icon="mdi-information-outline"
      density="comfortable"
      class="mt-4 mb-4"
    >
      먼저 식당을 선택해 주세요.
    </v-alert>

    <!-- ── 금액 · 일시 · 메모 ────────────────────────────────────── -->
    <div class="d-flex flex-column ga-4">
      <v-text-field
        v-model="amount"
        :label="isUse ? '사용 금액' : '충전 금액'"
        type="number"
        inputmode="numeric"
        suffix="원"
        density="default"
        class="amount-field"
        prepend-inner-icon="mdi-cash"
      />

      <!-- naive 문자열(YYYY-MM-DDTHH:mm)을 그대로 보낸다 — 서버가 KST 로 해석 -->
      <v-text-field
        v-model="occurredAt"
        :label="isUse ? '사용 일시' : '충전 일시'"
        type="datetime-local"
        prepend-inner-icon="mdi-calendar-clock"
        persistent-placeholder
      />

      <v-textarea
        v-model="memo"
        label="메모 (선택)"
        rows="2"
        prepend-inner-icon="mdi-note-text-outline"
      />
    </div>

    <!-- ── 예상 잔액 미리보기 ────────────────────────────────────── -->
    <v-card v-if="picked && amountInt > 0" class="mt-4 mb-4">
      <div class="px-4 py-3 d-flex align-center justify-space-between ga-3">
        <span class="field-label">{{ isUse ? '차감 후 예상 잔액' : '충전 후 예상 잔액' }}</span>
        <span class="metric-value amount" :class="isUse && expected < 0 ? 'text-error' : ''">
          {{ won(expected) }}
        </span>
      </div>
      <template v-if="isUse && expected < 0">
        <v-divider />
        <div class="px-4 py-3 d-flex align-start hint-text text-error">
          <v-icon icon="mdi-alert-outline" size="16" class="me-1 flex-shrink-0 mt-1" />
          <span>잔액이 마이너스가 됩니다. 저장할 때 한 번 더 확인합니다.</span>
        </div>
      </template>
    </v-card>

    <v-btn
      color="primary"
      size="large"
      block
      :prepend-icon="isUse ? 'mdi-arrow-up-circle-outline' : 'mdi-arrow-down-circle-outline'"
      :loading="submitting"
      :disabled="!canSubmit"
      @click="submit(false)"
    >
      {{ isUse ? '잔액에서 차감하기' : '선결제 충전하기' }}
    </v-btn>
    <v-btn
      variant="text"
      size="large"
      block
      class="mt-2"
      :disabled="submitting"
      @click="router.push('/')"
    >
      취소
    </v-btn>

    <!-- 잔액 부족 확인 -->
    <v-dialog v-model="negDialog" max-width="420">
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-alert-outline" color="warning" size="20" class="me-2" />
          <span class="section-title">잔액이 부족합니다</span>
        </v-card-title>
        <v-card-text>
          <div class="text-body-2">{{ negMessage }}</div>
          <div class="text-body-2 mt-2">
            잔액이 부족합니다. 잔액이 마이너스로 기록됩니다. 계속할까요?
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="negDialog = false">취소</v-btn>
          <v-btn color="error" variant="tonal" @click="proceedNegative">계속하기</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
/* 선택 상태 = 브랜드 테두리 + 톤 배경. `:hover` 보다 우선하도록 함께 선언한다.
   비선택 테두리는 헤어라인 토큰으로 고정한다 (Vuetify outlined 는 currentColor). */
.choice-card {
  border-color: rgba(var(--v-border-color), var(--v-border-opacity));
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease;
}

.choice-card:hover {
  background-color: rgba(var(--v-theme-on-surface), 0.03);
}

.choice-card:focus-visible {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
}

.choice-card--on,
.choice-card--on:hover {
  border-color: rgb(var(--v-theme-primary));
  background-color: rgba(var(--v-theme-primary), 0.08);
}

/* flex 안에서 text-truncate 가 동작하려면 min-width 를 풀어줘야 한다 */
.min-w-0 {
  min-width: 0;
}

/* 이 화면의 대표 숫자 — 입력칸에서도 크게 보인다 */
.amount-field :deep(input) {
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
</style>
