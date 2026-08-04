<script setup lang="ts">
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
  return role === 'admin' ? 'primary' : 'grey'
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
  <v-container class="pa-3" style="max-width: 720px">
    <h1 class="text-h6 mb-3">사용자 관리</h1>

    <v-alert v-if="!authStore.isAdmin" type="error" variant="tonal">
      관리자만 볼 수 있는 화면입니다.
    </v-alert>

    <template v-else>
      <!-- 초대코드 -->
      <v-card variant="outlined" class="mb-4">
        <v-card-title class="text-subtitle-1">초대코드</v-card-title>
        <v-card-text>
          <v-skeleton-loader v-if="inviteLoading" type="text" />
          <template v-else>
            <div class="d-flex align-center ga-2 flex-wrap">
              <code class="text-h6" style="letter-spacing: 2px">
                {{ revealed ? inviteCode : maskedCode }}
              </code>
              <v-spacer />
              <v-btn size="small" variant="outlined" @click="revealed = !revealed">
                {{ revealed ? '숨기기' : '보기' }}
              </v-btn>
              <v-btn size="small" variant="flat" color="primary" @click="copyCode">복사</v-btn>
            </div>
            <div class="text-caption text-medium-emphasis mt-3">
              이 코드를 아는 사람만 가입할 수 있습니다. 외부에 공유하지 마세요.
            </div>
          </template>
        </v-card-text>
      </v-card>

      <!-- 사용자 목록 -->
      <div class="d-flex align-center justify-space-between mb-2">
        <h2 class="text-subtitle-1 font-weight-bold">구성원 {{ users.length }}명</h2>
        <v-btn size="small" variant="text" :loading="loading" @click="loadUsers">새로 고침</v-btn>
      </div>

      <v-skeleton-loader
        v-if="loading && users.length === 0"
        type="list-item-two-line, list-item-two-line, list-item-two-line"
      />
      <v-alert v-else-if="users.length === 0" type="info" variant="tonal">
        아직 가입한 구성원이 없습니다.
      </v-alert>
      <v-card v-else variant="outlined">
        <v-table density="compact">
          <thead>
            <tr>
              <th class="text-left">이름</th>
              <th class="text-left">이메일</th>
              <th class="text-left">역할</th>
              <th class="text-left">활성</th>
              <th class="text-left">가입일</th>
              <th class="text-right"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td>
                {{ u.name }}
                <span v-if="isMe(u)" class="text-caption text-medium-emphasis">(나)</span>
              </td>
              <td class="text-caption">{{ u.email }}</td>
              <td>
                <v-chip size="x-small" :color="roleColor(u.role)" variant="flat">
                  {{ roleLabel(u.role) }}
                </v-chip>
              </td>
              <td>
                <v-chip
                  size="x-small"
                  :color="u.is_active ? 'success' : 'grey'"
                  variant="tonal"
                >
                  {{ u.is_active ? '활성' : '비활성' }}
                </v-chip>
              </td>
              <td class="text-caption">{{ dateOnly(u.created_at) }}</td>
              <td class="text-right">
                <v-btn size="x-small" variant="text" @click="openEdit(u)">수정</v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card>

      <div class="text-caption text-medium-emphasis mt-3">
        본인의 역할과 활성 상태는 변경할 수 없습니다. 마지막 관리자가 잠기는 것을 막기 위한
        제한입니다.
      </div>
    </template>

    <!-- 수정 다이얼로그 -->
    <v-dialog v-model="editDialog" max-width="480">
      <v-card>
        <v-card-title class="text-subtitle-1">
          구성원 수정
          <span v-if="target" class="text-caption text-medium-emphasis ml-1">
            {{ target.email }}
          </span>
        </v-card-title>
        <v-card-text>
          <v-text-field
            v-model="editForm.name"
            label="이름"
            density="comfortable"
            :error="editForm.name.trim().length === 0"
          />

          <v-select
            v-model="editForm.role"
            :items="roleOptions"
            label="역할"
            density="comfortable"
            class="mt-3"
            :disabled="isSelf"
          />
          <v-switch
            v-model="editForm.is_active"
            label="활성"
            color="primary"
            density="compact"
            hide-details
            :disabled="isSelf"
          />
          <div v-if="isSelf" class="text-caption text-warning mt-1 mb-2">
            본인의 역할과 활성 상태는 변경할 수 없습니다. (마지막 관리자 잠금 방지)
          </div>

          <v-divider class="my-4" />

          <v-text-field
            v-model="editForm.password"
            label="비밀번호 재설정 (선택)"
            type="password"
            density="comfortable"
            autocomplete="new-password"
            :error="passwordError"
            hint="최소 8자. 비워두면 비밀번호는 그대로 유지됩니다."
            persistent-hint
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="saving" @click="editDialog = false">취소</v-btn>
          <v-btn color="primary" variant="flat" :loading="saving" :disabled="!canSave" @click="save">
            저장
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
