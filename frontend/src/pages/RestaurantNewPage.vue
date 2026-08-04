<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { restaurantApi, errorMessage } from '@/api/endpoints'
import type { RestaurantCreateIn } from '@/api/types'
import { nowLocalInput, won } from '@/utils/format'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const appStore = useAppStore()

function toInt(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

const form = ref({
  name: '',
  business_number: '',
  address: '',
  phone: '',
  memo: '',
  initial_balance: 0 as number | string,
  occurred_at: nowLocalInput(),
})

const submitting = ref(false)
const dupMessage = ref('')

const balanceInt = computed(() => toInt(form.value.initial_balance))
const nameOk = computed(() => form.value.name.trim().length > 0)
const balanceOk = computed(() => balanceInt.value >= 0)
const canSubmit = computed(() => nameOk.value && balanceOk.value && !submitting.value)

async function submit() {
  if (!canSubmit.value) {
    if (!nameOk.value) appStore.toast('식당명을 입력해 주세요.', 'warning')
    else if (!balanceOk.value) appStore.toast('잔액은 0원 이상이어야 합니다.', 'warning')
    return
  }
  dupMessage.value = ''
  const body: RestaurantCreateIn = {
    name: form.value.name.trim(),
    business_number: form.value.business_number.trim() || null,
    address: form.value.address.trim() || null,
    phone: form.value.phone.trim() || null,
    memo: form.value.memo.trim() || null,
    initial_balance: balanceInt.value,
    initial_balance_memo: '초기 잔액 등록',
    occurred_at: form.value.occurred_at || null,
  }
  submitting.value = true
  try {
    const created = await restaurantApi.create(body)
    appStore.toast(`'${created.name}'을 등록했습니다.`, 'success')
    router.push(`/restaurants/${created.id}`)
  } catch (e) {
    const msg = errorMessage(e)
    if (msg.includes('사업자등록번호')) dupMessage.value = msg
    appStore.toast(msg, 'error')
  } finally {
    submitting.value = false
  }
}

function searchExisting() {
  const q = form.value.business_number.trim() || form.value.name.trim()
  router.push({ path: '/', query: q ? { query: q } : {} })
}
</script>

<template>
  <v-container class="pa-3" style="max-width: 720px">
    <h1 class="text-h6 mb-1">식당 직접 등록</h1>
    <div class="text-body-2 text-medium-emphasis mb-3">이미 선결제해둔 식당 추가</div>

    <v-alert type="info" variant="tonal" class="mb-4">
      이미 선결제해둔 식당을 앱에 추가합니다. 영수증 없이 현재 남은 잔액만 입력하면 됩니다.
    </v-alert>

    <v-alert v-if="dupMessage" type="warning" variant="tonal" class="mb-4">
      <div class="text-body-2">{{ dupMessage }}</div>
      <v-btn size="small" variant="flat" color="warning" class="mt-3" @click="searchExisting">
        기존 식당 찾아보기
      </v-btn>
    </v-alert>

    <v-text-field
      v-model="form.name"
      label="식당명"
      density="comfortable"
      :error="!nameOk"
      hint="필수 항목입니다."
      persistent-hint
    />

    <v-text-field
      v-model="form.business_number"
      label="사업자등록번호 (선택)"
      density="comfortable"
      class="mt-4"
      placeholder="123-45-67890"
      hint="영수증 매칭에 사용됩니다. 모르면 비워두세요."
      persistent-hint
    />

    <v-text-field v-model="form.address" label="주소 (선택)" density="comfortable" class="mt-4" />
    <v-text-field v-model="form.phone" label="전화 (선택)" density="comfortable" class="mt-4" />
    <v-textarea v-model="form.memo" label="메모 (선택)" rows="2" density="comfortable" class="mt-4" />

    <v-divider class="my-5" />

    <div class="text-subtitle-1 mb-2">현재 남은 선결제 잔액</div>
    <v-text-field
      v-model="form.initial_balance"
      label="현재 남은 선결제 잔액"
      type="number"
      inputmode="numeric"
      suffix="원"
      density="comfortable"
      :error="!balanceOk"
      hint="지금까지 사용한 금액을 빼고 남은 금액을 입력하세요."
      persistent-hint
    />

    <div class="text-caption text-medium-emphasis mb-1 mt-4">기준 일시</div>
    <input
      v-model="form.occurred_at"
      type="datetime-local"
      class="pa-2 rounded"
      style="width: 100%; border: 1px solid rgba(128, 128, 128, 0.5)"
    />
    <div class="text-caption text-medium-emphasis mt-1 mb-4">
      이 시점에 남은 잔액으로 기록됩니다.
    </div>

    <v-card variant="tonal" class="mb-4">
      <v-card-text class="py-3">
        <div v-if="balanceInt > 0" class="text-body-2">
          등록 직후 잔액: <span class="font-weight-bold">{{ won(balanceInt) }}</span>
          <span class="text-medium-emphasis"> (‘초기 잔액 등록’ 메모로 충전 기록이 남습니다)</span>
        </div>
        <div v-else class="text-body-2">
          잔액을 0원으로 등록합니다. 나중에 선결제 충전으로 채울 수 있습니다.
        </div>
      </v-card-text>
    </v-card>

    <v-btn
      color="primary"
      size="large"
      block
      :loading="submitting"
      :disabled="!canSubmit"
      @click="submit"
    >
      식당 등록하기
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
  </v-container>
</template>
