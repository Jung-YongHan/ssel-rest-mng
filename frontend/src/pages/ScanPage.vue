<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { receiptApi, errorMessage, isInsufficientBalance } from '@/api/endpoints'
import type {
  ConfirmIn,
  ConfirmOut,
  ParsedReceipt,
  ReceiptUploadOut,
  RestaurantSummary,
} from '@/api/types'
import { bizNumber, dateTime, nowLocalInput, txLabel, txColor, won } from '@/utils/format'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()

/* ------------------------------------------------------------------ */
/* 로컬 유틸                                                           */
/* ------------------------------------------------------------------ */

function toInt(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

/** ISO(UTC) → datetime-local 용 KST 벽시계 문자열 */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return nowLocalInput()
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return nowLocalInput()
  const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return (
    `${kst.getUTCFullYear()}-${p(kst.getUTCMonth() + 1)}-${p(kst.getUTCDate())}` +
    `T${p(kst.getUTCHours())}:${p(kst.getUTCMinutes())}`
  )
}

/* ------------------------------------------------------------------ */
/* 단계 상태                                                           */
/* ------------------------------------------------------------------ */

const steps = [
  { n: 1, label: '촬영' },
  { n: 2, label: '인식 확인' },
  { n: 3, label: '식당 확인' },
  { n: 4, label: '처리 방식' },
  { n: 5, label: '완료' },
]
const step = ref(1)

/* 1단계 --------------------------------------------------------------- */
const cameraInput = ref<HTMLInputElement | null>(null)
const galleryInput = ref<HTMLInputElement | null>(null)
const previewUrl = ref<string | null>(null)
const uploading = ref(false)
const uploadPct = ref(0)
const restoring = ref(false)

/* 2단계 --------------------------------------------------------------- */
const data = ref<ReceiptUploadOut | null>(null)
const reocring = ref(false)
const manualMode = ref(false)
const form = ref({
  store_name: '',
  business_number: '',
  address: '',
  phone: '',
  total_amount: '' as number | string,
  paid_at: nowLocalInput(),
})
const totalAmount = computed(() => toInt(form.value.total_amount))

/* 3단계 --------------------------------------------------------------- */
type Mode = 'existing' | 'new'
const mode = ref<Mode>('new')
const selected = ref<RestaurantSummary | null>(null)
const matchRejected = ref(false)
const candidateId = ref<number | null>(null)
const newRestaurant = ref({
  name: '',
  business_number: '',
  address: '',
  phone: '',
  memo: '',
})

/* 4단계 --------------------------------------------------------------- */
const action = ref<'register_and_charge' | 'charge' | 'use'>('register_and_charge')
const chargeAmount = ref<number | string>('')
const useAmount = ref<number | string>(0)
const memo = ref('')
const submitting = ref(false)
const negDialog = ref(false)
const negMessage = ref('')

/* 5단계 --------------------------------------------------------------- */
const result = ref<ConfirmOut | null>(null)

/* 영수증 확대 보기 */
const imageDialog = ref(false)

/* ------------------------------------------------------------------ */
/* 파생 값                                                             */
/* ------------------------------------------------------------------ */

const receipt = computed(() => data.value?.receipt ?? null)
const match = computed(() => data.value?.match ?? null)
const duplicate = computed(() => data.value?.duplicate ?? null)
const candidates = computed(() => data.value?.match.candidates ?? [])
const ocrFailed = computed(() => receipt.value?.ocr_status === 'failed')
const alreadyConsumed = computed(() => !!receipt.value?.consumed_at)
const imageSrc = computed(() => (receipt.value ? receiptApi.imageUrl(receipt.value.id) : ''))

/** 확정 매칭을 아직 거절하지 않았다면 그 식당을 물어본다 */
const askMatched = computed(() => !!match.value?.restaurant && !matchRejected.value)
/** 후보 목록을 보여줄 상황인가 */
const showCandidates = computed(
  () => !askMatched.value && mode.value === 'existing' && candidates.value.length > 0,
)
/** 새 식당 등록 폼을 보여줄 상황인가 */
const showNewForm = computed(() => !askMatched.value && mode.value === 'new')

const step2Valid = computed(() => form.value.store_name.trim().length > 0 && totalAmount.value > 0)
const step3Valid = computed(() =>
  mode.value === 'existing' ? !!selected.value : newRestaurant.value.name.trim().length > 0,
)

const chargeInt = computed(() => toInt(chargeAmount.value))
const useInt = computed(() => toInt(useAmount.value))

const step4Valid = computed(() => {
  if (action.value === 'use') return useInt.value > 0
  return chargeInt.value > 0 && useInt.value >= 0
})

const expectedBalance = computed(() => {
  const base = selected.value?.balance ?? 0
  if (action.value === 'use') return base - useInt.value
  return base + chargeInt.value - useInt.value
})

/* ------------------------------------------------------------------ */
/* 1단계 : 업로드                                                      */
/* ------------------------------------------------------------------ */

function pickCamera() {
  cameraInput.value?.click()
}
function pickGallery() {
  galleryInput.value?.click()
}

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files && input.files[0]
  if (!file) return
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(file)
  input.value = ''

  uploading.value = true
  uploadPct.value = 0
  try {
    const res = await receiptApi.upload(file, (pct: number) => {
      uploadPct.value = pct
    })
    applyUpload(res)
    step.value = 2
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    uploading.value = false
  }
}

/** 영수증·매칭 결과를 반영하고 3단계 선택 상태를 초기화한다 */
function applyMatch(res: ReceiptUploadOut) {
  data.value = res
  manualMode.value = false
  matchRejected.value = false
  candidateId.value = null
  selected.value = null
  mode.value = res.match.restaurant || res.match.candidates.length > 0 ? 'existing' : 'new'
}

function applyUpload(res: ReceiptUploadOut) {
  const p = res.parsed
  form.value = {
    store_name: p.store_name ?? '',
    business_number: p.business_number ?? '',
    address: p.address ?? '',
    phone: p.phone ?? '',
    total_amount: p.total_amount ?? '',
    paid_at: toLocalInput(p.paid_at),
  }
  applyMatch(res)
}

async function retryOcr() {
  if (!receipt.value) return
  reocring.value = true
  try {
    const res = await receiptApi.reocr(receipt.value.id)
    // 사용자가 직접 입력한 값은 지우지 않고, 새로 읽힌 값만 덮어쓴다.
    const p = res.parsed
    if (p.store_name) form.value.store_name = p.store_name
    if (p.business_number) form.value.business_number = p.business_number
    if (p.address) form.value.address = p.address
    if (p.phone) form.value.phone = p.phone
    if (p.total_amount) form.value.total_amount = p.total_amount
    if (p.paid_at) form.value.paid_at = toLocalInput(p.paid_at)
    applyMatch(res)
    if (res.receipt.ocr_status === 'done') {
      appStore.toast('영수증을 다시 인식했습니다.', 'success')
    } else {
      appStore.toast('여전히 인식에 실패했습니다. 직접 입력해 주세요.', 'warning')
    }
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    reocring.value = false
  }
}

/* ------------------------------------------------------------------ */
/* 2 → 3 단계                                                          */
/* ------------------------------------------------------------------ */

function goStep3() {
  if (!step2Valid.value) {
    appStore.toast('상호명과 합계금액을 입력해 주세요.', 'warning')
    return
  }
  newRestaurant.value = {
    name: form.value.store_name.trim(),
    business_number: form.value.business_number.trim(),
    address: form.value.address.trim(),
    phone: form.value.phone.trim(),
    memo: '',
  }
  step.value = 3
}

/* ------------------------------------------------------------------ */
/* 3 → 4 단계                                                          */
/* ------------------------------------------------------------------ */

function acceptMatched() {
  if (!match.value?.restaurant) return
  selected.value = match.value.restaurant
  mode.value = 'existing'
  goStep4()
}

function rejectMatched() {
  matchRejected.value = true
  selected.value = null
  mode.value = candidates.value.length > 0 ? 'existing' : 'new'
}

function chooseCandidate(id: number) {
  candidateId.value = id
  const found = candidates.value.find((c) => c.restaurant.id === id)
  if (found) {
    selected.value = found.restaurant
    mode.value = 'existing'
  }
}

function confirmCandidate() {
  if (!selected.value) {
    appStore.toast('식당을 선택해 주세요.', 'warning')
    return
  }
  goStep4()
}

function switchToNew() {
  matchRejected.value = true
  mode.value = 'new'
  selected.value = null
  candidateId.value = null
}

function goStep4() {
  if (!step3Valid.value) {
    appStore.toast('식당 정보를 확인해 주세요.', 'warning')
    return
  }
  if (mode.value === 'new') {
    action.value = 'register_and_charge'
    chargeAmount.value = totalAmount.value
    useAmount.value = 0
  } else {
    action.value = 'charge'
    chargeAmount.value = totalAmount.value
    useAmount.value = 0
  }
  step.value = 4
}

function pickAction(a: 'charge' | 'use') {
  action.value = a
  if (a === 'charge') {
    chargeAmount.value = totalAmount.value
    useAmount.value = 0
  } else {
    useAmount.value = totalAmount.value
    chargeAmount.value = ''
  }
}

/* ------------------------------------------------------------------ */
/* 확정                                                                */
/* ------------------------------------------------------------------ */

function parsedPayload(): ParsedReceipt {
  return {
    store_name: form.value.store_name.trim() || null,
    business_number: form.value.business_number.trim() || null,
    address: form.value.address.trim() || null,
    phone: form.value.phone.trim() || null,
    total_amount: totalAmount.value > 0 ? totalAmount.value : null,
    paid_at: form.value.paid_at || null,
  }
}

function buildBody(allowNegative: boolean): ConfirmIn {
  const isNew = mode.value === 'new'
  return {
    action: action.value,
    restaurant_id: isNew ? null : (selected.value?.id ?? null),
    restaurant: isNew
      ? {
          name: newRestaurant.value.name.trim(),
          business_number: newRestaurant.value.business_number.trim() || null,
          address: newRestaurant.value.address.trim() || null,
          phone: newRestaurant.value.phone.trim() || null,
          memo: newRestaurant.value.memo.trim() || null,
        }
      : null,
    charge_amount: action.value === 'use' ? null : chargeInt.value,
    use_amount: useInt.value > 0 ? useInt.value : 0,
    occurred_at: form.value.paid_at || null,
    memo: memo.value.trim() || null,
    allow_negative: allowNegative,
    parsed: parsedPayload(),
  }
}

async function submit(allowNegative = false) {
  if (!receipt.value || submitting.value) return
  if (!step4Valid.value) {
    appStore.toast('금액을 확인해 주세요.', 'warning')
    return
  }
  submitting.value = true
  try {
    const res = await receiptApi.confirm(receipt.value.id, buildBody(allowNegative))
    result.value = res
    step.value = 5
    appStore.toast('기록을 저장했습니다.', 'success')
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
/* 초기화 / 복귀                                                        */
/* ------------------------------------------------------------------ */

function resetAll() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = null
  data.value = null
  result.value = null
  selected.value = null
  candidateId.value = null
  matchRejected.value = false
  manualMode.value = false
  mode.value = 'new'
  action.value = 'register_and_charge'
  chargeAmount.value = ''
  useAmount.value = 0
  memo.value = ''
  uploadPct.value = 0
  form.value = {
    store_name: '',
    business_number: '',
    address: '',
    phone: '',
    total_amount: '',
    paid_at: nowLocalInput(),
  }
  step.value = 1
}

function goHome() {
  router.push('/')
}

function goDetail() {
  if (result.value) router.push(`/restaurants/${result.value.restaurant.id}`)
  else if (selected.value) router.push(`/restaurants/${selected.value.id}`)
}

onMounted(async () => {
  // 다른 화면에서 /scan?receipt_id=123 으로 돌아온 경우 이어서 진행
  const raw = route.query.receipt_id
  const id = Number(Array.isArray(raw) ? raw[0] : raw)
  if (!Number.isFinite(id) || id <= 0) return
  restoring.value = true
  try {
    const res = await receiptApi.get(id)
    applyUpload(res)
    step.value = 2
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    restoring.value = false
  }
})

onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<template>
  <v-container class="pa-3" style="max-width: 720px">
    <h1 class="text-h6 mb-3">영수증 스캔</h1>

    <!-- 단계 표시 -->
    <div class="d-flex align-start mb-4">
      <div v-for="s in steps" :key="s.n" class="text-center flex-grow-1">
        <v-chip
          size="small"
          :color="step >= s.n ? 'primary' : 'grey'"
          :variant="step >= s.n ? 'flat' : 'outlined'"
        >
          {{ s.n }}
        </v-chip>
        <div class="text-caption mt-1" :class="step === s.n ? 'font-weight-bold' : 'text-medium-emphasis'">
          {{ s.label }}
        </div>
      </div>
    </div>

    <v-skeleton-loader v-if="restoring" type="card" class="mb-4" />

    <!-- 이미 처리된 영수증 안내 -->
    <v-alert v-if="alreadyConsumed && step < 5" type="info" variant="tonal" class="mb-4">
      <div class="font-weight-medium">이미 처리된 영수증입니다.</div>
      <div class="text-body-2">
        이 영수증은 {{ dateTime(receipt?.consumed_at) }} 에 이미 기록되었습니다. 같은 영수증을 두 번
        기록하지 않도록 홈에서 확인해 주세요.
      </div>
      <template #append>
        <v-btn variant="text" @click="goHome">홈으로</v-btn>
      </template>
    </v-alert>

    <!-- ============================== 1단계 : 촬영 ============================== -->
    <template v-if="step === 1">
      <v-card variant="tonal" class="mb-4">
        <v-card-text>
          <div class="text-body-2">
            식당에서 받은 영수증을 촬영하면 상호명·금액·날짜를 자동으로 읽어 드립니다.
          </div>
          <div v-if="!appStore.ocrEnabled" class="text-body-2 mt-2 text-warning">
            지금은 자동 인식이 꺼져 있어 촬영 후 직접 입력해야 합니다.
          </div>
        </v-card-text>
      </v-card>

      <v-img
        v-if="previewUrl"
        :src="previewUrl"
        max-height="240"
        class="rounded mb-4"
        cover
      />

      <input
        ref="cameraInput"
        type="file"
        accept="image/*"
        capture="environment"
        class="d-none"
        @change="onFileChange"
      />
      <input
        ref="galleryInput"
        type="file"
        accept="image/*"
        class="d-none"
        @change="onFileChange"
      />

      <v-btn
        color="primary"
        size="large"
        block
        class="mb-3"
        :loading="uploading"
        :disabled="uploading"
        @click="pickCamera"
      >
        📷 영수증 촬영
      </v-btn>
      <v-btn
        variant="outlined"
        size="large"
        block
        class="mb-4"
        :disabled="uploading"
        @click="pickGallery"
      >
        갤러리에서 선택
      </v-btn>

      <div v-if="uploading">
        <v-progress-linear :model-value="uploadPct" height="10" rounded color="primary" />
        <div class="text-caption mt-2 text-center">
          업로드 {{ uploadPct }}% — 인식 중입니다. OCR 인식에 최대 1분 정도 걸릴 수 있습니다.
        </div>
      </div>
      <div v-else class="text-caption text-medium-emphasis text-center">
        OCR 인식에 최대 1분 정도 걸릴 수 있습니다.
      </div>
    </template>

    <!-- ========================= 2단계 : 인식 결과 확인 ========================= -->
    <template v-else-if="step === 2">
      <v-alert v-if="ocrFailed && !manualMode" type="warning" variant="tonal" class="mb-4">
        <div class="font-weight-medium">영수증을 자동으로 읽지 못했습니다.</div>
        <div class="text-body-2 mt-1">{{ receipt?.ocr_error || '인식 결과가 없습니다.' }}</div>
        <div class="text-body-2 mt-1">
          아래 항목을 직접 입력해도 그대로 기록됩니다.
        </div>
        <div class="d-flex ga-2 mt-3 flex-wrap">
          <v-btn size="small" variant="flat" color="warning" :loading="reocring" @click="retryOcr">
            다시 인식
          </v-btn>
          <v-btn size="small" variant="outlined" @click="manualMode = true">직접 입력하기</v-btn>
        </div>
      </v-alert>
      <v-alert v-else-if="ocrFailed" type="info" variant="tonal" class="mb-4">
        <div class="text-body-2">직접 입력 모드입니다. 영수증을 보고 아래 항목을 채워 주세요.</div>
        <div class="d-flex ga-2 mt-3">
          <v-btn size="small" variant="outlined" :loading="reocring" @click="retryOcr">
            다시 인식
          </v-btn>
        </div>
      </v-alert>

      <v-alert v-if="duplicate" type="warning" variant="tonal" prominent class="mb-4">
        <div class="font-weight-medium">중복일 수 있습니다</div>
        <div class="text-body-2 mt-1">{{ duplicate.message }}</div>
        <div class="text-caption mt-1">그래도 계속 진행할 수 있습니다.</div>
      </v-alert>

      <v-row class="mb-1">
        <v-col cols="12" sm="4">
          <v-card variant="outlined">
            <v-img
              :src="imageSrc"
              max-height="180"
              cover
              style="cursor: pointer"
              @click="imageDialog = true"
            />
            <v-card-text class="text-caption py-2 text-center">
              눌러서 크게 보기
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="12" sm="8">
          <v-text-field
            v-model="form.store_name"
            label="상호명"
            density="comfortable"
            :error="form.store_name.trim().length === 0"
            hint="필수 항목입니다."
            persistent-hint
          />
          <v-text-field
            v-model="form.business_number"
            label="사업자등록번호"
            density="comfortable"
            class="mt-3"
            hint="하이픈은 있어도 됩니다."
          />
          <v-text-field v-model="form.address" label="주소" density="comfortable" class="mt-3" />
          <v-text-field v-model="form.phone" label="전화" density="comfortable" class="mt-3" />
          <v-text-field
            v-model="form.total_amount"
            label="합계금액"
            type="number"
            inputmode="numeric"
            suffix="원"
            density="comfortable"
            class="mt-3"
            :error="totalAmount <= 0"
          />
          <div class="text-caption text-medium-emphasis mb-1 mt-3">결제일시</div>
          <input
            v-model="form.paid_at"
            type="datetime-local"
            class="pa-2 rounded"
            style="width: 100%; border: 1px solid rgba(128, 128, 128, 0.5)"
          />
        </v-col>
      </v-row>

      <div class="text-body-2 mb-3">
        인식된 값이 영수증과 다르면 고쳐 주세요. 고친 내용은 그대로 저장됩니다.
      </div>

      <v-btn color="primary" size="large" block :disabled="!step2Valid" @click="goStep3">
        다음 — 식당 확인
      </v-btn>
      <v-btn variant="text" size="large" block class="mt-2" @click="resetAll">
        다시 촬영하기
      </v-btn>
    </template>

    <!-- ============================ 3단계 : 식당 확인 ============================ -->
    <template v-else-if="step === 3">
      <v-alert v-if="duplicate" type="warning" variant="tonal" prominent class="mb-4">
        <div class="font-weight-medium">중복일 수 있습니다</div>
        <div class="text-body-2 mt-1">{{ duplicate.message }}</div>
      </v-alert>

      <!-- 3-a. 확정 매칭 확인 -->
      <v-card v-if="askMatched" variant="outlined" class="mb-4">
        <v-card-title class="text-subtitle-1">
          '{{ match?.restaurant?.name }}'이 맞나요?
        </v-card-title>
        <v-card-text>
          <div class="text-h6 mb-1">
            현재 잔액 {{ won(match?.restaurant?.balance) }}
          </div>
          <div class="text-body-2 text-medium-emphasis">
            {{ bizNumber(match?.restaurant?.business_number) }}
          </div>
          <div v-if="match?.restaurant?.address" class="text-body-2 text-medium-emphasis">
            {{ match?.restaurant?.address }}
          </div>
        </v-card-text>
        <v-card-actions class="flex-column align-stretch px-4 pb-4">
          <v-btn color="primary" size="large" block @click="acceptMatched">
            네, 이 식당이에요
          </v-btn>
          <v-btn variant="outlined" size="large" block class="mt-2 ml-0" @click="rejectMatched">
            아니에요, 다른 식당
          </v-btn>
        </v-card-actions>
      </v-card>

      <!-- 3-b. 후보 목록 -->
      <template v-if="showCandidates">
        <div class="text-subtitle-1 mb-2">비슷한 식당이 있어요. 어디인가요?</div>
        <v-card variant="outlined" class="mb-3">
          <v-list>
            <v-list-item
              v-for="c in candidates"
              :key="c.restaurant.id"
              :active="candidateId === c.restaurant.id"
              @click="chooseCandidate(c.restaurant.id)"
            >
              <v-list-item-title class="font-weight-medium">
                {{ c.restaurant.name }}
              </v-list-item-title>
              <v-list-item-subtitle>
                잔액 {{ won(c.restaurant.balance) }} ·
                {{ bizNumber(c.restaurant.business_number) }}
              </v-list-item-subtitle>
              <template #append>
                <v-chip size="small" variant="tonal">
                  유사도 {{ Math.round(c.score) }}
                </v-chip>
              </template>
            </v-list-item>
          </v-list>
        </v-card>
        <v-btn
          color="primary"
          size="large"
          block
          :disabled="!selected"
          class="mb-2"
          @click="confirmCandidate"
        >
          이 식당으로 계속
        </v-btn>
        <v-btn variant="outlined" size="large" block class="mb-4" @click="switchToNew">
          목록에 없어요 — 새 식당으로 등록
        </v-btn>
      </template>

      <!-- 3-c. 새 식당 등록 -->
      <template v-if="showNewForm">
        <v-card variant="tonal" class="mb-3">
          <v-card-text>
            <div class="font-weight-medium">새로 방문한 식당이네요. 등록할까요?</div>
            <div class="text-body-2 mt-1">
              영수증에서 읽은 정보를 채워 두었습니다. 필요하면 고쳐 주세요.
            </div>
          </v-card-text>
        </v-card>
        <v-text-field
          v-model="newRestaurant.name"
          label="식당명"
          density="comfortable"
          :error="newRestaurant.name.trim().length === 0"
          hint="필수 항목입니다."
          persistent-hint
        />
        <v-text-field
          v-model="newRestaurant.business_number"
          label="사업자등록번호"
          density="comfortable"
          class="mt-3"
          hint="다음 영수증 매칭에 사용됩니다. 모르면 비워두세요."
          persistent-hint
        />
        <v-text-field v-model="newRestaurant.address" label="주소" density="comfortable" class="mt-3" />
        <v-text-field v-model="newRestaurant.phone" label="전화" density="comfortable" class="mt-3" />
        <v-textarea
          v-model="newRestaurant.memo"
          label="메모 (선택)"
          rows="2"
          density="comfortable"
          class="mt-3"
        />
        <v-btn
          color="primary"
          size="large"
          block
          class="mt-2"
          :disabled="!step3Valid"
          @click="goStep4"
        >
          다음 — 처리 방식
        </v-btn>
        <v-btn
          v-if="candidates.length > 0"
          variant="text"
          size="large"
          block
          class="mt-2"
          @click="mode = 'existing'"
        >
          다시 후보 목록에서 고르기
        </v-btn>
      </template>

      <v-btn variant="text" size="large" block class="mt-2" @click="step = 2">
        이전 단계로
      </v-btn>
    </template>

    <!-- ============================ 4단계 : 처리 방식 ============================ -->
    <template v-else-if="step === 4">
      <v-card variant="tonal" class="mb-4">
        <v-card-text>
          <div class="font-weight-medium">
            {{ mode === 'new' ? newRestaurant.name : selected?.name }}
          </div>
          <div v-if="mode === 'existing'" class="text-body-2">
            현재 잔액 {{ won(selected?.balance) }}
          </div>
          <div v-else class="text-body-2">새로 등록되는 식당입니다.</div>
          <div class="text-body-2 mt-1">영수증 합계금액 {{ won(totalAmount) }}</div>
        </v-card-text>
      </v-card>

      <!-- 신규 등록: 선결제 충전만 -->
      <template v-if="mode === 'new'">
        <div class="text-subtitle-1 mb-1">선결제 충전으로 등록합니다</div>
        <div class="text-body-2 text-medium-emphasis mb-3">
          식당을 새로 만들고, 이번에 미리 결제한 금액을 잔액으로 올립니다.
        </div>
      </template>

      <!-- 기존 식당: 충전 / 사용 선택 -->
      <template v-else>
        <div class="text-subtitle-1 mb-2">이 영수증은 어떤 기록인가요?</div>
        <v-card
          :variant="action === 'charge' ? 'flat' : 'outlined'"
          :color="action === 'charge' ? 'success' : undefined"
          class="mb-2"
          @click="pickAction('charge')"
        >
          <v-card-text>
            <div class="font-weight-medium">선결제 충전</div>
            <div class="text-body-2">충전 = 이번에 미리 결제한 금액</div>
          </v-card-text>
        </v-card>
        <v-card
          :variant="action === 'use' ? 'flat' : 'outlined'"
          :color="action === 'use' ? 'error' : undefined"
          class="mb-4"
          @click="pickAction('use')"
        >
          <v-card-text>
            <div class="font-weight-medium">잔액에서 차감하기</div>
            <div class="text-body-2">사용 = 선결제 잔액에서 쓴 금액</div>
          </v-card-text>
        </v-card>
      </template>

      <!-- 금액 입력 -->
      <v-text-field
        v-if="action !== 'use'"
        v-model="chargeAmount"
        label="선결제 금액"
        type="number"
        inputmode="numeric"
        suffix="원"
        density="comfortable"
        :error="chargeInt <= 0"
      />
      <v-text-field
        v-else
        v-model="useAmount"
        label="사용 금액"
        type="number"
        inputmode="numeric"
        suffix="원"
        density="comfortable"
        :error="useInt <= 0"
      />

      <!-- 즉시 사용 -->
      <template v-if="action !== 'use'">
        <div class="text-subtitle-2 mt-4">이번 결제에서 바로 사용한 금액이 있나요?</div>
        <v-text-field
          v-model="useAmount"
          label="바로 사용한 금액"
          type="number"
          inputmode="numeric"
          suffix="원"
          density="comfortable"
          class="mt-2"
          hint="보통 선결제 후 일부를 바로 사용합니다. 없으면 0으로 두세요."
          persistent-hint
        />
      </template>

      <v-textarea v-model="memo" label="메모 (선택)" rows="2" density="comfortable" class="mt-4" />

      <v-card variant="tonal" class="mt-2 mb-4">
        <v-card-text class="py-3">
          <div class="text-body-2">기록 일시 {{ form.paid_at.replace('T', ' ') }}</div>
          <div v-if="mode === 'existing'" class="text-body-2 mt-1">
            처리 후 예상 잔액
            <span :class="expectedBalance < 0 ? 'text-error font-weight-bold' : 'font-weight-bold'">
              {{ won(expectedBalance) }}
            </span>
          </div>
        </v-card-text>
      </v-card>

      <v-btn
        color="primary"
        size="large"
        block
        :loading="submitting"
        :disabled="submitting || !step4Valid"
        @click="submit(false)"
      >
        기록 저장하기
      </v-btn>
      <v-btn variant="text" size="large" block class="mt-2" :disabled="submitting" @click="step = 3">
        이전 단계로
      </v-btn>
    </template>

    <!-- ============================== 5단계 : 완료 ============================== -->
    <template v-else-if="step === 5 && result">
      <v-card color="success" variant="tonal" class="mb-4">
        <v-card-text>
          <div class="text-h6">✅ 기록을 저장했습니다</div>
          <div class="text-subtitle-1 mt-1">{{ result.restaurant.name }}</div>
        </v-card-text>
      </v-card>

      <v-card variant="outlined" class="mb-4">
        <v-card-text>
          <div class="text-subtitle-2 mb-2">기록된 내용</div>
          <div
            v-for="t in result.transactions"
            :key="t.id"
            class="d-flex align-center justify-space-between py-1"
          >
            <v-chip size="small" :color="txColor(t.type)" variant="flat">
              {{ txLabel(t.type) }}
            </v-chip>
            <div class="font-weight-medium">{{ won(t.amount) }}</div>
          </div>
          <v-divider class="my-3" />
          <div class="d-flex align-center justify-space-between">
            <span class="text-body-2">이전 잔액</span>
            <span>{{ won(result.balance_before) }}</span>
          </div>
          <div class="d-flex align-center justify-space-between mt-1">
            <span class="text-body-2">새 잔액</span>
            <span
              class="text-h6"
              :class="result.balance_after < 0 ? 'text-error' : 'text-primary'"
            >
              {{ won(result.balance_after) }}
            </span>
          </div>
          <div class="text-caption text-medium-emphasis mt-2">
            {{ won(result.balance_before) }} → {{ won(result.balance_after) }}
          </div>
        </v-card-text>
      </v-card>

      <v-alert
        v-for="(w, i) in result.warnings"
        :key="i"
        type="warning"
        variant="tonal"
        class="mb-3"
      >
        {{ w }}
      </v-alert>

      <v-btn color="primary" size="large" block class="mb-2" @click="goDetail">
        식당 상세 보기
      </v-btn>
      <v-btn variant="outlined" size="large" block class="mb-2" @click="resetAll">
        영수증 하나 더 스캔
      </v-btn>
      <v-btn variant="text" size="large" block @click="goHome">홈으로</v-btn>
    </template>

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

    <!-- 영수증 크게 보기 -->
    <v-dialog v-model="imageDialog" max-width="640">
      <v-card>
        <v-img :src="imageSrc" max-height="80vh" contain />
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="imageDialog = false">닫기</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
