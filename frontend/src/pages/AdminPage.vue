<script setup lang="ts">
/**
 * 사용자 관리 (CONTRACT §2.6) — 관리자 전용.
 *
 * 초대코드 확인/복사 + 구성원 역할·활성 상태 수정.
 * 본인의 역할/활성 상태는 서버에서도 막지만 화면에서도 비활성으로 표시한다.
 * 디자인 규약은 docs/DESIGN.md.
 */
import { computed, onMounted, ref } from 'vue'
import { adminApi, errorMessage } from '@/api/endpoints'
import type { UserOut } from '@/api/types'
import { dateOnly } from '@/utils/format'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const appStore = useAppStore()
const authStore = useAuthStore()

/* ------------------------------------------------------------------ */
/* 상태                                                                */
/* ------------------------------------------------------------------ */

const users = ref<UserOut[]>([])
const loading = ref(true)

const editDialog = ref(false)
const target = ref<UserOut | null>(null)
const editForm = ref({ name: '', role: 'member', is_active: true, password: '' })
const saving = ref(false)

const inviteCode = ref('')
const inviteLoading = ref(true)
const revealed = ref(false)

/* ------------------------------------------------------------------ */
/* 파생 값                                                             */
/* ------------------------------------------------------------------ */

const roleOptions = [
  { title: '관리자', value: 'admin' },
  { title: '구성원', value: 'member' },
]

const isSelf = computed(() => !!target.value && authStore.user?.id === target.value.id)
const passwordError = computed(
  () => editForm.value.password.length > 0 && editForm.value.password.length < 8,
)
const canSave = computed(
  () => editForm.value.name.trim().length > 0 && !passwordError.value && !saving.value,
)
const maskedCode = computed(() => '•'.repeat(Math.max(inviteCode.value.length, 8)))

function roleLabel(role: string): string {
  return role === 'admin' ? '관리자' : '구성원'
}
function roleColor(role: string): string {
  return role === 'admin' ? 'primary' : 'secondary'
}
function roleIcon(role: string): string {
  return role === 'admin' ? 'mdi-shield-account-outline' : 'mdi-account-circle-outline'
}
function isMe(u: UserOut): boolean {
  return authStore.user?.id === u.id
}

/* ------------------------------------------------------------------ */
/* 로드                                                                */
/* ------------------------------------------------------------------ */

async function loadUsers() {
  loading.value = true
  try {
    users.value = await adminApi.users()
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    loading.value = false
  }
}

async function loadInviteCode() {
  inviteLoading.value = true
  try {
    const res = await adminApi.inviteCode()
    inviteCode.value = res.invite_code
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    inviteLoading.value = false
  }
}

onMounted(() => {
  if (!authStore.isAdmin) return
  loadUsers()
  loadInviteCode()
})

/* ------------------------------------------------------------------ */
/* 수정                                                                */
/* ------------------------------------------------------------------ */

function openEdit(u: UserOut) {
  target.value = u
  editForm.value = { name: u.name, role: u.role, is_active: u.is_active, password: '' }
  editDialog.value = true
}

async function save() {
  const t = target.value
  if (!t) return
  if (!canSave.value) {
    if (editForm.value.name.trim().length === 0) appStore.toast('이름을 입력해 주세요.', 'warning')
    else if (passwordError.value) appStore.toast('비밀번호는 최소 8자입니다.', 'warning')
    return
  }

  const body: { name?: string; role?: string; is_active?: boolean; password?: string } = {}
  const name = editForm.value.name.trim()
  if (name !== t.name) body.name = name
  if (!isSelf.value) {
    if (editForm.value.role !== t.role) body.role = editForm.value.role
    if (editForm.value.is_active !== t.is_active) body.is_active = editForm.value.is_active
  }
  if (editForm.value.password.length > 0) body.password = editForm.value.password

  if (Object.keys(body).length === 0) {
    appStore.toast('변경된 내용이 없습니다.', 'info')
    return
  }

  saving.value = true
  try {
    const updated = await adminApi.updateUser(t.id, body)
    users.value = users.value.map((u) => (u.id === updated.id ? updated : u))
    appStore.toast(`'${updated.name}' 정보를 저장했습니다.`, 'success')
    editDialog.value = false
    if (isSelf.value) await authStore.fetchMe()
  } catch (e) {
    appStore.toast(errorMessage(e), 'error')
  } finally {
    saving.value = false
  }
}

/* ------------------------------------------------------------------ */
/* 초대코드                                                             */
/* ------------------------------------------------------------------ */

async function copyCode() {
  if (!inviteCode.value) return
  try {
    await navigator.clipboard.writeText(inviteCode.value)
    appStore.toast('초대코드를 복사했습니다.', 'success')
  } catch {
    appStore.toast('복사할 수 없습니다. 코드를 직접 선택해 복사해 주세요.', 'error')
  }
}
</script>

<template>
  <v-container class="flow-container pa-4">
    <h1 class="page-title mb-4">사용자 관리</h1>

    <v-alert v-if="!authStore.isAdmin" type="error">관리자만 볼 수 있는 화면입니다.</v-alert>

    <template v-else>
      <!-- ── 초대코드 ─────────────────────────────────────────── -->
      <v-card class="mb-6">
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon icon="mdi-key-outline" size="20" />
          <span class="section-title">초대코드</span>
        </v-card-title>
        <v-divider />

        <div class="pa-4">
          <v-skeleton-loader v-if="inviteLoading" type="text" />

          <template v-else>
            <v-sheet color="surface-variant" class="px-4 py-3">
              <div class="d-flex align-center flex-wrap ga-3">
                <code class="invite-code flex-grow-1">
                  {{ revealed ? inviteCode : maskedCode }}
                </code>
                <div class="d-flex align-center ga-2 flex-shrink-0">
                  <v-btn
                    variant="text"
                    :prepend-icon="revealed ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
                    @click="revealed = !revealed"
                  >
                    {{ revealed ? '숨기기' : '보기' }}
                  </v-btn>
                  <v-btn
                    variant="tonal"
                    color="primary"
                    prepend-icon="mdi-content-copy"
                    @click="copyCode"
                  >
                    복사
                  </v-btn>
                </div>
              </div>
            </v-sheet>

            <div class="d-flex align-start hint-text mt-3">
              <v-icon icon="mdi-shield-alert-outline" size="16" class="me-2 mt-1 flex-shrink-0" />
              <span>이 코드를 아는 사람만 가입할 수 있습니다. 외부에 공유하지 마세요.</span>
            </div>
          </template>
        </div>
      </v-card>

      <!-- ── 구성원 목록 ──────────────────────────────────────── -->
      <div class="d-flex align-center justify-space-between ga-3 mb-2">
        <h2 class="section-title">구성원 {{ users.length }}명</h2>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="loadUsers">
          새로 고침
        </v-btn>
      </div>

      <v-skeleton-loader
        v-if="loading && users.length === 0"
        type="list-item-two-line, list-item-two-line, list-item-two-line"
      />

      <v-card v-else-if="users.length === 0" class="pa-8 text-center">
        <v-icon icon="mdi-shield-account-outline" size="40" class="mb-3" style="opacity: 0.35" />
        <div class="text-body-2 text-medium-emphasis">아직 가입한 구성원이 없습니다.</div>
      </v-card>

      <v-card v-else class="table-scroll">
        <v-table density="comfortable">
          <thead>
            <tr>
              <th class="field-label text-left">이름</th>
              <th class="field-label text-left">이메일</th>
              <th class="field-label text-left">역할</th>
              <th class="field-label text-left">활성</th>
              <th class="field-label text-left">가입일</th>
              <th class="field-label text-right"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td class="text-no-wrap">
                <span class="font-weight-medium">{{ u.name }}</span>
                <v-chip v-if="isMe(u)" color="primary" size="x-small" class="ms-2">나</v-chip>
              </td>
              <td class="hint-text text-no-wrap">{{ u.email }}</td>
              <td>
                <v-chip :color="roleColor(u.role)" size="small" :prepend-icon="roleIcon(u.role)">
                  {{ roleLabel(u.role) }}
                </v-chip>
              </td>
              <td>
                <v-chip :color="u.is_active ? 'success' : 'secondary'" size="small">
                  {{ u.is_active ? '활성' : '비활성' }}
                </v-chip>
              </td>
              <td class="hint-text text-no-wrap">{{ dateOnly(u.created_at) }}</td>
              <td class="text-right">
                <v-btn variant="text" prepend-icon="mdi-pencil-outline" @click="openEdit(u)">
                  수정
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card>

      <div class="d-flex align-start hint-text mt-3">
        <v-icon icon="mdi-information-outline" size="16" class="me-2 mt-1 flex-shrink-0" />
        <span>
          본인의 역할과 활성 상태는 변경할 수 없습니다. 마지막 관리자가 잠기는 것을 막기 위한
          제한입니다.
        </span>
      </div>
    </template>

    <!-- ── 구성원 수정 ─────────────────────────────────────────── -->
    <v-dialog v-model="editDialog" max-width="480">
      <v-card>
        <v-card-title class="d-flex align-center ga-2 pa-4">
          <v-icon icon="mdi-pencil-outline" size="20" />
          <span class="section-title">구성원 수정</span>
        </v-card-title>
        <v-divider />

        <v-card-text class="pa-4">
          <div v-if="target" class="hint-text mb-4">{{ target.email }}</div>

          <div class="field-label mb-1">이름</div>
          <v-text-field
            v-model="editForm.name"
            :error="editForm.name.trim().length === 0"
            prepend-inner-icon="mdi-account-circle-outline"
          />

          <div class="field-label mb-1 mt-4">역할</div>
          <v-select v-model="editForm.role" :items="roleOptions" :disabled="isSelf" />

          <div class="d-flex align-center mt-2">
            <v-switch
              v-model="editForm.is_active"
              label="활성"
              color="primary"
              density="compact"
              inset
              hide-details
              :disabled="isSelf"
            />
          </div>

          <div v-if="isSelf" class="d-flex align-start hint-text text-warning mt-1">
            <v-icon icon="mdi-alert-outline" size="16" class="me-2 mt-1 flex-shrink-0" />
            <span>본인의 역할과 활성 상태는 변경할 수 없습니다. (마지막 관리자 잠금 방지)</span>
          </div>

          <v-divider class="my-4" />

          <div class="field-label mb-1">비밀번호 재설정 (선택)</div>
          <v-text-field
            v-model="editForm.password"
            type="password"
            autocomplete="new-password"
            :error="passwordError"
            hint="최소 8자. 비워두면 비밀번호는 그대로 유지됩니다."
            persistent-hint
          />
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn variant="text" :disabled="saving" @click="editDialog = false">취소</v-btn>
          <v-btn color="primary" :loading="saving" :disabled="!canSave" @click="save">저장</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
/* 초대코드는 자리수를 세기 쉽게 고정폭 + 자간을 넓힌다.
   styles.css 에 고정폭 서체 토큰이 없어 이 카드 전용으로만 정의한다.
   (`.v-application code` 가 본문 폰트를 !important 로 강제하므로 여기서도 !important 가 필요하다) */
code.invite-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Courier New', monospace !important;
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  font-variant-numeric: tabular-nums;
  word-break: break-all;
  color: rgb(var(--v-theme-on-surface));
}
</style>
