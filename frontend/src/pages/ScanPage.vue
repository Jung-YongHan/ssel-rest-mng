<script setup lang="ts">
/**
 * 영수증 스캔 — 5단계 플로우 (UC1/UC2/UC3).
 *
 * 촬영 → 인식 확인 → 식당 확인 → 처리 방식 → 완료.
 * 화면 규약은 docs/DESIGN.md: 이모지 대신 아이콘, 카드는 헤어라인,
 * 금액은 반드시 `won()` + `class="amount"`, 채운 버튼은 화면당 1개.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
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
const { smAndUp } = useDisplay()

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

/** 잔액 색 — 음수만 error, 임계값 미만은 warning, 정상은 기본 잉크색 (DESIGN §1) */
function balanceClass(r: RestaurantSummary | null | undefined): string {
  if (!r) return ''
  if (r.balance < 0) return 'text-error'
  if (r.is_low_balance) return 'text-warning'
  return ''
}

/** 거래 유형별 금액 색 — 칩(라벨)과 함께만 쓴다 (색만으로 의미 전달 금지) */
function txTextClass(t: string): string {
  return `text-${txColor(t)}`
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

/** 좁은 화면용 요약 표시 */
const currentStepLabel = computed(() => steps.find((s) => s.n === step.value)?.label ?? '')
const progressPct = computed(() => Math.round((step.value / steps.length) * 100))

/** 단계 원의 상태 (완료 / 현재 / 예정) */
function stepState(n: number): string {
  if (step.value > n) return 'step-item--done'
  if (step.value === n) return 'step-item--current'
  return 'step-item--future'
}

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
  <v-container class="flow-container pa-4">
    <h1 class="page-title mb-4">영수증 스캔</h1>

    <!-- ── 진행 단계 ─────────────────────────────────────────────── -->
    <ol v-if="smAndUp" class="step-nav mb-5" aria-label="진행 단계">
      <li
        v-for="s in steps"
        :key="s.n"
        class="step-item"
        :class="stepState(s.n)"
        :aria-current="step === s.n ? 'step' : undefined"
      >
        <div class="step-rail" aria-hidden="true">
          <span class="step-line step-line--start" />
          <span class="step-dot">
            <v-icon v-if="step > s.n" icon="mdi-check" size="14" />
            <template v-else>{{ s.n }}</template>
          </span>
          <span class="step-line step-line--end" />
        </div>
        <div class="step-label field-label">{{ s.label }}</div>
      </li>
    </ol>
    <div v-else class="mb-5">
      <div class="text-body-2 font-weight-medium mb-2">
        단계 {{ step }}/{{ steps.length }} · {{ currentStepLabel }}
      </div>
      <v-progress-linear :model-value="progressPct" height="4" color="primary" />
    </div>

    <v-skeleton-loader v-if="restoring" type="card" class="mb-4" />

    <!-- 이미 처리된 영수증 안내 -->
    <v-alert
      v-if="alreadyConsumed && step < 5"
      type="info"
      icon="mdi-information-outline"
      density="comfortable"
      class="mb-4"
    >
      <div class="font-weight-medium">이미 처리된 영수증입니다.</div>
      <div class="text-body-2 mt-1">
        이 영수증은 {{ dateTime(receipt?.consumed_at) }} 에 이미 기록되었습니다. 같은 영수증을 두 번
        기록하지 않도록 홈에서 확인해 주세요.
      </div>
      <template #append>
        <v-btn variant="text" @click="goHome">홈으로</v-btn>
      </template>
    </v-alert>

    <!-- ============================== 1단계 : 촬영 ============================== -->
    <template v-if="step === 1">
      <v-alert
        type="info"
        icon="mdi-information-outline"
        density="comfortable"
        :class="appStore.ocrEnabled ? 'mb-4' : 'mb-2'"
      >
        식당에서 받은 영수증을 촬영하면 상호명·금액·날짜를 자동으로 읽어 드립니다.
      </v-alert>

      <div v-if="!appStore.ocrEnabled" class="d-flex align-start hint-text text-warning mb-4">
        <v-icon icon="mdi-information-outline" size="16" class="me-1 flex-shrink-0 mt-1" />
        <span>지금은 자동 인식이 꺼져 있어 촬영 후 직접 입력해야 합니다.</span>
      </div>

      <v-sheet
        v-if="previewUrl"
        border
        rounded="lg"
        color="surface-variant"
        class="receipt-frame receipt-frame--tall mb-4"
      >
        <!-- VImg 기본값이 object-fit:contain — 영수증이 잘리지 않게 cover 를 쓰지 않는다 -->
        <v-img :src="previewUrl" height="100%" alt="촬영한 영수증" />
      </v-sheet>

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

      <div class="d-flex flex-column ga-3">
        <v-btn
          color="primary"
          size="large"
          block
          prepend-icon="mdi-camera-outline"
          :loading="uploading"
          :disabled="uploading"
          @click="pickCamera"
        >
          영수증 촬영
        </v-btn>
        <v-btn
          variant="outlined"
          size="large"
          block
          prepend-icon="mdi-image-outline"
          :disabled="uploading"
          @click="pickGallery"
        >
          갤러리에서 선택
        </v-btn>
      </div>

      <div v-if="uploading" class="mt-4">
        <v-progress-linear :model-value="uploadPct" color="primary" />
        <div class="hint-text mt-2 text-center">
          업로드 {{ uploadPct }}% — 인식 중입니다. OCR 인식에 최대 1분 정도 걸릴 수 있습니다.
        </div>
      </div>
      <div v-else class="hint-text mt-4 text-center">
        OCR 인식에 최대 1분 정도 걸릴 수 있습니다.
      </div>
    </template>

    <!-- ========================= 2단계 : 인식 결과 확인 ========================= -->
    <template v-else-if="step === 2">
      <v-alert
        v-if="ocrFailed && !manualMode"
        type="warning"
        icon="mdi-alert-outline"
        density="comfortable"
        class="mb-4"
      >
        <div class="font-weight-medium">영수증을 자동으로 읽지 못했습니다.</div>
        <div class="text-body-2 mt-1">{{ receipt?.ocr_error || '인식 결과가 없습니다.' }}</div>
        <div class="text-body-2 mt-1">아래 항목을 직접 입력해도 그대로 기록됩니다.</div>
        <div class="d-flex ga-2 mt-3 flex-wrap">
          <v-btn
            size="small"
            variant="tonal"
            color="warning"
            prepend-icon="mdi-refresh"
            :loading="reocring"
            @click="retryOcr"
          >
            다시 인식
          </v-btn>
          <v-btn size="small" variant="outlined" prepend-icon="mdi-pencil-outline" @click="manualMode = true">
            직접 입력하기
          </v-btn>
        </div>
      </v-alert>
      <v-alert
        v-else-if="ocrFailed"
        type="info"
        icon="mdi-pencil-outline"
        density="comfortable"
        class="mb-4"
      >
        <div class="text-body-2">직접 입력 모드입니다. 영수증을 보고 아래 항목을 채워 주세요.</div>
        <div class="d-flex ga-2 mt-3">
          <v-btn
            size="small"
            variant="outlined"
            prepend-icon="mdi-refresh"
            :loading="reocring"
            @click="retryOcr"
          >
            다시 인식
          </v-btn>
        </div>
      </v-alert>

      <v-alert
        v-if="duplicate"
        type="warning"
        icon="mdi-alert-outline"
        density="comfortable"
        class="mb-4"
      >
        <div class="font-weight-medium">중복일 수 있습니다</div>
        <div class="text-body-2 mt-1">{{ duplicate.message }}</div>
        <div class="hint-text mt-1">그래도 계속 진행할 수 있습니다.</div>
      </v-alert>

      <v-row>
        <v-col cols="12" sm="4">
          <v-sheet
            border
            rounded="lg"
            color="surface-variant"
            class="receipt-frame pressable"
            role="button"
            tabindex="0"
            aria-label="영수증 크게 보기"
            @click="imageDialog = true"
            @keydown.enter="imageDialog = true"
            @keydown.space.prevent="imageDialog = true"
          >
            <v-img :src="imageSrc" height="100%" alt="영수증 이미지" />
          </v-sheet>
          <div class="hint-text text-center mt-2">눌러서 크게 보기</div>
        </v-col>

        <v-col cols="12" sm="8">
          <div class="d-flex flex-column ga-4">
            <v-text-field
              v-model="form.store_name"
              label="상호명"
              prepend-inner-icon="mdi-storefront-outline"
              :error="form.store_name.trim().length === 0"
              hint="필수 항목입니다."
              persistent-hint
            />
            <v-text-field
              v-model="form.business_number"
              label="사업자등록번호"
              prepend-inner-icon="mdi-card-account-details-outline"
              hint="하이픈은 있어도 됩니다."
            />
            <v-text-field
              v-model="form.address"
              label="주소"
              prepend-inner-icon="mdi-map-marker-outline"
            />
            <v-text-field
              v-model="form.phone"
              label="전화"
              prepend-inner-icon="mdi-phone-outline"
            />
            <v-text-field
              v-model="form.total_amount"
              label="합계금액"
              type="number"
              inputmode="numeric"
              suffix="원"
              density="default"
              class="amount-field"
              prepend-inner-icon="mdi-cash"
              :error="totalAmount <= 0"
            />
            <!-- naive 문자열(YYYY-MM-DDTHH:mm)을 그대로 보낸다 — 서버가 KST 로 해석 -->
            <v-text-field
              v-model="form.paid_at"
              label="결제일시"
              type="datetime-local"
              prepend-inner-icon="mdi-calendar-clock"
              persistent-placeholder
            />
          </div>
        </v-col>
      </v-row>

      <div class="hint-text mt-4 mb-4">
        인식된 값이 영수증과 다르면 고쳐 주세요. 고친 내용은 그대로 저장됩니다.
      </div>

      <v-btn
        color="primary"
        size="large"
        block
        append-icon="mdi-arrow-right"
        :disabled="!step2Valid"
        @click="goStep3"
      >
        다음 — 식당 확인
      </v-btn>
      <v-btn
        variant="text"
        size="large"
        block
        class="mt-2"
        prepend-icon="mdi-camera-outline"
        @click="resetAll"
      >
        다시 촬영하기
      </v-btn>
    </template>

    <!-- ============================ 3단계 : 식당 확인 ============================ -->
    <template v-else-if="step === 3">
      <v-alert
        v-if="duplicate"
        type="warning"
        icon="mdi-alert-outline"
        density="comfortable"
        class="mb-4"
      >
        <div class="font-weight-medium">중복일 수 있습니다</div>
        <div class="text-body-2 mt-1">{{ duplicate.message }}</div>
      </v-alert>

      <!-- 3-a. 확정 매칭 확인 -->
      <v-card v-if="askMatched" class="mb-4">
        <div class="px-4 py-3">
          <div class="section-title">'{{ match?.restaurant?.name }}'이 맞나요?</div>
        </div>
        <v-divider />
        <div class="pa-4">
          <div class="d-flex align-center">
            <v-icon icon="mdi-storefront-outline" size="18" class="me-2 text-medium-emphasis" />
            <span class="text-body-2 font-weight-medium text-truncate">
              {{ match?.restaurant?.name }}
            </span>
          </div>
          <div class="d-flex align-center mt-2">
            <v-icon
              icon="mdi-card-account-details-outline"
              size="18"
              class="me-2 text-medium-emphasis"
            />
            <span class="text-body-2 text-medium-emphasis">
              {{ bizNumber(match?.restaurant?.business_number) }}
            </span>
          </div>
          <div v-if="match?.restaurant?.address" class="d-flex align-center mt-2">
            <v-icon icon="mdi-map-marker-outline" size="18" class="me-2 text-medium-emphasis" />
            <span class="text-body-2 text-medium-emphasis text-truncate">
              {{ match?.restaurant?.address }}
            </span>
          </div>
        </div>
        <v-divider />
        <div class="px-4 py-3 d-flex align-center justify-space-between">
          <span class="field-label">현재 잔액</span>
          <span class="metric-value amount" :class="balanceClass(match?.restaurant)">
            {{ won(match?.restaurant?.balance) }}
          </span>
        </div>
        <v-divider />
        <div class="pa-4">
          <v-btn color="primary" size="large" block @click="acceptMatched">
            네, 이 식당이에요
          </v-btn>
          <v-btn variant="outlined" size="large" block class="mt-2" @click="rejectMatched">
            아니에요, 다른 식당
          </v-btn>
        </div>
      </v-card>

      <!-- 3-b. 후보 목록 -->
      <template v-if="showCandidates">
        <div class="section-title mb-2">비슷한 식당이 있어요. 어디인가요?</div>
        <v-card class="mb-4">
          <div class="divided">
            <div
              v-for="c in candidates"
              :key="c.restaurant.id"
              class="pressable pick-row px-4 py-3 d-flex align-center"
              :class="{ 'pick-row--on': candidateId === c.restaurant.id }"
              role="button"
              tabindex="0"
              :aria-pressed="candidateId === c.restaurant.id"
              @click="chooseCandidate(c.restaurant.id)"
              @keydown.enter="chooseCandidate(c.restaurant.id)"
              @keydown.space.prevent="chooseCandidate(c.restaurant.id)"
            >
              <v-icon
                :icon="
                  candidateId === c.restaurant.id ? 'mdi-check-circle-outline' : 'mdi-circle-outline'
                "
                :color="candidateId === c.restaurant.id ? 'primary' : undefined"
                :class="candidateId === c.restaurant.id ? 'me-3' : 'me-3 text-disabled'"
                size="20"
              />
              <div class="flex-grow-1 min-w-0 me-3">
                <div class="d-flex align-center">
                  <span class="text-body-2 font-weight-medium text-truncate">
                    {{ c.restaurant.name }}
                  </span>
                  <v-chip class="ms-2 flex-shrink-0">유사도 {{ Math.round(c.score) }}</v-chip>
                </div>
                <div class="hint-text text-truncate mt-1">
                  {{ bizNumber(c.restaurant.business_number) }}
                </div>
              </div>
              <div class="text-right flex-shrink-0">
                <div class="field-label">잔액</div>
                <div class="amount" :class="balanceClass(c.restaurant)">
                  {{ won(c.restaurant.balance) }}
                </div>
              </div>
            </div>
          </div>
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
        <v-btn
          variant="outlined"
          size="large"
          block
          class="mb-4"
          prepend-icon="mdi-store-plus-outline"
          @click="switchToNew"
        >
          목록에 없어요 — 새 식당으로 등록
        </v-btn>
      </template>

      <!-- 3-c. 새 식당 등록 -->
      <template v-if="showNewForm">
        <v-alert
          type="info"
          icon="mdi-information-outline"
          density="comfortable"
          class="mb-4"
        >
          <div class="font-weight-medium">새로 방문한 식당이네요. 등록할까요?</div>
          <div class="text-body-2 mt-1">
            영수증에서 읽은 정보를 채워 두었습니다. 필요하면 고쳐 주세요.
          </div>
        </v-alert>

        <v-card class="pa-4 mb-4">
          <div class="d-flex flex-column ga-4">
            <v-text-field
              v-model="newRestaurant.name"
              label="식당명"
              prepend-inner-icon="mdi-storefront-outline"
              :error="newRestaurant.name.trim().length === 0"
              hint="필수 항목입니다."
              persistent-hint
            />
            <v-text-field
              v-model="newRestaurant.business_number"
              label="사업자등록번호"
              prepend-inner-icon="mdi-card-account-details-outline"
              hint="다음 영수증 매칭에 사용됩니다. 모르면 비워두세요."
              persistent-hint
            />
            <v-text-field
              v-model="newRestaurant.address"
              label="주소"
              prepend-inner-icon="mdi-map-marker-outline"
            />
            <v-text-field
              v-model="newRestaurant.phone"
              label="전화"
              prepend-inner-icon="mdi-phone-outline"
            />
            <v-textarea
              v-model="newRestaurant.memo"
              label="메모 (선택)"
              rows="2"
              prepend-inner-icon="mdi-note-text-outline"
            />
          </div>
        </v-card>

        <v-btn
          color="primary"
          size="large"
          block
          append-icon="mdi-arrow-right"
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

      <v-btn variant="text" size="large" block class="mt-2" prepend-icon="mdi-arrow-left" @click="step = 2">
        이전 단계로
      </v-btn>
    </template>

    <!-- ============================ 4단계 : 처리 방식 ============================ -->
    <template v-else-if="step === 4">
      <v-card class="mb-4">
        <div class="px-4 py-3">
          <div class="d-flex align-center">
            <v-icon icon="mdi-storefront-outline" size="18" class="me-2 text-medium-emphasis" />
            <span class="text-body-2 font-weight-medium text-truncate">
              {{ mode === 'new' ? newRestaurant.name : selected?.name }}
            </span>
          </div>
          <div v-if="mode === 'new'" class="hint-text mt-1">새로 등록되는 식당입니다.</div>
        </div>
        <v-divider />
        <div class="metric-row">
          <div v-if="mode === 'existing'" class="metric-cell">
            <div class="field-label">현재 잔액</div>
            <div class="metric-value amount" :class="balanceClass(selected)">
              {{ won(selected?.balance) }}
            </div>
          </div>
          <div class="metric-cell">
            <div class="field-label">영수증 합계금액</div>
            <div class="metric-value amount">{{ won(totalAmount) }}</div>
          </div>
        </div>
      </v-card>

      <!-- 신규 등록: 선결제 충전만 -->
      <template v-if="mode === 'new'">
        <v-card class="pa-4 mb-4">
          <div class="d-flex align-start">
            <v-icon
              icon="mdi-arrow-down-circle-outline"
              color="success"
              size="22"
              class="me-3 flex-shrink-0"
            />
            <div class="min-w-0">
              <div class="section-title">선결제 충전으로 등록합니다</div>
              <div class="hint-text mt-1">
                식당을 새로 만들고, 이번에 미리 결제한 금액을 잔액으로 올립니다.
              </div>
            </div>
          </div>
        </v-card>
      </template>

      <!-- 기존 식당: 충전 / 사용 선택 -->
      <template v-else>
        <div class="section-title mb-2">이 영수증은 어떤 기록인가요?</div>
        <v-row dense class="mb-2">
          <v-col cols="12" sm="6">
            <v-card
              class="choice-card pa-4 h-100"
              :class="action === 'charge' ? 'choice-card--on' : ''"
              role="button"
              tabindex="0"
              :aria-pressed="action === 'charge'"
              @click="pickAction('charge')"
              @keydown.enter="pickAction('charge')"
              @keydown.space.prevent="pickAction('charge')"
            >
              <div class="d-flex align-start">
                <v-icon
                  icon="mdi-arrow-down-circle-outline"
                  color="success"
                  size="22"
                  class="me-3 flex-shrink-0"
                />
                <div class="min-w-0">
                  <div class="text-body-2 font-weight-medium">선결제 충전</div>
                  <div class="hint-text mt-1">충전 = 이번에 미리 결제한 금액</div>
                </div>
                <v-spacer />
                <v-icon
                  v-if="action === 'charge'"
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
              :class="action === 'use' ? 'choice-card--on' : ''"
              role="button"
              tabindex="0"
              :aria-pressed="action === 'use'"
              @click="pickAction('use')"
              @keydown.enter="pickAction('use')"
              @keydown.space.prevent="pickAction('use')"
            >
              <div class="d-flex align-start">
                <v-icon
                  icon="mdi-arrow-up-circle-outline"
                  color="error"
                  size="22"
                  class="me-3 flex-shrink-0"
                />
                <div class="min-w-0">
                  <div class="text-body-2 font-weight-medium">잔액에서 차감하기</div>
                  <div class="hint-text mt-1">사용 = 선결제 잔액에서 쓴 금액</div>
                </div>
                <v-spacer />
                <v-icon
                  v-if="action === 'use'"
                  icon="mdi-check-circle-outline"
                  color="primary"
                  size="20"
                  class="ms-2 flex-shrink-0"
                />
              </div>
            </v-card>
          </v-col>
        </v-row>
      </template>

      <!-- 금액 입력 -->
      <v-text-field
        v-if="action !== 'use'"
        v-model="chargeAmount"
        label="선결제 금액"
        type="number"
        inputmode="numeric"
        suffix="원"
        density="default"
        class="amount-field mt-2"
        prepend-inner-icon="mdi-cash"
        :error="chargeInt <= 0"
      />
      <v-text-field
        v-else
        v-model="useAmount"
        label="사용 금액"
        type="number"
        inputmode="numeric"
        suffix="원"
        density="default"
        class="amount-field mt-2"
        prepend-inner-icon="mdi-cash"
        :error="useInt <= 0"
      />

      <!-- 즉시 사용 -->
      <template v-if="action !== 'use'">
        <div class="section-title mt-5">이번 결제에서 바로 사용한 금액이 있나요?</div>
        <div class="hint-text mt-1 mb-2">
          보통 선결제 후 일부를 바로 사용합니다. 없으면 0으로 두세요.
        </div>
        <v-text-field
          v-model="useAmount"
          label="바로 사용한 금액"
          type="number"
          inputmode="numeric"
          suffix="원"
          prepend-inner-icon="mdi-arrow-up-circle-outline"
        />
      </template>

      <v-textarea
        v-model="memo"
        label="메모 (선택)"
        rows="2"
        class="mt-4"
        prepend-inner-icon="mdi-note-text-outline"
      />

      <v-card class="mt-4 mb-4">
        <div class="divided">
          <div class="px-4 py-3 d-flex align-center justify-space-between ga-3">
            <span class="field-label">기록 일시</span>
            <span class="text-body-2 amount">{{ form.paid_at.replace('T', ' ') }}</span>
          </div>
          <div
            v-if="mode === 'existing'"
            class="px-4 py-3 d-flex align-center justify-space-between ga-3"
          >
            <span class="field-label">처리 후 예상 잔액</span>
            <span class="metric-value amount" :class="expectedBalance < 0 ? 'text-error' : ''">
              {{ won(expectedBalance) }}
            </span>
          </div>
        </div>
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
      <v-btn
        variant="text"
        size="large"
        block
        class="mt-2"
        prepend-icon="mdi-arrow-left"
        :disabled="submitting"
        @click="step = 3"
      >
        이전 단계로
      </v-btn>
    </template>

    <!-- ============================== 5단계 : 완료 ============================== -->
    <template v-else-if="step === 5 && result">
      <v-card class="mb-4">
        <div class="pa-4 d-flex align-start">
          <v-icon
            icon="mdi-check-circle-outline"
            color="success"
            size="28"
            class="me-3 flex-shrink-0"
          />
          <div class="min-w-0">
            <div class="section-title">기록을 저장했습니다</div>
            <div class="text-body-2 mt-1 text-truncate">{{ result.restaurant.name }}</div>
          </div>
        </div>
        <v-divider />
        <div class="px-4 pt-3">
          <div class="field-label">기록된 내용</div>
        </div>
        <div class="divided mt-1">
          <div
            v-for="t in result.transactions"
            :key="t.id"
            class="px-4 py-3 d-flex align-center justify-space-between ga-3"
          >
            <v-chip :color="txColor(t.type)">{{ txLabel(t.type) }}</v-chip>
            <span class="amount" :class="txTextClass(t.type)">{{ won(t.amount) }}</span>
          </div>
        </div>
        <v-divider />
        <div class="px-4 py-3">
          <div class="field-label">이전 잔액 → 새 잔액</div>
          <div class="d-flex align-center mt-1">
            <span class="amount text-medium-emphasis">{{ won(result.balance_before) }}</span>
            <v-icon
              icon="mdi-arrow-right"
              size="16"
              class="mx-2 text-medium-emphasis flex-shrink-0"
            />
            <span
              class="metric-value amount"
              :class="result.balance_after < 0 ? 'text-error' : ''"
            >
              {{ won(result.balance_after) }}
            </span>
          </div>
        </div>
      </v-card>

      <v-alert
        v-for="(w, i) in result.warnings"
        :key="i"
        type="warning"
        icon="mdi-alert-outline"
        density="comfortable"
        class="mb-3"
      >
        {{ w }}
      </v-alert>

      <v-btn
        color="primary"
        size="large"
        block
        class="mb-2"
        append-icon="mdi-arrow-right"
        @click="goDetail"
      >
        식당 상세 보기
      </v-btn>
      <v-btn
        color="primary"
        variant="tonal"
        size="large"
        block
        class="mb-2"
        prepend-icon="mdi-camera-outline"
        @click="resetAll"
      >
        영수증 하나 더 스캔
      </v-btn>
      <v-btn variant="text" size="large" block @click="goHome">홈으로</v-btn>
    </template>

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

    <!-- 영수증 크게 보기 -->
    <v-dialog v-model="imageDialog" max-width="640">
      <v-card>
        <v-img :src="imageSrc" max-height="80vh" alt="영수증 이미지" />
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="imageDialog = false">닫기</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
/* ── 진행 단계 표시 ────────────────────────────────────────────────
   완료=체크(브랜드 채움) / 현재=번호(브랜드 채움) / 예정=헤어라인 원.
   색은 테마 토큰만 사용한다. */
.step-nav {
  display: flex;
  list-style: none;
  margin: 0;
  padding: 0;
}

.step-item {
  flex: 1 1 0;
  min-width: 0;
}

.step-rail {
  display: flex;
  align-items: center;
}

.step-line {
  flex: 1 1 auto;
  height: 1px;
  background-color: rgba(var(--v-border-color), var(--v-border-opacity));
}

.step-item:first-child .step-line--start,
.step-item:last-child .step-line--end {
  visibility: hidden;
}

.step-item--done .step-line,
.step-item--current .step-line--start {
  background-color: rgba(var(--v-theme-primary), 0.4);
}

.step-dot {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  background-color: rgb(var(--v-theme-surface));
  color: rgb(var(--v-theme-on-surface-variant));
  font-size: 0.75rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.step-item--done .step-dot,
.step-item--current .step-dot {
  border-color: rgb(var(--v-theme-primary));
  background-color: rgb(var(--v-theme-primary));
  color: rgb(var(--v-theme-on-primary, 255, 255, 255));
}

.step-item--future .step-dot {
  opacity: 0.55;
}

.step-label {
  margin-top: var(--sp-2);
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-item--current .step-label {
  color: rgb(var(--v-theme-on-surface));
  font-weight: 700;
}

.step-item--future .step-label {
  opacity: 0.6;
}

/* ── 영수증 이미지 틀 ─────────────────────────────────────────────*/
.receipt-frame {
  height: 176px;
  overflow: hidden;
}

.receipt-frame--tall {
  height: 240px;
}

/* ── 선택 카드 / 선택 행 ─────────────────────────────────────────
   선택 상태 = 브랜드 테두리 + 톤 배경. `:hover` 보다 우선하도록 함께 선언한다.
   비선택 테두리는 헤어라인 토큰으로 고정해 선택 상태가 확실히 도드라지게 한다
   (Vuetify 의 outlined 는 border-color 가 currentColor 라서 잉크색으로 나온다). */
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

.pick-row--on,
.pick-row--on:hover {
  background-color: rgba(var(--v-theme-primary), 0.08);
}

/* ── 보조 ────────────────────────────────────────────────────────*/
/* flex 안에서 text-truncate 가 동작하려면 min-width 를 풀어줘야 한다 */
.min-w-0 {
  min-width: 0;
}

/* 합계/충전 금액은 이 화면의 대표 숫자 — 입력칸에서도 크게 보인다 */
.amount-field :deep(input) {
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
</style>
