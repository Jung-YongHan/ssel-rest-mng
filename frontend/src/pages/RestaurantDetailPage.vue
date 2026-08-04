<script setup lang="ts">
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
const balanceColor = computed(() => {
  if (balance.value < 0) return 'text-error'
  if (detail.value?.is_low_balance) return 'text-warning'
  return 'text-primary'
})
const hasMore = computed(() => txItems.value.length < txTotal.value)
const txAmountInt = computed(() => toInt(txAmount.value))
const expectedBalance = computed(() =>
  txType.value === 'CHARGE' ? balance.value + txAmountInt.value : balance.value - txAmountInt.value,
)
const canSaveTx = computed(() => txAmountInt.value > 0 && !txSaving.value)
const canVoid = computed(() => voidReason.value.trim().length > 0 && !voiding.value)

function signedText(t: TransactionOut): string {
  if (t.is_voided) return won(t.amount)
  return (t.signed_amount > 0 ? '+' : '') + won(t.signed_amount)
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
  <v-container class="pa-3" style="max-width: 720px">
    <v-skeleton-loader v-if="loading && !detail" type="card, list-item-two-line, list-item-two-line" />

    <template v-else-if="detail">
      <!-- 헤더 -->
      <v-card variant="outlined" class="mb-3">
        <v-card-text>
          <div class="d-flex align-start justify-space-between">
            <div>
              <div class="text-h6">{{ detail.name }}</div>
              <div v-if="detail.business_number" class="text-caption text-medium-emphasis">
                {{ bizNumber(detail.business_number) }}
              </div>
            </div>
            <div class="d-flex ga-1 flex-column align-end">
              <v-chip v-if="detail.is_low_balance" color="error" size="small" variant="flat">
                잔액 부족
              </v-chip>
              <v-chip v-if="detail.is_archived" color="grey" size="small" variant="flat">
                보관됨
              </v-chip>
            </div>
          </div>

          <div v-if="detail.address" class="text-body-2 mt-2">📍 {{ detail.address }}</div>
          <div v-if="detail.phone" class="text-body-2">☎ {{ detail.phone }}</div>
          <div v-if="detail.memo" class="text-body-2 text-medium-emphasis mt-1">
            {{ detail.memo }}
          </div>

          <v-divider class="my-3" />

          <div class="text-body-2 text-medium-emphasis">현재 잔액</div>
          <div class="text-h4 font-weight-bold" :class="balanceColor">{{ won(balance) }}</div>
          <div class="text-caption text-medium-emphasis mt-1">
            마지막 사용 {{ detail.last_used_at ? relativeDate(detail.last_used_at) : '없음' }} ·
            마지막 충전 {{ detail.last_charged_at ? relativeDate(detail.last_charged_at) : '없음' }}
          </div>
        </v-card-text>
      </v-card>

      <!-- 요약 -->
      <v-row class="mb-1" dense>
        <v-col cols="4">
          <v-card variant="tonal" class="text-center">
            <v-card-text class="py-3">
              <div class="text-caption text-medium-emphasis">누적 충전</div>
              <div class="text-subtitle-1 font-weight-bold text-success">
                {{ won(detail.charge_total) }}
              </div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="4">
          <v-card variant="tonal" class="text-center">
            <v-card-text class="py-3">
              <div class="text-caption text-medium-emphasis">누적 사용</div>
              <div class="text-subtitle-1 font-weight-bold text-error">
                {{ won(detail.use_total) }}
              </div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="4">
          <v-card variant="tonal" class="text-center">
            <v-card-text class="py-3">
              <div class="text-caption text-medium-emphasis">거래 수</div>
              <div class="text-subtitle-1 font-weight-bold">{{ detail.tx_count }}건</div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <!-- 동작 -->
      <v-btn color="success" size="large" block class="mt-3" @click="openTx('CHARGE')">
        선결제 충전
      </v-btn>
      <v-btn color="error" size="large" block class="mt-2" @click="openTx('USE')">
        잔액에서 차감
      </v-btn>
      <v-btn variant="outlined" size="large" block class="mt-2" @click="goScan">
        📷 영수증으로 기록
      </v-btn>
      <div class="d-flex ga-2 mt-2">
        <v-btn variant="text" class="flex-grow-1" @click="openEdit">정보 수정</v-btn>
        <v-btn variant="text" class="flex-grow-1" @click="archiveDialog = true">
          {{ detail.is_archived ? '보관 해제' : '보관하기' }}
        </v-btn>
      </div>

      <v-divider class="my-4" />

      <!-- 거래 타임라인 -->
      <div class="d-flex align-center justify-space-between mb-2">
        <h2 class="text-subtitle-1 font-weight-bold">거래 내역</h2>
        <span class="text-caption text-medium-emphasis">전체 {{ txTotal }}건</span>
      </div>

      <v-skeleton-loader
        v-if="txLoading && txItems.length === 0"
        type="list-item-two-line, list-item-two-line, list-item-two-line"
      />

      <v-alert v-else-if="txItems.length === 0" type="info" variant="tonal">
        아직 거래 내역이 없습니다. 선결제 충전으로 시작해 보세요.
      </v-alert>

      <v-card v-else variant="outlined">
        <template v-for="(t, i) in txItems" :key="t.id">
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

            <div class="text-caption text-medium-emphasis mt-1">
              {{ dateTime(t.occurred_at) }}
            </div>
            <div v-if="t.memo" class="text-body-2 mt-1">{{ t.memo }}</div>
            <div class="text-caption text-medium-emphasis mt-1">
              기록: {{ t.created_by ? t.created_by.name : '알 수 없음' }}
            </div>
            <div v-if="t.is_voided" class="text-caption text-error mt-1">
              취소 사유: {{ t.void_reason || '(사유 없음)' }}
              <template v-if="t.voided_by"> · {{ t.voided_by.name }}</template>
              <template v-if="t.voided_at"> · {{ dateTime(t.voided_at) }}</template>
            </div>

            <div class="d-flex ga-2 mt-2">
              <v-btn
                v-if="t.has_receipt"
                size="small"
                variant="text"
                @click="openReceipt(t.receipt_id)"
              >
                🧾 영수증 보기
              </v-btn>
              <v-spacer />
              <v-btn v-if="!t.is_voided" size="small" variant="text" color="error" @click="openVoid(t)">
                기록 취소
              </v-btn>
            </div>
          </div>
        </template>
      </v-card>

      <v-btn
        v-if="hasMore"
        variant="outlined"
        size="large"
        block
        class="mt-3"
        :loading="txLoading"
        @click="loadTx(false)"
      >
        더 보기
      </v-btn>
    </template>

    <v-alert v-else type="error" variant="tonal">
      식당 정보를 불러오지 못했습니다.
      <v-btn variant="text" class="mt-2" @click="refreshAll">다시 시도</v-btn>
    </v-alert>

    <!-- 충전 / 차감 다이얼로그 -->
    <v-dialog v-model="txDialog" max-width="480">
      <v-card>
        <v-card-title class="text-subtitle-1">
          {{ txType === 'CHARGE' ? '선결제 충전' : '잔액에서 차감' }}
        </v-card-title>
        <v-card-text>
          <div class="text-body-2 text-medium-emphasis mb-3">
            {{
              txType === 'CHARGE'
                ? '이번에 미리 결제한 금액을 잔액에 더합니다.'
                : '선결제 잔액에서 쓴 금액을 기록합니다.'
            }}
          </div>
          <v-text-field
            v-model="txAmount"
            :label="txType === 'CHARGE' ? '충전 금액' : '사용 금액'"
            type="number"
            inputmode="numeric"
            suffix="원"
            density="comfortable"
            autofocus
          />
          <div class="text-caption text-medium-emphasis mb-1 mt-2">일시</div>
          <input
            v-model="txOccurredAt"
            type="datetime-local"
            class="pa-2 rounded"
            style="width: 100%; border: 1px solid rgba(128, 128, 128, 0.5)"
          />
          <v-textarea
            v-model="txMemo"
            label="메모 (선택)"
            rows="2"
            density="comfortable"
            class="mt-4"
          />
          <div v-if="txAmountInt > 0" class="text-body-2">
            처리 후 예상 잔액:
            <span :class="expectedBalance < 0 ? 'text-error font-weight-bold' : 'font-weight-bold'">
              {{ won(expectedBalance) }}
            </span>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="txSaving" @click="txDialog = false">취소</v-btn>
          <v-btn
            :color="txType === 'CHARGE' ? 'success' : 'error'"
            variant="flat"
            :loading="txSaving"
            :disabled="!canSaveTx"
            @click="saveTx(false)"
          >
            {{ txType === 'CHARGE' ? '선결제 충전하기' : '잔액에서 차감하기' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

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

    <!-- 기록 취소 다이얼로그 -->
    <v-dialog v-model="voidDialog" max-width="480">
      <v-card>
        <v-card-title class="text-subtitle-1">기록 취소</v-card-title>
        <v-card-text>
          <div v-if="voidTarget" class="text-body-2 mb-3">
            {{ txLabel(voidTarget.type) }} {{ won(voidTarget.amount) }} ·
            {{ dateTime(voidTarget.occurred_at) }}
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

    <!-- 정보 수정 다이얼로그 -->
    <v-dialog v-model="editDialog" max-width="520">
      <v-card>
        <v-card-title class="text-subtitle-1">식당 정보 수정</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="editForm.name"
            label="식당명"
            density="comfortable"
            :error="editForm.name.trim().length === 0"
          />
          <v-text-field
            v-model="editForm.business_number"
            label="사업자등록번호"
            density="comfortable"
            class="mt-3"
            hint="영수증 매칭에 사용됩니다."
          />
          <v-text-field v-model="editForm.address" label="주소" density="comfortable" class="mt-3" />
          <v-text-field v-model="editForm.phone" label="전화" density="comfortable" class="mt-3" />
          <v-textarea v-model="editForm.memo" label="메모" rows="2" density="comfortable" class="mt-3" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="editSaving" @click="editDialog = false">취소</v-btn>
          <v-btn color="primary" variant="flat" :loading="editSaving" @click="saveEdit">저장</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 보관 확인 -->
    <v-dialog v-model="archiveDialog" max-width="420">
      <v-card>
        <v-card-title class="text-subtitle-1">
          {{ detail && detail.is_archived ? '보관 해제할까요?' : '이 식당을 보관할까요?' }}
        </v-card-title>
        <v-card-text class="text-body-2">
          <template v-if="detail && detail.is_archived">
            보관을 해제하면 목록과 합계에 다시 표시됩니다.
          </template>
          <template v-else>
            보관하면 목록과 총 잔액 합계에서 숨겨집니다. 거래 기록은 그대로 남고 언제든 되돌릴 수
            있습니다.
          </template>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="archiveSaving" @click="archiveDialog = false">취소</v-btn>
          <v-btn color="primary" variant="flat" :loading="archiveSaving" @click="toggleArchive">
            확인
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
