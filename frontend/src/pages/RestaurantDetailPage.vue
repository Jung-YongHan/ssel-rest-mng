<script setup lang="ts">
/**
 * 식당 상세 — 잔액 · 누적 지표 · 거래 타임라인 (CONTRACT §2.2 / §2.4).
 *
 * 디자인 규약은 docs/DESIGN.md. 이 화면의 채운 버튼은 다이얼로그 확인 버튼뿐이고,
 * 페이지의 충전/차감은 톤(tonal)으로만 강조한다.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  receiptApi,
  restaurantApi,
  transactionApi,
  errorMessage,
  isInsufficientBalance,
} from '@/api/endpoints'
import type { RestaurantDetail, TransactionOut } from '@/api/types'
import { bizNumber, dateTime, nowLocalInput, relativeDate, txColor, txLabel, won } from '@/utils/format'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

const PAGE_SIZE = 20

function toInt(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

const restaurantId = computed(() => {
  const raw = route.params.id
  return Number(Array.isArray(raw) ? raw[0] : raw)
})

/* ------------------------------------------------------------------ */
/* 상태                                                                */
/* ------------------------------------------------------------------ */

const detail = ref<RestaurantDetail | null>(null)
const loading = ref(true)

const txItems = ref<TransactionOut[]>([])
const txTotal = ref(0)
const txLoading = ref(false)

/* 충전 / 차감 */
const txDialog = ref(false)
const txType = ref<'CHARGE' | 'USE'>('CHARGE')
const txAmount = ref<number | string>('')
const txOccurredAt = ref(nowLocalInput())
const txMemo = ref('')
const txSaving = ref(false)
const negDialog = ref(false)
const negMessage = ref('')

/* 기록 취소 */
const voidDialog = ref(false)
const voidTarget = ref<TransactionOut | null>(null)
const voidReason = ref('')
const voiding = ref(false)

/* 정보 수정 */
const editDialog = ref(false)
const editForm = ref({ name: '', business_number: '', address: '', phone: '', memo: '' })
const editSaving = ref(false)

/* 보관 */
const archiveDialog = ref(false)
const archiveSaving = ref(false)

/* 영수증 이미지 */
const imageDialog = ref(false)
const imageUrl = ref('')

/* ------------------------------------------------------------------ */
/* 파생 값                                                             */
/* ------------------------------------------------------------------ */

const balance = computed(() => detail.value?.balance ?? 0)
/** 금액 색은 부호가 있을 때만 (DESIGN §1). 정상 잔액은 기본 잉크색. */
const balanceColor = computed(() => {
  if (balance.value < 0) return 'text-error'
  if (detail.value?.is_low_balance) return 'text-warning'
  return ''
})
const hasMore = computed(() => txItems.value.length < txTotal.value)
const txAmountInt = computed(() => toInt(txAmount.value))
const expectedBalance = computed(() =>
  txType.value === 'CHARGE' ? balance.value + txAmountInt.value : balance.value - txAmountInt.value,
)
const canSaveTx = computed(() => txAmountInt.value > 0 && !txSaving.value)
const canVoid = computed(() => voidReason.value.trim().length > 0 && !voiding.value)

/** 값이 있는 항목만 아이콘 + 텍스트 한 줄로 (DESIGN §3 매핑) */
const metaRows = computed<{ icon: string; text: string }[]>(() => {
  const d = detail.value
  if (!d) return []
  const rows: { icon: string; text: string }[] = []
  if (d.business_number) {
    rows.push({ icon: 'mdi-card-account-details-outline', text: bizNumber(d.business_number) })
  }
  if (d.address) rows.push({ icon: 'mdi-map-marker-outline', text: d.address })
  if (d.phone) rows.push({ icon: 'mdi-phone-outline', text: d.phone })
  if (d.memo) rows.push({ icon: 'mdi-note-text-outline', text: d.memo })
  return rows
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
/* 로드                                                                */
/* ------------------------------------------------------------------ */

async function loadDetail() {
  loading.value = true
  try {
    detail.value = await restaurantApi.get(restaurantId.value)
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    loading.value = false
  }
}

async function loadTx(reset = false) {
  if (txLoading.value) return
  if (reset) {
    txItems.value = []
    txTotal.value = 0
  }
  txLoading.value = true
  try {
    const res = await restaurantApi.transactions(restaurantId.value, {
      limit: PAGE_SIZE,
      offset: txItems.value.length,
      include_voided: true,
    })
    txItems.value = txItems.value.concat(res.items)
    txTotal.value = res.total
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    txLoading.value = false
  }
}

async function refreshAll() {
  await loadDetail()
  await loadTx(true)
}

onMounted(refreshAll)
watch(restaurantId, (v) => {
  if (Number.isFinite(v) && v > 0) refreshAll()
})

/* ------------------------------------------------------------------ */
/* 충전 / 차감                                                          */
/* ------------------------------------------------------------------ */

function openTx(type: 'CHARGE' | 'USE') {
  txType.value = type
  txAmount.value = ''
  txOccurredAt.value = nowLocalInput()
  txMemo.value = ''
  txDialog.value = true
}

async function saveTx(allowNegative = false) {
  if (txAmountInt.value <= 0) {
    appStore.toast('금액을 입력해 주세요.', 'warning')
    return
  }
  if (txSaving.value) return
  txSaving.value = true
  try {
    const res = await transactionApi.create({
      restaurant_id: restaurantId.value,
      type: txType.value,
      amount: txAmountInt.value,
      occurred_at: txOccurredAt.value || null,
      memo: txMemo.value.trim() || null,
      allow_negative: allowNegative,
    })
    for (const w of res.warnings) appStore.toast(w, 'warning')
    appStore.toast(
      txType.value === 'CHARGE' ? '선결제 충전을 기록했습니다.' : '사용 기록을 저장했습니다.',
      'success',
    )
    txDialog.value = false
    await refreshAll()
  } catch (e) {
    if (isInsufficientBalance(e)) {
      negMessage.value = errorMessage(e)
      negDialog.value = true
    } else {
      appStore.toast(errorMessage(e), 'error')
    }
  } finally {
    txSaving.value = false
  }
}

function proceedNegative() {
  negDialog.value = false
  saveTx(true)
}

/* ------------------------------------------------------------------ */
/* 기록 취소                                                            */
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
    await refreshAll()
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    voiding.value = false
  }
}

/* ------------------------------------------------------------------ */
/* 정보 수정 / 보관                                                     */
/* ------------------------------------------------------------------ */

function openEdit() {
  if (!detail.value) return
  editForm.value = {
    name: detail.value.name,
    business_number: detail.value.business_number ?? '',
    address: detail.value.address ?? '',
    phone: detail.value.phone ?? '',
    memo: detail.value.memo ?? '',
  }
  editDialog.value = true
}

async function saveEdit() {
  if (editForm.value.name.trim().length === 0) {
    appStore.toast('식당명을 입력해 주세요.', 'warning')
    return
  }
  if (editSaving.value) return
  editSaving.value = true
  try {
    detail.value = await restaurantApi.update(restaurantId.value, {
      name: editForm.value.name.trim(),
      business_number: editForm.value.business_number.trim() || null,
      address: editForm.value.address.trim() || null,
      phone: editForm.value.phone.trim() || null,
      memo: editForm.value.memo.trim() || null,
    })
    appStore.toast('식당 정보를 수정했습니다.', 'success')
    editDialog.value = false
    await loadTx(true)
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    editSaving.value = false
  }
}

async function toggleArchive() {
  if (!detail.value || archiveSaving.value) return
  const next = !detail.value.is_archived
  archiveSaving.value = true
  try {
    detail.value = await restaurantApi.update(restaurantId.value, { is_archived: next })
    appStore.toast(next ? '식당을 보관했습니다.' : '보관을 해제했습니다.', 'success')
    archiveDialog.value = false
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    archiveSaving.value = false
  }
}

/* ------------------------------------------------------------------ */
/* 기타                                                                */
/* ------------------------------------------------------------------ */

function openReceipt(receiptId: number | null) {
  if (!receiptId) return
  imageUrl.value = receiptApi.imageUrl(receiptId)
  imageDialog.value = true
}

function goScan() {
  router.push('/scan')
}
</script>

<template>
  <v-container class="flow-container pa-4">
    <v-skeleton-loader
      v-if="loading && !detail"
      type="card, list-item-two-line, list-item-two-line"
    />

    <template v-else-if="detail">
      <!-- ── 헤더: 식당명 · 메타 · 잔액 ─────────────────────────── -->
      <v-card class="mb-4">
        <div class="pa-4">
          <div class="d-flex align-start ga-2">
            <h1 class="page-title flex-grow-1">{{ detail.name }}</h1>
            <v-chip
              v-if="detail.is_archived"
              color="secondary"
              size="small"
              prepend-icon="mdi-archive-arrow-down-outline"
              class="flex-shrink-0"
            >
              보관됨
            </v-chip>
          </div>

          <div v-if="metaRows.length" class="mt-3">
            <div
              v-for="row in metaRows"
              :key="row.icon"
              class="d-flex align-start hint-text mt-1"
            >
              <v-icon :icon="row.icon" size="16" class="me-2 mt-1 flex-shrink-0" />
              <span>{{ row.text }}</span>
            </div>
          </div>
        </div>

        <v-divider />

        <div class="pa-4">
          <div class="field-label">현재 잔액</div>
          <div class="d-flex align-center flex-wrap ga-3 mt-1">
            <div class="money-hero amount" :class="balanceColor">{{ won(balance) }}</div>
            <v-chip
              v-if="detail.is_low_balance"
              color="warning"
              size="small"
              prepend-icon="mdi-alert-outline"
            >
              잔액 부족
            </v-chip>
          </div>
          <div class="hint-text mt-2">
            마지막 사용 {{ detail.last_used_at ? relativeDate(detail.last_used_at) : '없음' }} ·
            마지막 충전 {{ detail.last_charged_at ? relativeDate(detail.last_charged_at) : '없음' }}
          </div>
        </div>
      </v-card>

      <!-- ── 누적 지표 ─────────────────────────────────────────── -->
      <v-card class="mb-4">
        <div class="metric-row">
          <div class="metric-cell">
            <div class="field-label">누적 충전</div>
            <div class="metric-value amount text-success">{{ won(detail.charge_total) }}</div>
          </div>
          <div class="metric-cell">
            <div class="field-label">누적 사용</div>
            <div class="metric-value amount text-error">{{ won(detail.use_total) }}</div>
          </div>
          <div class="metric-cell">
            <div class="field-label">거래 수</div>
            <div class="metric-value amount">{{ detail.tx_count }}건</div>
          </div>
        </div>
      </v-card>

      <!-- ── 동작 ──────────────────────────────────────────────── -->
      <!-- 좁은 화면에서는 세로로 쌓고, sm 이상에서 3등분한다 (긴 라벨이 잘리지 않게) -->
      <v-row dense class="mb-1">
        <v-col cols="12" sm="4">
          <v-btn
            variant="tonal"
            color="success"
            size="large"
            block
            prepend-icon="mdi-arrow-down-circle-outline"
            @click="openTx('CHARGE')"
          >
            선결제 충전
          </v-btn>
        </v-col>
        <v-col cols="12" sm="4">
          <v-btn
            variant="tonal"
            color="error"
            size="large"
            block
            prepend-icon="mdi-arrow-up-circle-outline"
            @click="openTx('USE')"
          >
            잔액에서 차감
          </v-btn>
        </v-col>
        <v-col cols="12" sm="4">
          <v-btn
            variant="outlined"
            size="large"
            block
            prepend-icon="mdi-camera-outline"
            @click="goScan"
          >
            영수증으로 기록
          </v-btn>
        </v-col>
      </v-row>

      <div class="d-flex flex-wrap ga-2">
        <v-btn variant="text" prepend-icon="mdi-pencil-outline" @click="openEdit">정보 수정</v-btn>
        <v-btn
          variant="text"
          prepend-icon="mdi-archive-arrow-down-outline"
          @click="archiveDialog = true"
        >
          {{ detail.is_archived ? '보관 해제' : '보관하기' }}
        </v-btn>
      </div>

      <!-- ── 거래 타임라인 ─────────────────────────────────────── -->
      <div class="d-flex align-center justify-space-between mt-6 mb-2">
        <h2 class="section-title">거래 내역</h2>
        <span class="hint-text">전체 {{ txTotal }}건</span>
      </div>

      <v-skeleton-loader
        v-if="txLoading && txItems.length === 0"
        type="list-item-two-line, list-item-two-line, list-item-two-line"
      />

      <v-card v-else-if="txItems.length === 0" class="pa-8 text-center">
        <v-icon icon="mdi-receipt-text-outline" size="40" class="mb-3" style="opacity: 0.35" />
        <div class="text-body-2 text-medium-emphasis mb-4">아직 거래 내역이 없습니다.</div>
        <v-btn
          variant="tonal"
          color="success"
          prepend-icon="mdi-arrow-down-circle-outline"
          @click="openTx('CHARGE')"
        >
          선결제 충전
        </v-btn>
      </v-card>

      <v-card v-else>
        <div class="divided">
          <div v-for="t in txItems" :key="t.id" class="pa-4">
            <div class="d-flex align-start ga-3">
              <div class="flex-grow-1 overflow-hidden">
                <div class="d-flex align-center flex-wrap ga-2">
                  <v-chip :color="txColor(t.type)" size="small" :prepend-icon="txIcon(t.type)">
                    {{ txLabel(t.type) }}
                  </v-chip>
                  <v-chip v-if="t.is_voided" color="secondary" size="small">취소됨</v-chip>
                </div>

                <div class="hint-text mt-2">{{ dateTime(t.occurred_at) }}</div>
                <div v-if="t.memo" class="text-body-2 mt-1">{{ t.memo }}</div>
                <div class="hint-text mt-1">
                  기록: {{ t.created_by ? t.created_by.name : '알 수 없음' }}
                </div>
                <div v-if="t.is_voided" class="hint-text mt-1">
                  취소 사유: {{ t.void_reason || '(사유 없음)' }}
                  <template v-if="t.voided_by"> · {{ t.voided_by.name }}</template>
                  <template v-if="t.voided_at"> · {{ dateTime(t.voided_at) }}</template>
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

      <v-btn
        v-if="hasMore"
        variant="outlined"
        size="large"
        block
        class="mt-4"
        :loading="txLoading"
        @click="loadTx(false)"
      >
        더 보기
      </v-btn>
    </template>

    <v-card v-else class="pa-8 text-center">
      <v-icon icon="mdi-storefront-outline" size="40" class="mb-3" style="opacity: 0.35" />
      <div class="text-body-2 text-medium-emphasis mb-4">식당 정보를 불러오지 못했습니다.</div>
      <v-btn variant="tonal" color="primary" prepend-icon="mdi-refresh" @click="refreshAll">
        다시 시도
      </v-btn>
    </v-card>

    <!-- ── 충전 / 차감 ─────────────────────────────────────────── -->
    <v-dialog v-model="txDialog" max-width="480">
      <v-card>
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon :icon="txIcon(txType)" size="20" />
          <span class="section-title">
            {{ txType === 'CHARGE' ? '선결제 충전' : '잔액에서 차감' }}
          </span>
        </v-card-title>
        <v-divider />

        <v-card-text class="pa-4">
          <div class="hint-text mb-4">
            {{
              txType === 'CHARGE'
                ? '이번에 미리 결제한 금액을 잔액에 더합니다.'
                : '선결제 잔액에서 쓴 금액을 기록합니다.'
            }}
          </div>

          <div class="field-label mb-1">{{ txType === 'CHARGE' ? '충전 금액' : '사용 금액' }}</div>
          <v-text-field
            v-model="txAmount"
            type="number"
            inputmode="numeric"
            suffix="원"
            placeholder="0"
            autofocus
          />

          <div class="field-label mb-1 mt-4">일시</div>
          <v-text-field v-model="txOccurredAt" type="datetime-local" />

          <div class="field-label mb-1 mt-4">메모 (선택)</div>
          <v-textarea v-model="txMemo" rows="2" placeholder="예: 회식 선결제" />

          <template v-if="txAmountInt > 0">
            <v-divider class="my-4" />
            <div class="d-flex align-center justify-space-between">
              <span class="field-label">처리 후 예상 잔액</span>
              <span class="amount" :class="expectedBalance < 0 ? 'text-error' : ''">
                {{ won(expectedBalance) }}
              </span>
            </div>
          </template>
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn variant="text" :disabled="txSaving" @click="txDialog = false">취소</v-btn>
          <v-btn
            color="primary"
            :loading="txSaving"
            :disabled="!canSaveTx"
            @click="saveTx(false)"
          >
            {{ txType === 'CHARGE' ? '선결제 충전하기' : '잔액에서 차감하기' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- ── 잔액 부족 확인 ──────────────────────────────────────── -->
    <v-dialog v-model="negDialog" max-width="420">
      <v-card>
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon icon="mdi-alert-outline" size="20" color="warning" />
          <span class="section-title">잔액이 부족합니다</span>
        </v-card-title>
        <v-divider />

        <v-card-text class="pa-4">
          <div class="text-body-2">{{ negMessage }}</div>
          <div class="text-body-2 mt-2">
            잔액이 부족합니다. 잔액이 마이너스로 기록됩니다. 계속할까요?
          </div>
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn variant="text" @click="negDialog = false">취소</v-btn>
          <v-btn color="error" @click="proceedNegative">계속하기</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- ── 기록 취소 ───────────────────────────────────────────── -->
    <v-dialog v-model="voidDialog" max-width="480">
      <v-card>
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon icon="mdi-close-circle-outline" size="20" />
          <span class="section-title">기록 취소</span>
        </v-card-title>
        <v-divider />

        <v-card-text class="pa-4">
          <div v-if="voidTarget" class="d-flex align-center ga-2 flex-wrap mb-3">
            <v-chip :color="txColor(voidTarget.type)" size="small" :prepend-icon="txIcon(voidTarget.type)">
              {{ txLabel(voidTarget.type) }}
            </v-chip>
            <span class="amount">{{ won(voidTarget.amount) }}</span>
            <span class="hint-text">{{ dateTime(voidTarget.occurred_at) }}</span>
          </div>

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

    <!-- ── 정보 수정 ───────────────────────────────────────────── -->
    <v-dialog v-model="editDialog" max-width="520">
      <v-card>
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon icon="mdi-pencil-outline" size="20" />
          <span class="section-title">식당 정보 수정</span>
        </v-card-title>
        <v-divider />

        <v-card-text class="pa-4">
          <div class="field-label mb-1">식당명</div>
          <v-text-field
            v-model="editForm.name"
            :error="editForm.name.trim().length === 0"
            prepend-inner-icon="mdi-storefront-outline"
          />

          <div class="field-label mb-1 mt-4">사업자등록번호</div>
          <v-text-field
            v-model="editForm.business_number"
            prepend-inner-icon="mdi-card-account-details-outline"
            hint="영수증 매칭에 사용됩니다."
          />

          <div class="field-label mb-1 mt-4">주소</div>
          <v-text-field v-model="editForm.address" prepend-inner-icon="mdi-map-marker-outline" />

          <div class="field-label mb-1 mt-4">전화</div>
          <v-text-field v-model="editForm.phone" prepend-inner-icon="mdi-phone-outline" />

          <div class="field-label mb-1 mt-4">메모</div>
          <v-textarea v-model="editForm.memo" rows="2" />
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn variant="text" :disabled="editSaving" @click="editDialog = false">취소</v-btn>
          <v-btn color="primary" :loading="editSaving" @click="saveEdit">저장</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- ── 보관 확인 ───────────────────────────────────────────── -->
    <v-dialog v-model="archiveDialog" max-width="420">
      <v-card>
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon icon="mdi-archive-arrow-down-outline" size="20" />
          <span class="section-title">
            {{ detail && detail.is_archived ? '보관 해제할까요?' : '이 식당을 보관할까요?' }}
          </span>
        </v-card-title>
        <v-divider />

        <v-card-text class="pa-4 text-body-2">
          <template v-if="detail && detail.is_archived">
            보관을 해제하면 목록과 합계에 다시 표시됩니다.
          </template>
          <template v-else>
            보관하면 목록과 총 잔액 합계에서 숨겨집니다. 거래 기록은 그대로 남고 언제든 되돌릴 수
            있습니다.
          </template>
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn variant="text" :disabled="archiveSaving" @click="archiveDialog = false">취소</v-btn>
          <v-btn color="primary" :loading="archiveSaving" @click="toggleArchive">확인</v-btn>
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
