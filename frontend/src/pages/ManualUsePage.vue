<script setup lang="ts">
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
  <v-container class="pa-3" style="max-width: 720px">
    <h1 class="text-h6 mb-1">영수증 없이 기록</h1>
    <div class="text-body-2 text-medium-emphasis mb-3">
      영수증이 없거나 나중에 정리할 때 사용합니다.
    </div>

    <!-- 유형 전환 -->
    <v-btn-toggle v-model="type" mandatory divided color="primary" class="mb-4" style="width: 100%">
      <v-btn value="USE" class="flex-grow-1">잔액에서 차감</v-btn>
      <v-btn value="CHARGE" class="flex-grow-1">선결제 충전하기</v-btn>
    </v-btn-toggle>

    <v-alert :type="isUse ? 'info' : 'success'" variant="tonal" class="mb-4">
      {{
        isUse
          ? '선결제 잔액에서 쓴 금액을 기록합니다.'
          : '이번에 미리 결제한 금액을 잔액에 더합니다.'
      }}
    </v-alert>

    <!-- 식당 선택 -->
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
      density="comfortable"
    >
      <template #item="{ props, item }">
        <v-list-item
          v-bind="props"
          :title="item.raw.name"
          :subtitle="`잔액 ${won(item.raw.balance)}`"
        />
      </template>
      <template #no-data>
        <div class="pa-4 text-body-2 text-medium-emphasis">
          검색 결과가 없습니다. 식당을 먼저 등록해 주세요.
        </div>
      </template>
    </v-autocomplete>

    <!-- 선택된 식당 -->
    <v-skeleton-loader v-if="loadingDetail" type="card" class="mb-4" />
    <v-card v-else-if="current" variant="outlined" class="mb-4">
      <v-card-text>
        <div class="d-flex align-center justify-space-between">
          <div>
            <div class="text-subtitle-1 font-weight-medium">{{ current.name }}</div>
            <div class="text-caption text-medium-emphasis">
              {{ bizNumber(current.business_number) }}
            </div>
          </div>
          <v-chip v-if="current.is_low_balance" color="error" size="small" variant="flat">
            잔액 부족
          </v-chip>
        </div>
        <div class="mt-2 text-body-2 text-medium-emphasis">현재 잔액</div>
        <div class="text-h5" :class="balance < 0 ? 'text-error' : 'text-primary'">
          {{ won(balance) }}
        </div>
      </v-card-text>
    </v-card>
    <v-alert v-else type="info" variant="tonal" class="mb-4">
      먼저 식당을 선택해 주세요.
    </v-alert>

    <!-- 금액 -->
    <v-text-field
      v-model="amount"
      :label="isUse ? '사용 금액' : '충전 금액'"
      type="number"
      inputmode="numeric"
      suffix="원"
      density="comfortable"
    />

    <!-- 일시 -->
    <div class="text-caption text-medium-emphasis mb-1">
      {{ isUse ? '사용 일시' : '충전 일시' }}
    </div>
    <input
      v-model="occurredAt"
      type="datetime-local"
      class="pa-2 rounded mb-4"
      style="width: 100%; border: 1px solid rgba(128, 128, 128, 0.5)"
    />

    <v-textarea v-model="memo" label="메모 (선택)" rows="2" density="comfortable" class="mb-2" />

    <!-- 미리보기 -->
    <v-card v-if="picked && amountInt > 0" variant="tonal" class="mb-4">
      <v-card-text class="py-3">
        <div v-if="isUse" class="text-body-1">
          차감 후 예상 잔액:
          <span :class="expected < 0 ? 'text-error font-weight-bold' : 'font-weight-bold'">
            {{ won(expected) }}
          </span>
        </div>
        <div v-else class="text-body-1">
          충전 후 예상 잔액:
          <span class="font-weight-bold">{{ won(expected) }}</span>
        </div>
        <div v-if="isUse && expected < 0" class="text-caption text-error mt-1">
          잔액이 마이너스가 됩니다. 저장할 때 한 번 더 확인합니다.
        </div>
      </v-card-text>
    </v-card>

    <v-btn
      :color="isUse ? 'error' : 'success'"
      size="large"
      block
      :loading="submitting"
      :disabled="!canSubmit"
      @click="submit(false)"
    >
      {{ isUse ? '잔액에서 차감하기' : '선결제 충전하기' }}
    </v-btn>
    <v-btn variant="text" size="large" block class="mt-2" :disabled="submitting" @click="router.push('/')">
      취소
    </v-btn>

    <!-- 잔액 부족 확인 -->
    <v-dialog v-model="negDialog" max-width="420">
      <v-card>
        <v-card-title class="text-subtitle-1">잔액이 부족합니다</v-card-title>
        <v-card-text>
          <div class="text-body-2">{{ negMessage }}</div>
          <div class="text-body-2 mt-2">
            잔액이 부족합니다. 잔액이 마이너스로 기록됩니다. 계속할까요?
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="negDialog = false">취소</v-btn>
          <v-btn color="error" variant="flat" @click="proceedNegative">계속하기</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
